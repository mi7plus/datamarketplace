# app/submissions.py
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from app.db import get_db
from app.models import Submission, DataRequest, UserAuth as User, SubmissionStatus, RequestStatus, UserRole
from app.auth import get_current_user
from app.ingest import validate_dataset
from app.lifecycle import validate_submission, accept_submission, transition_submission, expire_request, mark_paid
from app.storage import get_storage
from app.payments import get_payment_provider, ledger_balance
from app.reviews import _increment_transactions

ACCEPTANCE_WINDOW_HOURS = int(os.getenv("ACCEPTANCE_WINDOW_HOURS", "72"))

logger = logging.getLogger("submissions")

router = APIRouter()

MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = {"csv", "jsonl"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_submission_or_404(submission_id: str, db: Session) -> Submission:
    s = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.is_deleted == False,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")
    return s


def _require_request_owner(request: DataRequest, current_user: User) -> None:
    # 404, not 403: never confirm to a non-owner that this object exists (S1).
    if str(request.requester_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Request not found")


def _serialize_submission(s: Submission) -> dict:
    return {
        "id": str(s.id),
        "request_id": str(s.request_id),
        "provider_id": str(s.provider_id),
        "status": s.status,
        "offered_amount": s.offered_amount,
        "validated_amount": s.validated_amount,
        "accepted_amount": s.accepted_amount,
        "amount_due": s.amount_due,
        "content_link": s.content_link,
        "dataset_hash": s.dataset_hash,
        "validation_report": s.validation_report,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "accepted_at": s.accepted_at.isoformat() if s.accepted_at else None,
        "confirm_by": (
            (s.accepted_at + timedelta(hours=ACCEPTANCE_WINDOW_HOURS)).isoformat()
            if s.accepted_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Provider: submit a dataset
# ---------------------------------------------------------------------------

@router.post("/")
async def create_submission(
    request_id: UUID = Form(...),
    offered_amount: int = Form(...),
    file: UploadFile = File(...),
    warranted: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data_request = db.query(DataRequest).filter(
        DataRequest.id == str(request_id),
        DataRequest.is_deleted == False,
    ).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    if data_request.status not in ("open", "partially_fulfilled"):
        raise HTTPException(
            status_code=409,
            detail=f"Request is not accepting submissions (status: {data_request.status})",
        )

    # Role gate: only providers submit datasets (requesters post requests).
    if current_user.role != UserRole.PROVIDER:
        raise HTTPException(status_code=403, detail="Only providers can submit data")

    if not warranted:
        raise HTTPException(
            status_code=422,
            detail="Provider warranties must be affirmed before submitting",
        )

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Only CSV and JSONL files are accepted, got .{ext}")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 100 MB limit")

    result = validate_dataset(
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        spec=data_request.spec,
    )

    storage_key = f"{request_id}/{current_user.id}/{file.filename}"
    storage_location = get_storage().save(storage_key, file_bytes)

    # Store a timestamped warranty affirmation in owner_signature
    warranty_sig = (
        f"warranted by {current_user.email} at {datetime.utcnow().isoformat()}Z "
        f"— rights confirmed, no unconsented personal data"
    )

    submission = Submission(
        request_id=request_id,
        provider_id=current_user.id,
        content_link=file.filename,
        offered_amount=offered_amount,
        accepted_amount=0,
        file_size_bytes=len(file_bytes),
        mime_type=file.content_type or ("text/csv" if ext == "csv" else "application/x-jsonlines"),
        storage_location=storage_location,
        dataset_hash=result.dataset_hash,
        owner_signature=warranty_sig,
        key_hashes=result.key_hashes or None,
    )
    db.add(submission)
    db.flush()

    validate_submission(
        submission=submission,
        validated_amount=result.validated_amount,
        validation_report={**result.validation_report, "sample": result.sample},
        db=db,
    )

    return _serialize_submission(submission)


# ---------------------------------------------------------------------------
# Buyer: accept a submission (the core allocation — transactional)
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/accept")
def accept(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Allocate validated units from this submission against the request's remaining
    capacity. Runs inside ONE transaction with row-level locks on BOTH data_requests
    AND submissions (acquired in that order — always request-first to prevent deadlocks).

    Double-accept protection: the submission is re-checked under the submission lock
    AFTER the request lock is held, so two concurrent accepts of the same submission
    serialise here and only the first proceeds.

    This is the likeliest money bug — the lock order is non-negotiable.
    """
    # Quick pre-check outside the lock (not the authoritative check — see below)
    submission = _get_submission_or_404(submission_id, db)
    request_id = str(submission.request_id)

    # --- BEGIN critical section ---
    # Lock order: request first, then submission. Consistent everywhere → no deadlock.
    data_request = (
        db.execute(
            select(DataRequest)
            .where(DataRequest.id == request_id)
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")

    # Ownership FIRST (S1): a non-owner must get 404 regardless of the submission's
    # status — never leak existence or state to someone who doesn't own the request.
    _require_request_owner(data_request, current_user)

    # Re-load the submission under its own lock INSIDE the critical section.
    # The pre-check above may have seen VALIDATED before a concurrent accept committed.
    submission = (
        db.execute(
            select(Submission)
            .where(Submission.id == submission_id)
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if not submission or submission.status != SubmissionStatus.VALIDATED:
        raise HTTPException(
            status_code=409,
            detail=f"Submission is no longer available for acceptance (status: {getattr(submission, 'status', 'not found')})",
        )

    if data_request.status not in (RequestStatus.OPEN, RequestStatus.PARTIALLY_FULFILLED):
        raise HTTPException(
            status_code=409,
            detail=f"Request is not accepting acceptances (status: {data_request.status})",
        )

    # Check for deadline expiry lazily on read
    if data_request.deadline and data_request.deadline < datetime.utcnow():
        expire_request(data_request, db)
        raise HTTPException(status_code=409, detail="Request has expired — escrow will be refunded")

    # Bump version for optimistic-concurrency detection by external callers
    data_request.version = (data_request.version or 1) + 1

    # Run allocation (modifies submission + request in-place, sets accepted_at, and
    # commits once). accepted_at is anchored INSIDE this transaction (F9) so an
    # ACCEPTED submission can never end up with a NULL window anchor.
    submission, data_request = accept_submission(submission, data_request, db)
    # --- END critical section (accept_submission commits) ---

    # Escrow stays held. Buyer must call /confirm (or wait for auto-release after window).
    return {
        "submission": _serialize_submission(submission),
        "request_status": data_request.status,
        "request_accepted_total": data_request.accepted_total,
        "request_remaining": (data_request.amount_required or 0) - (data_request.accepted_total or 0),
        "confirm_by": (
            (submission.accepted_at + timedelta(hours=ACCEPTANCE_WINDOW_HOURS)).isoformat()
            if submission.accepted_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Buyer: confirm a submission (releases escrow → PAID)
# Also auto-releases if the acceptance window has elapsed (called lazily here).
# ---------------------------------------------------------------------------

def _release_and_pay(submission_id: str, db: Session) -> Submission:
    """
    Release escrow for an ACCEPTED/PARTIALLY_ACCEPTED submission and mark PAID.

    The single locked chokepoint for ALL release triggers (confirm / claim /
    lazy-download / sweep). Re-loads BOTH rows FOR UPDATE — request first, then
    submission, the same lock order as accept() — and re-asserts status under the
    lock. Concurrent triggers therefore serialise here and only the first releases;
    a second caller sees PAID and returns a clean no-op (no double release, no 500).

    The cheap pre-checks in callers (_auto_release_if_due, confirm, claim) are an
    optimisation only — this re-check inside the lock is the authoritative one.
    """
    submission_pre = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission_pre:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Lock order: request first, then submission (matches accept()).
    data_request = (
        db.execute(
            select(DataRequest)
            .where(DataRequest.id == str(submission_pre.request_id))
            .with_for_update()
        )
        .scalars()
        .first()
    )
    submission = (
        db.execute(
            select(Submission)
            .where(Submission.id == submission_id)
            .with_for_update()
        )
        .scalars()
        .first()
    )

    # Decisive re-check UNDER the lock.
    if submission.status == SubmissionStatus.PAID:
        return submission                       # already released — clean no-op
    if submission.status not in ACCEPTED_STATUSES:
        return submission
    if _has_open_dispute(submission.id, db):
        return submission                       # dispute opened in the meantime

    payment = get_payment_provider()
    payment.release_to_provider(submission, db)
    submission = mark_paid(submission, db)
    _increment_transactions(str(data_request.requester_id), successful=True, db=db)
    _increment_transactions(str(submission.provider_id), successful=True, db=db)

    # Refund genuine surplus (rounding leftover / under-fill) to the buyer — but ONLY
    # once no submissions remain awaiting release. Otherwise, on a COMPLETED request
    # with several accepted submissions, releasing the first would see the others'
    # not-yet-released amount_due as "remaining" and wrongly refund it (driving the
    # ledger negative). The current submission is already PAID, so it's excluded here.
    if data_request.status == RequestStatus.COMPLETED:
        pending = (
            db.query(Submission)
            .filter(
                Submission.request_id == str(data_request.id),
                Submission.status.in_(ACCEPTED_STATUSES),
                Submission.is_deleted == False,
            )
            .count()
        )
        if pending == 0:
            balance = ledger_balance(db, data_request.id)
            if balance["remaining"] > Decimal("0"):
                payment.refund_to_buyer(data_request, balance["remaining"], db)
    db.commit()
    return submission


# ---------------------------------------------------------------------------
# Auto-release helpers (shared by /download lazy check, /claim, and the sweep)
# All three MUST go through these so the release rules can never drift.
# ---------------------------------------------------------------------------

ACCEPTED_STATUSES = (SubmissionStatus.ACCEPTED, SubmissionStatus.PARTIALLY_ACCEPTED)


def _window_elapsed(submission: Submission) -> bool:
    """True if the acceptance window has passed since accepted_at."""
    return bool(
        submission.accepted_at
        and datetime.utcnow() > submission.accepted_at + timedelta(hours=ACCEPTANCE_WINDOW_HOURS)
    )


def _has_open_dispute(submission_id, db: Session) -> bool:
    from app.models import Dispute
    return (
        db.query(Dispute)
        .filter(Dispute.submission_id == str(submission_id), Dispute.status == "open")
        .first()
        is not None
    )


def _auto_release_if_due(submission: Submission, db: Session) -> bool:
    """
    Release escrow iff the submission is ACCEPTED/PARTIALLY_ACCEPTED, the acceptance
    window has elapsed, and no dispute is open. Returns True if it released.

    The status/window/dispute checks here are a CHEAP PRE-FILTER only — they avoid
    taking the row lock for the common case where nothing is due. The authoritative
    re-check happens inside _release_and_pay under FOR UPDATE, so correctness does
    not depend on these pre-checks. Shared by lazy /download, /claim, and the sweep.
    """
    if submission.status not in ACCEPTED_STATUSES:
        return False
    if not _window_elapsed(submission):
        return False
    if _has_open_dispute(submission.id, db):
        return False
    released = _release_and_pay(str(submission.id), db)
    return released.status == SubmissionStatus.PAID


def run_auto_release_sweep(db: Session) -> int:
    """
    Release every ACCEPTED/PARTIALLY_ACCEPTED submission whose acceptance window has
    elapsed and that has no open dispute — regardless of whether the buyer ever
    returned. This is what guarantees providers are never stranded.

    Returns the number of submissions released. Idempotent: release_to_provider is
    keyed by submission id and the ledger ref is unique, so re-running is safe.
    """
    cutoff = datetime.utcnow() - timedelta(hours=ACCEPTANCE_WINDOW_HOURS)
    due = (
        db.query(Submission)
        .filter(
            Submission.status.in_(ACCEPTED_STATUSES),
            Submission.accepted_at.isnot(None),
            Submission.accepted_at < cutoff,
            Submission.is_deleted == False,
        )
        .all()
    )
    released = 0
    for sub in due:
        # Per-row isolation: one failing release (e.g. a provider with no connected
        # Stripe account) must not abort the whole batch.
        try:
            if _auto_release_if_due(sub, db):
                released += 1
        except Exception:
            db.rollback()
            logger.exception("auto-release failed for submission %s", sub.id)
    return released


@router.post("/{submission_id}/confirm")
def confirm(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Buyer explicitly confirms the dataset is satisfactory → releases escrow now,
    before the acceptance window elapses. This is the buyer-driven path.

    Providers who are never confirmed are NOT stranded: the background sweep
    (run_auto_release_sweep) and the provider-reachable POST /{id}/claim endpoint
    both release ACCEPTED submissions once the window passes with no open dispute.
    """
    submission = _get_submission_or_404(submission_id, db)

    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    _require_request_owner(data_request, current_user)

    if submission.status not in ACCEPTED_STATUSES:
        if submission.status == SubmissionStatus.PAID:
            return {"submission": _serialize_submission(submission), "released": False}
        raise HTTPException(
            status_code=409,
            detail=f"Only ACCEPTED/PARTIALLY_ACCEPTED submissions can be confirmed (current: {submission.status})",
        )

    # A dispute pauses release until an admin resolves it
    if _has_open_dispute(submission.id, db):
        raise HTTPException(status_code=409, detail="A dispute is open — release is paused until admin resolves it")

    submission = _release_and_pay(str(submission.id), db)
    released = submission.status == SubmissionStatus.PAID
    return {"submission": _serialize_submission(submission), "released": released}


# ---------------------------------------------------------------------------
# Provider: claim payment after the acceptance window (buyer-independent)
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/claim")
def claim(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Provider self-service release. Once the acceptance window has elapsed and no
    dispute is open, the provider can release their own escrow without the buyer
    ever calling /confirm or /download. Complements the background sweep so a
    provider is never stranded by an absent buyer.
    """
    submission = _get_submission_or_404(submission_id, db)
    if str(submission.provider_id) != str(current_user.id):
        # 404, not 403 — don't confirm this submission exists to a non-owner (S1).
        raise HTTPException(status_code=404, detail="Submission not found")

    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")

    if submission.status == SubmissionStatus.PAID:
        return {"submission": _serialize_submission(submission), "released": False, "detail": "Already paid"}
    if submission.status not in ACCEPTED_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Submission is not awaiting release (status: {submission.status})",
        )
    if not _window_elapsed(submission):
        raise HTTPException(
            status_code=409,
            detail="Acceptance window has not elapsed yet — the buyer may still confirm or open a dispute",
        )
    if _has_open_dispute(submission.id, db):
        raise HTTPException(status_code=409, detail="A dispute is open — release is paused until admin resolves it")

    submission = _release_and_pay(str(submission.id), db)
    released = submission.status == SubmissionStatus.PAID
    return {"submission": _serialize_submission(submission), "released": released}


# ---------------------------------------------------------------------------
# Buyer: reject a submission
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/reject")
def reject(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    submission = _get_submission_or_404(submission_id, db)

    # Ownership FIRST (S1): a non-owner gets 404 regardless of the submission status.
    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    _require_request_owner(data_request, current_user)

    if submission.status != SubmissionStatus.VALIDATED:
        raise HTTPException(
            status_code=409,
            detail=f"Only VALIDATED submissions can be rejected (current: {submission.status})",
        )

    submission = transition_submission(submission, SubmissionStatus.REJECTED, db)
    return _serialize_submission(submission)


# ---------------------------------------------------------------------------
# Expiry: mark a request expired (lazy check or explicit buyer cancel)
# ---------------------------------------------------------------------------

@router.post("/requests/{request_id}/expire")
def expire(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Buyer can manually close a request early, or this runs on deadline check."""
    data_request = db.query(DataRequest).filter(
        DataRequest.id == request_id,
        DataRequest.is_deleted == False,
    ).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    _require_request_owner(data_request, current_user)
    data_request = expire_request(data_request, db)
    # Refund unspent escrow
    from decimal import Decimal
    balance = ledger_balance(db, data_request.id)
    if balance["remaining"] > Decimal("0"):
        get_payment_provider().refund_to_buyer(data_request, balance["remaining"], db)
    db.commit()
    return {"status": data_request.status}


# ---------------------------------------------------------------------------
# Read: provider history + buyer view
# ---------------------------------------------------------------------------

@router.get("/my")
def my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subs = (
        db.query(Submission)
        .filter(Submission.provider_id == current_user.id, Submission.is_deleted == False)
        .order_by(Submission.created_at.desc())
        .all()
    )
    return [_serialize_submission(s) for s in subs]


@router.get("/request/{request_id}")
def submissions_for_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data_request = db.query(DataRequest).filter(DataRequest.id == request_id).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    _require_request_owner(data_request, current_user)

    subs = (
        db.query(Submission)
        .filter(
            Submission.request_id == request_id,
            Submission.status != SubmissionStatus.PENDING,
            Submission.is_deleted == False,
        )
        .order_by(Submission.created_at.desc())
        .all()
    )
    return [_serialize_submission(s) for s in subs]


# ---------------------------------------------------------------------------
# Gated delivery: sample (pre-payment) + full file (PAID only)
# ---------------------------------------------------------------------------

@router.get("/{submission_id}/sample")
def get_sample(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the sample rows from the validation report.
    Available to the requester for any VALIDATED+ submission on their request,
    and to the provider for their own submission.
    Sample is stored in validation_report['sample'] — never the full file.
    """
    submission = _get_submission_or_404(submission_id, db)
    _assert_sample_access(submission, current_user, db)

    sample = (submission.validation_report or {}).get("sample", [])
    return {
        "submission_id": str(submission.id),
        "status": submission.status,
        "validated_amount": submission.validated_amount,
        "sample": sample,
        "sample_count": len(sample),
    }


@router.get("/{submission_id}/download")
def download(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Issue a short-lived pre-signed URL for the full dataset.
    ONLY issued when submission is PAID.
    Never issued for PENDING / VALIDATED / REJECTED* — buyer must pay first.
    """
    submission = _get_submission_or_404(submission_id, db)

    # Gate: only the requester who paid can download
    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    _require_request_owner(data_request, current_user)

    # Auto-release check: if window has elapsed and no dispute, release now (lazy).
    # Shares one helper with /claim and the sweep so the rules can't drift.
    # (_release_and_pay commits, expiring `submission`; its status is re-read below.)
    _auto_release_if_due(submission, db)

    # Status gate — full file for PAID or during the acceptance window (buyer verifying)
    allowed_statuses = (SubmissionStatus.PAID, SubmissionStatus.ACCEPTED, SubmissionStatus.PARTIALLY_ACCEPTED)
    if submission.status not in allowed_statuses:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Full file is only available for PAID or ACCEPTED submissions "
                f"(current status: {submission.status}). "
                "Use /sample to preview before accepting."
            ),
        )

    if not submission.storage_location:
        raise HTTPException(status_code=404, detail="No file on record for this submission")

    # Honour takedown: if access_expiry is in the past (set by takedown), deny
    if submission.access_expiry and submission.access_expiry < datetime.utcnow():
        raise HTTPException(status_code=410, detail="This dataset has been taken down and is no longer available")

    url = get_storage().presigned_url(submission.storage_location)

    # Record download in access_expiry (best-effort — not blocking)
    try:
        from datetime import timedelta
        submission.access_expiry = datetime.utcnow() + timedelta(
            seconds=int(os.getenv("PRESIGNED_URL_TTL_SECONDS", "3600"))
        )
        db.commit()
    except Exception:
        pass

    return {
        "url": url,
        "expires_in_seconds": int(os.getenv("PRESIGNED_URL_TTL_SECONDS", "3600")),
        "submission_id": str(submission.id),
        "filename": submission.content_link,
    }


# ---------------------------------------------------------------------------
# Access-check helpers
# ---------------------------------------------------------------------------

def _assert_sample_access(submission: Submission, user: User, db) -> None:
    """Sample visible to the requester (on their request) or the submitting provider."""
    if str(submission.provider_id) == str(user.id):
        return
    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    if data_request and str(data_request.requester_id) == str(user.id):
        return
    # 404, not 403 — don't leak the submission's existence to a third party (S1).
    raise HTTPException(status_code=404, detail="Submission not found")


# ---------------------------------------------------------------------------
# Takedown (admin only) — GDPR / copyright infringement
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/takedown")
def takedown(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin takedown: soft-delete the submission and immediately expire any
    outstanding pre-signed URL so the file becomes unreachable.
    The underlying file in storage is NOT deleted (preserve for legal review).
    """
    from app.models import UserRole
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")

    submission = _get_submission_or_404(submission_id, db)

    # Revoke access: expire the URL gate immediately
    submission.access_expiry = datetime.utcnow()
    # Soft-delete so it disappears from all queries
    submission.is_deleted = True

    db.commit()
    return {
        "submission_id": submission_id,
        "status": "taken_down",
        "message": "Submission removed and URL access revoked. File preserved for legal review.",
    }
