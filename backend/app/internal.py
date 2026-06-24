# app/internal.py
#
# Internal callback surface for the Rust ingest service (async path).
#
# The Rust worker processes a job and POSTs its report here; Python — the single
# writer to the core schema — flips the submission to VALIDATED / REJECTED_INVALID
# inside its own transaction and bulk-populates the dedup staging table. Idempotent:
# a report for an already-processed submission is a no-op, so at-least-once SQS
# delivery + retries are safe.
#
# Gated by a shared secret (INGEST_CALLBACK_SECRET) presented in the
# X-Internal-Secret header. If the secret is not configured the endpoint is
# DISABLED (503) — it is never mounted on the public gateway in production.
# Contract matches rust-ingest worker.rs (nested {submission_id, content_hash, report}).

import os
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi import Depends

from app.db import get_db
from app.models import Submission, SubmissionStatus, SubmissionKeyStaging
from app.lifecycle import validate_submission

logger = logging.getLogger("internal")
router = APIRouter()


class IngestReportIn(BaseModel):
    status: str | None = None            # "VALIDATED" | "REJECTED_INVALID"
    validated_amount: int = 0
    dataset_hash: str | None = None
    quality_score: float = 0.0
    sample: list | None = None
    key_hashes: list[str] | None = None
    validation_report: dict | None = None
    media_meta: dict | None = None
    perceptual_hashes: list | None = None
    errors: list[str] | None = None


class IngestResultIn(BaseModel):
    submission_id: str
    content_hash: str | None = None
    report: IngestReportIn


def _require_secret(x_internal_secret: str | None) -> None:
    expected = os.getenv("INGEST_CALLBACK_SECRET", "")
    if not expected:
        # Secret not configured → the callback is disabled, not merely unauthorized.
        raise HTTPException(status_code=503, detail="ingest callback disabled")
    if x_internal_secret != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/ingest-result")
def ingest_result(
    body: IngestResultIn,
    x_internal_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _require_secret(x_internal_secret)
    report = body.report

    submission = (
        db.query(Submission)
        .filter(Submission.id == body.submission_id, Submission.is_deleted == False)  # noqa: E712
        .first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="submission not found")

    # Idempotency: only a still-PENDING submission is transitioned. A repeat callback
    # (SQS redelivery / reprocess) is a no-op and does NOT duplicate staging rows.
    if submission.status != SubmissionStatus.PENDING:
        return {"status": "already_processed", "current": submission.status.value}

    validation_report = dict(report.validation_report or {})
    validation_report.setdefault("engine", "rust")
    if report.errors:
        validation_report["errors"] = report.errors

    if report.dataset_hash:
        submission.dataset_hash = report.dataset_hash
    if report.quality_score:
        submission.quality_score = report.quality_score

    # validate_submission picks VALIDATED vs REJECTED_INVALID from the amount, so a
    # corrupt/REJECTED_INVALID report (amount 0) lands correctly.
    amount = 0 if report.status == "REJECTED_INVALID" else report.validated_amount
    validate_submission(
        submission=submission,
        validated_amount=amount,
        validation_report=validation_report,
        db=db,
    )

    # Bulk-populate the dedup staging table (the allocation anti-join reads it),
    # UNLESS the worker already COPYed it. Guard on existing rows so worker-COPY and
    # this callback compose without duplicates.
    if amount > 0 and report.key_hashes:
        already = (
            db.query(SubmissionKeyStaging.id)
            .filter(SubmissionKeyStaging.submission_id == submission.id)
            .first()
        )
        if not already:
            for i, kh in enumerate(report.key_hashes):
                db.add(SubmissionKeyStaging(submission_id=submission.id, ordinal=i, key_hash=kh))
            db.commit()

    logger.info("ingest-result %s sub=%s amount=%s", submission.status.value, body.submission_id, amount)
    return {"submission_status": submission.status.value, "validated_amount": amount}
