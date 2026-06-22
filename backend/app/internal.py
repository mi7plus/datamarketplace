# app/internal.py
#
# Internal callback for the Rust ingest service (Rust ingest plan, async path).
# The Rust worker processes a file off the queue and POSTs its report here; Python
# flips the submission to VALIDATED / REJECTED_INVALID and populates the dedup
# staging table. Python remains the SOLE writer to the core schema — Rust never
# writes money/lifecycle rows.
#
# Auth: a shared secret in the X-Internal-Secret header (INGEST_CALLBACK_SECRET).
# If the secret is unset the endpoint is disabled (503) — it's an internal,
# VPC-only surface, never public.
#
# Idempotency: the job is keyed by submission_id + content_hash. The callback is a
# no-op if the submission has already left PENDING, so re-delivery is safe.

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.lifecycle import transition_submission
from app.models import Submission, SubmissionStatus, SubmissionKeyStaging

router = APIRouter(prefix="/internal", tags=["internal"])


class IngestReportIn(BaseModel):
    status: str                       # "VALIDATED" | "REJECTED_INVALID"
    validated_amount: int = 0
    dataset_hash: str | None = None
    quality_score: float = 0.0
    sample: list[dict] = Field(default_factory=list)
    key_hashes: list[str] = Field(default_factory=list)
    validation_report: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class IngestResultIn(BaseModel):
    submission_id: str
    content_hash: str | None = None   # idempotency key component (== dataset_hash)
    report: IngestReportIn


def _require_secret(x_internal_secret: str | None = Header(default=None)) -> None:
    secret = os.getenv("INGEST_CALLBACK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Internal ingest callback is disabled")
    if not x_internal_secret or not hmac.compare_digest(x_internal_secret, secret):
        raise HTTPException(status_code=401, detail="Invalid internal secret")


@router.post("/ingest-result")
def ingest_result(
    body: IngestResultIn,
    db: Session = Depends(get_db),
    _: None = Depends(_require_secret),
):
    sub = db.query(Submission).filter(Submission.id == body.submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Idempotent: only the first report for a PENDING submission takes effect.
    if sub.status != SubmissionStatus.PENDING:
        return {"status": "already_processed", "submission_status": sub.status.value}

    report = body.report
    sub.validated_amount = report.validated_amount
    sub.dataset_hash = report.dataset_hash
    sub.validation_report = report.validation_report
    sub.quality_score = report.quality_score
    sub.key_hashes = report.key_hashes

    # Populate the dedup staging table (the allocation step reads from here) —
    # UNLESS the Rust worker already bulk-COPYed it on the async path. Guarding on
    # existing rows lets worker-COPY and this callback compose without duplicates.
    already_staged = (
        db.query(SubmissionKeyStaging.id)
        .filter(SubmissionKeyStaging.submission_id == sub.id)
        .first()
    )
    if not already_staged:
        for i, kh in enumerate(report.key_hashes):
            db.add(SubmissionKeyStaging(submission_id=sub.id, ordinal=i, key_hash=kh))

    valid = report.status == "VALIDATED" and report.validated_amount > 0
    new_status = SubmissionStatus.VALIDATED if valid else SubmissionStatus.REJECTED_INVALID
    transition_submission(sub, new_status, db, commit=True)

    return {"status": "ok", "submission_status": new_status.value, "validated_amount": sub.validated_amount}
