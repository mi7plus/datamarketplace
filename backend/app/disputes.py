# app/disputes.py
#
# Dispute flow: buyer opens dispute on an ACCEPTED/PARTIALLY_ACCEPTED submission,
# pausing its escrow release. Admin resolves → PAID (release) or REJECTED (refund).
#
# Only one open dispute per submission. Resolution is manual (admin only for MVP).

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as PydanticModel
from sqlalchemy.orm import Session
from datetime import datetime

from app.db import get_db
from app.models import (
    Dispute, Submission, DataRequest, UserAuth as User,
    SubmissionStatus, UserRole, UserAnalytics,
)
from app.auth import get_current_user
from app.lifecycle import open_dispute, resolve_dispute
from app.payments import get_payment_provider, ledger_balance

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DisputeOpen(PydanticModel):
    reason: str


class DisputeResolve(PydanticModel):
    outcome: str          # "paid" | "rejected"
    notes: str | None = None


# ---------------------------------------------------------------------------
# Open a dispute (buyer only, ACCEPTED or PARTIALLY_ACCEPTED)
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/open")
def open(
    submission_id: str,
    data: DisputeOpen,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    submission = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.is_deleted == False,
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    if not data_request or str(data_request.requester_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Only the requester can open a dispute")

    if submission.status not in (SubmissionStatus.ACCEPTED, SubmissionStatus.PARTIALLY_ACCEPTED):
        raise HTTPException(
            status_code=409,
            detail=f"Disputes can only be opened on ACCEPTED or PARTIALLY_ACCEPTED submissions (current: {submission.status})",
        )

    existing = db.query(Dispute).filter(Dispute.submission_id == submission_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="A dispute already exists for this submission")

    # Transition submission to DISPUTED (pauses escrow release)
    submission = open_dispute(submission, db)

    dispute = Dispute(
        submission_id=submission_id,
        opened_by_id=str(current_user.id),
        reason=data.reason,
        status="open",
    )
    db.add(dispute)
    db.commit()
    db.refresh(dispute)

    return {
        "dispute_id": str(dispute.id),
        "submission_id": submission_id,
        "status": dispute.status,
        "reason": dispute.reason,
    }


# ---------------------------------------------------------------------------
# Resolve a dispute (admin only)
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/resolve")
def resolve(
    submission_id: str,
    data: DisputeResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can resolve disputes")

    dispute = db.query(Dispute).filter(Dispute.submission_id == submission_id).first()
    if not dispute or dispute.status != "open":
        raise HTTPException(status_code=404, detail="Open dispute not found for this submission")

    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()

    if data.outcome not in ("paid", "rejected"):
        raise HTTPException(status_code=400, detail="outcome must be 'paid' or 'rejected'")

    # Transition submission state
    submission = resolve_dispute(submission, data.outcome, db)

    payment = get_payment_provider()

    if data.outcome == "paid":
        # Release escrow to provider
        payment.release_to_provider(submission, db)
        dispute.status = "resolved_paid"
    else:
        # Refund the disputed amount to buyer
        disputed_amount = submission.amount_due or 0.0
        if disputed_amount > 0:
            payment.refund_to_buyer(data_request, disputed_amount, db)
        dispute.status = "resolved_rejected"

    dispute.notes = data.notes
    db.commit()

    return {
        "dispute_id": str(dispute.id),
        "submission_id": submission_id,
        "outcome": data.outcome,
        "submission_status": submission.status,
        "notes": dispute.notes,
    }


# ---------------------------------------------------------------------------
# List open disputes (admin only)
# ---------------------------------------------------------------------------

@router.get("/")
def list_disputes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")

    disputes = (
        db.query(Dispute)
        .filter(Dispute.status == "open")
        .order_by(Dispute.created_at.desc())
        .all()
    )
    return [
        {
            "dispute_id": str(d.id),
            "submission_id": str(d.submission_id),
            "opened_by_id": str(d.opened_by_id),
            "reason": d.reason,
            "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in disputes
    ]


# ---------------------------------------------------------------------------
# Get dispute for a submission (requester can see their own)
# ---------------------------------------------------------------------------

@router.get("/{submission_id}")
def get_dispute(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dispute = db.query(Dispute).filter(Dispute.submission_id == submission_id).first()
    if not dispute:
        raise HTTPException(status_code=404, detail="No dispute for this submission")

    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()

    if (
        current_user.role != UserRole.ADMIN
        and str(data_request.requester_id) != str(current_user.id)
        and str(submission.provider_id) != str(current_user.id)
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "dispute_id": str(dispute.id),
        "submission_id": submission_id,
        "opened_by_id": str(dispute.opened_by_id),
        "reason": dispute.reason,
        "notes": dispute.notes,
        "status": dispute.status,
        "created_at": dispute.created_at.isoformat() if dispute.created_at else None,
    }
