# app/lifecycle.py
#
# Explicit state machines for DataRequest and Submission.
# All status changes MUST go through these functions — never assign .status directly.
# Each function validates the current state, applies the transition, and returns the entity.
#
# Phase 4 will wrap the allocation + acceptance transitions in a DB transaction
# with an optimistic lock on DataRequest.version.

from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import DataRequest, Submission, RequestStatus, SubmissionStatus, AcceptedKey


# ---------------------------------------------------------------------------
# DataRequest transitions
# ---------------------------------------------------------------------------

# Valid forward transitions (current → allowed next states)
_REQUEST_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.DRAFT:               {RequestStatus.OPEN, RequestStatus.EXPIRED},
    RequestStatus.OPEN:                {RequestStatus.PARTIALLY_FULFILLED, RequestStatus.COMPLETED, RequestStatus.EXPIRED},
    RequestStatus.PARTIALLY_FULFILLED: {RequestStatus.PARTIALLY_FULFILLED, RequestStatus.COMPLETED, RequestStatus.EXPIRED},
    RequestStatus.REVIEW:              {RequestStatus.COMPLETED, RequestStatus.EXPIRED},
    RequestStatus.COMPLETED:           set(),   # terminal
    RequestStatus.EXPIRED:             set(),   # terminal
}


def transition_request(
    request: DataRequest,
    new_status: RequestStatus,
    db: Session,
    commit: bool = True,
) -> DataRequest:
    allowed = _REQUEST_TRANSITIONS.get(request.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move request from {request.status} to {new_status}",
        )
    request.status = new_status
    if commit:
        db.commit()
        db.refresh(request)
    return request


def open_request(request: DataRequest, db: Session) -> DataRequest:
    """DRAFT → OPEN. Call after escrow hold is confirmed (Phase 5)."""
    return transition_request(request, RequestStatus.OPEN, db)


def expire_request(request: DataRequest, db: Session) -> DataRequest:
    """OPEN | PARTIALLY_FULFILLED → EXPIRED (deadline passed or buyer cancelled)."""
    return transition_request(request, RequestStatus.EXPIRED, db)


def _recalculate_request_status(request: DataRequest, db: Session, commit: bool = True) -> DataRequest:
    """Called after each acceptance to move OPEN → PARTIALLY_FULFILLED → COMPLETED."""
    if request.accepted_total >= request.amount_required:
        return transition_request(request, RequestStatus.COMPLETED, db, commit=commit)
    if request.status == RequestStatus.OPEN and request.accepted_total > 0:
        return transition_request(request, RequestStatus.PARTIALLY_FULFILLED, db, commit=commit)
    if commit:
        db.commit()
        db.refresh(request)
    return request


# ---------------------------------------------------------------------------
# Submission transitions
# ---------------------------------------------------------------------------

_SUBMISSION_TRANSITIONS: dict[SubmissionStatus, set[SubmissionStatus]] = {
    SubmissionStatus.PENDING:           {SubmissionStatus.VALIDATED, SubmissionStatus.REJECTED_INVALID},
    SubmissionStatus.VALIDATED:         {SubmissionStatus.ACCEPTED, SubmissionStatus.PARTIALLY_ACCEPTED, SubmissionStatus.REJECTED},
    SubmissionStatus.REJECTED_INVALID:  set(),  # terminal
    SubmissionStatus.ACCEPTED:          {SubmissionStatus.PAID, SubmissionStatus.DISPUTED},
    SubmissionStatus.PARTIALLY_ACCEPTED:{SubmissionStatus.PAID, SubmissionStatus.DISPUTED},
    SubmissionStatus.REJECTED:          set(),  # terminal
    SubmissionStatus.PAID:              set(),  # terminal
    SubmissionStatus.DISPUTED:          {SubmissionStatus.PAID, SubmissionStatus.REJECTED},
}


def transition_submission(
    submission: Submission,
    new_status: SubmissionStatus,
    db: Session,
    commit: bool = True,
) -> Submission:
    allowed = _SUBMISSION_TRANSITIONS.get(submission.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move submission from {submission.status} to {new_status}",
        )
    submission.status = new_status
    if commit:
        db.commit()
        db.refresh(submission)
    return submission


def validate_submission(
    submission: Submission,
    validated_amount: int,
    validation_report: dict,
    db: Session,
) -> Submission:
    """PENDING → VALIDATED (or REJECTED_INVALID if validated_amount == 0)."""
    submission.validated_amount = validated_amount
    submission.validation_report = validation_report
    target = (
        SubmissionStatus.VALIDATED if validated_amount > 0
        else SubmissionStatus.REJECTED_INVALID
    )
    return transition_submission(submission, target, db)


def accept_submission(
    submission: Submission,
    request: DataRequest,
    db: Session,
) -> tuple[Submission, DataRequest]:
    """
    VALIDATED → ACCEPTED | PARTIALLY_ACCEPTED | REJECTED
    Core allocation logic — must be called inside a DB transaction (Phase 4).

    Invariants enforced:
    - accepted_amount ≤ validated_amount
    - sum(accepted_amount for request) ≤ amount_required
    """
    if submission.validated_amount is None:
        raise HTTPException(status_code=409, detail="Submission has not been validated yet")

    # Invariant: validated_amount must be ≥ 0
    assert submission.validated_amount >= 0, "validated_amount must be non-negative"

    remaining = max(0, (request.amount_required or 0) - (request.accepted_total or 0))

    # Cross-provider dedup (F3/F7): credit only the records whose key-hash has NOT
    # already been accepted for this request, capped at remaining capacity. We derive
    # `accepted` from this exact set (`creditable`) and later persist that same set —
    # so the count and the rows written to accepted_keys can never disagree.
    #
    # The previous implementation computed an overlap *count* but then persisted
    # key_hashes[:accepted] (the FIRST `accepted` hashes). On partial overlap those
    # leading hashes can be the already-accepted ones, which both corrupts future
    # dedup and violates uq_accepted_key (IntegrityError → 500). Keeping submission
    # order and filtering by membership fixes both.
    creditable: list[str] | None = None
    if getattr(submission, "key_hashes", None):
        already_accepted = {
            row.key_hash
            for row in db.query(AcceptedKey)
            .filter(AcceptedKey.request_id == str(request.id))
            .all()
        }
        new_hashes = [h for h in submission.key_hashes if h not in already_accepted]
        creditable = new_hashes[:remaining]
        accepted = len(creditable)
    else:
        accepted = min(submission.validated_amount, remaining)

    ppu_raw = request.price_per_unit or (
        (request.budget / request.amount_required) if request.amount_required else 0
    )
    price_per_unit = Decimal(str(ppu_raw or 0)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    if accepted == 0:
        new_status = SubmissionStatus.REJECTED
    elif accepted < submission.offered_amount:
        new_status = SubmissionStatus.PARTIALLY_ACCEPTED
    else:
        new_status = SubmissionStatus.ACCEPTED

    submission.accepted_amount = accepted
    submission.amount_due = (Decimal(accepted) * price_per_unit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    request.accepted_total = (request.accepted_total or 0) + accepted

    # Enforce invariant in code before committing
    if submission.accepted_amount > submission.validated_amount:
        raise HTTPException(
            status_code=409,
            detail="accepted_amount cannot exceed validated_amount",
        )

    # All three mutations (submission status, request status, accepted_keys) are
    # flushed but NOT committed here. The caller holds the FOR UPDATE lock and
    # issues the single db.commit() that ends the critical section atomically.
    submission = transition_submission(submission, new_status, db, commit=False)
    request = _recalculate_request_status(request, db, commit=False)

    # Persist the exact set we credited so future submissions see them as duplicates.
    # `creditable` already excludes already-accepted hashes and is capped at remaining,
    # so len(creditable) == accepted and no row can collide with uq_accepted_key.
    if creditable:
        for kh in creditable:
            db.add(AcceptedKey(request_id=request.id, key_hash=kh))

    db.flush()
    db.commit()
    db.refresh(submission)
    db.refresh(request)

    return submission, request


def mark_paid(submission: Submission, db: Session) -> Submission:
    """ACCEPTED | PARTIALLY_ACCEPTED → PAID (after escrow release)."""
    return transition_submission(submission, SubmissionStatus.PAID, db)


def open_dispute(submission: Submission, db: Session) -> Submission:
    """ACCEPTED | PARTIALLY_ACCEPTED → DISPUTED."""
    return transition_submission(submission, SubmissionStatus.DISPUTED, db)


def resolve_dispute(
    submission: Submission,
    outcome: str,   # "paid" or "rejected"
    db: Session,
) -> Submission:
    """DISPUTED → PAID | REJECTED."""
    if outcome == "paid":
        return transition_submission(submission, SubmissionStatus.PAID, db)
    elif outcome == "rejected":
        return transition_submission(submission, SubmissionStatus.REJECTED, db)
    raise HTTPException(status_code=400, detail="outcome must be 'paid' or 'rejected'")
