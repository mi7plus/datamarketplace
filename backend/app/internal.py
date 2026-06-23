# app/internal.py
#
# Internal callback surface for the Rust ingest service (async path).
#
# The Rust worker processes a job and POSTs its report here; Python — the single
# writer to the core schema — flips the submission to VALIDATED / REJECTED_INVALID
# inside its own transaction. Idempotent: a report for an already-processed
# submission is a no-op, so at-least-once SQS delivery + retries are safe.
#
# Gated by a shared secret (INGEST_INTERNAL_TOKEN). This router is NOT mounted on
# the public API gateway in production — internal VPC only.

import os
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Submission, SubmissionStatus
from app.lifecycle import validate_submission

logger = logging.getLogger("internal")
router = APIRouter()


class IngestResultIn(BaseModel):
    submission_id: str
    status: str | None = None            # "VALIDATED" | "REJECTED_INVALID"
    validated_amount: int = 0
    dataset_hash: str | None = None
    total_rows: int = 0
    rejected_rows: int = 0
    duplicate_rows: int = 0
    quality_score: float = 0.0
    stats: dict | None = None
    sample: list | None = None
    key_hash_ref: str | None = None
    key_hash_count: int = 0
    media_meta: dict | None = None
    perceptual_hashes: dict | None = None
    errors: list[str] | None = None


def _require_token(x_internal_token: str | None) -> None:
    expected = os.getenv("INGEST_INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/ingest-result")
def ingest_result(
    body: IngestResultIn,
    x_internal_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _require_token(x_internal_token)

    submission = (
        db.query(Submission)
        .filter(Submission.id == body.submission_id, Submission.is_deleted == False)  # noqa: E712
        .first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="submission not found")

    # Idempotency: only a still-PENDING submission gets transitioned. A repeat
    # callback (SQS redelivery / reprocess) is a no-op.
    if submission.status != SubmissionStatus.PENDING:
        return {"status": "noop", "current": str(submission.status)}

    report = {
        "total_rows": body.total_rows,
        "conforming_rows": body.validated_amount,
        "rejected_rows": body.rejected_rows,
        "duplicate_rows": body.duplicate_rows,
        "sample": body.sample or [],
        "stats": body.stats or {},
        "key_hash_ref": body.key_hash_ref,
        "media_meta": body.media_meta,
        "perceptual_hashes": body.perceptual_hashes,
        "errors": body.errors or [],
        "engine": "rust",
    }

    if body.dataset_hash:
        submission.dataset_hash = body.dataset_hash
    if body.quality_score:
        submission.quality_score = body.quality_score

    # validate_submission picks VALIDATED vs REJECTED_INVALID from the amount, so
    # a corrupt-media (amount 0) or REJECTED_INVALID report both land correctly.
    amount = 0 if body.status == "REJECTED_INVALID" else body.validated_amount
    validate_submission(
        submission=submission,
        validated_amount=amount,
        validation_report=report,
        db=db,
    )
    outcome = "validated" if amount > 0 else "rejected"
    logger.info("ingest-result %s sub=%s amount=%s", outcome, body.submission_id, amount)
    return {"status": outcome}
