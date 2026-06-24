# app/submissions.py
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal
import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from app import audit
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from app.db import get_db
from app.models import Submission, DataRequest, UserAuth as User, SubmissionStatus, RequestStatus, UserRole
from app.auth import get_current_user
from app.ingest import validate_dataset
from app.filesafety import assert_safe_text_upload
from app.malware import assert_clean
from app.lifecycle import validate_submission, accept_submission, transition_submission, expire_request, mark_paid
from app.storage import get_storage
from app.payments import get_payment_provider, ledger_balance
from app.reviews import _increment_transactions
from app.notifications import notify

ACCEPTANCE_WINDOW_HOURS = int(os.getenv("ACCEPTANCE_WINDOW_HOURS", "72"))
# Releases to a just-changed payout destination are held for this long (S3).
PAYOUT_COOLDOWN_HOURS = int(os.getenv("PAYOUT_COOLDOWN_HOURS", "24"))

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
        "commission_amount": s.commission_amount,
        "content_link": s.content_link,
        "dataset_hash": s.dataset_hash,
        "quality_score": s.quality_score,
        "quarantined": s.quarantined,
        "pii_report": s.pii_report,
        "source": s.source,
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

    # Decide it's really a text dataset by content, not the (forgeable) extension —
    # a renamed .exe/.zip/image is refused before it's stored or served.
    assert_safe_text_upload(file_bytes, file.filename or "upload")
    # Active-content scan (S2) — an infected file is never stored or made downloadable.
    assert_clean(file_bytes)

    result = validate_dataset(
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        spec=data_request.spec,
    )

    # Envelope-encrypt at rest (E5) when the dataset carries personal data, so a
    # leaked object yields ciphertext. read()/delivery transparently decrypt for
    # the authorized roles (the deliberate carve-out that keeps the dedup/validate
    # moat working). Standard SSE-KMS covers the non-sensitive rest.
    sensitive = (result.pii_report or {}).get("risk") in ("high", "medium")
    storage_key = f"{request_id}/{current_user.id}/{file.filename}"
    storage_location = get_storage().save(storage_key, file_bytes, encrypt=sensitive)

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
        quality_score=result.quality_score,
        pii_report=result.pii_report or None,
        # Auto-quarantine high-risk PII (payment cards / national IDs / pervasive
        # contact data) so it can't be delivered before a human reviews it (S4).
        quarantined=(result.pii_report or {}).get("risk") == "high",
        source="request",
    )
    db.add(submission)
    db.flush()

    validate_submission(
        submission=submission,
        validated_amount=result.validated_amount,
        validation_report={**result.validation_report, "sample": result.sample},
        db=db,
    )

    # P1 SHADOW mode: run the Rust ingest service on the same file and log any
    # parity divergence. Python stays authoritative; this never affects the
    # response and never raises (no-op unless INGEST_SHADOW_ENABLED).
    try:
        from app.ingest_client import shadow_compare
        shadow_compare(
            result,
            submission_id=str(submission.id),
            s3_key=storage_location,
            filename=file.filename or "upload",
            spec=data_request.spec,
            content_hash=result.dataset_hash,
        )
    except Exception:
        pass

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

    # Payout cool-down (S3): if the provider changed their payout destination
    # recently, do NOT release yet — defer (stays ACCEPTED) until the window
    # passes, so a hijacked account can't immediately drain escrow. The sweep
    # retries automatically after the cool-down.
    provider = db.query(User).filter(User.id == str(submission.provider_id)).first()
    if provider and provider.payout_account_changed_at:
        if datetime.utcnow() < provider.payout_account_changed_at + timedelta(hours=PAYOUT_COOLDOWN_HOURS):
            return submission

    # Platform take-rate: record commission before releasing so the supplier
    # transfer is net (escrow ledger still records the full amount — see commission.py).
    from app.commission import compute_commission
    submission.commission_amount = compute_commission(submission.amount_due, submission.source)

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


def _assert_download_allowed(submission: Submission, current_user: User, db: Session) -> DataRequest:
    """Shared gate for both delivery paths (presigned + decrypt-stream). Enforces
    buyer ownership, PAID/accepted status, quarantine, takedown expiry, and the
    per-submission download_limit (E3). Returns the parent DataRequest."""
    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    _require_request_owner(data_request, current_user)

    # Auto-release check: if window has elapsed and no dispute, release now (lazy).
    # Shares one helper with /claim and the sweep so the rules can't drift.
    _auto_release_if_due(submission, db)

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

    # Quarantine gate (S4): a flagged / high-PII dataset is not deliverable until reviewed.
    if submission.quarantined:
        raise HTTPException(
            status_code=403,
            detail="This dataset is under review and is temporarily unavailable for download.",
        )

    # Honour takedown: if access_expiry is in the past (set by takedown), deny
    if submission.access_expiry and submission.access_expiry < datetime.utcnow():
        raise HTTPException(status_code=410, detail="This dataset has been taken down and is no longer available")

    # E3: honour download_limit. 0 = unlimited (the default). Once the limit is
    # reached the access grant is spent — no more URLs / streams are issued.
    if submission.download_limit and submission.download_limit > 0 and \
            (submission.download_count or 0) >= submission.download_limit:
        raise HTTPException(
            status_code=403,
            detail=f"Download limit reached ({submission.download_limit}).",
        )

    return data_request


def _record_download(submission: Submission, current_user: User, request: Request, db: Session) -> None:
    """Audit + count the grant. Best-effort access_expiry refresh keeps the
    takedown gate's clock current."""
    audit.record(db, "download", actor_id=current_user.id, ip=audit.client_ip(request),
                 object_type="submission", object_id=submission.id)
    try:
        submission.download_count = (submission.download_count or 0) + 1
        submission.access_expiry = datetime.utcnow() + timedelta(
            seconds=int(os.getenv("PRESIGNED_URL_TTL_SECONDS", "300"))
        )
        db.commit()
    except Exception:
        db.rollback()


@router.get("/{submission_id}/download")
def download(
    submission_id: str,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Hand the paying buyer the full dataset. ONLY for PAID / accepted submissions.

    For objects stored encrypted at rest (E5) the presigned URL would be useless
    ciphertext, so the response points at the decrypt-and-stream sub-endpoint
    instead; otherwise a short-lived (E3) presigned URL is returned.
    """
    submission = _get_submission_or_404(submission_id, db)
    _assert_download_allowed(submission, current_user, db)

    manifest = _compliance_manifest(submission, db)

    # Envelope-encrypted object: the bytes in storage are ciphertext, so we can't
    # presign them. Direct the client to the authenticated stream endpoint, which
    # decrypts in memory (the carve-out) and serves plaintext. The count is taken
    # there, when the bytes actually flow.
    if get_storage().is_encrypted_at_rest(submission.storage_location):
        return {
            "url": None,
            "streamed": True,
            "download_path": f"/submissions/{submission.id}/download/stream",
            "submission_id": str(submission.id),
            "filename": submission.content_link,
            "manifest": manifest,
        }

    ttl = int(os.getenv("PRESIGNED_URL_TTL_SECONDS", "300"))
    url = get_storage().presigned_url(submission.storage_location, filename=submission.content_link)
    _record_download(submission, current_user, request, db)

    return {
        "url": url,
        "streamed": False,
        "expires_in_seconds": ttl,
        "submission_id": str(submission.id),
        "filename": submission.content_link,
        # Compliance manifest travels with every delivery (Phase 8).
        "manifest": manifest,
    }


@router.get("/{submission_id}/download/stream")
def download_stream(
    submission_id: str,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Decrypt-and-stream delivery for envelope-encrypted datasets (E5). Same gate
    as /download; the authorized buyer's request triggers the in-memory KMS unwrap
    + decrypt, and the plaintext is streamed straight to the client — never
    re-persisted as a plaintext object."""
    submission = _get_submission_or_404(submission_id, db)
    _assert_download_allowed(submission, current_user, db)

    plaintext = get_storage().read(submission.storage_location)  # transparent decrypt
    _record_download(submission, current_user, request, db)

    fn = (submission.content_link or "dataset").replace('"', "")
    return StreamingResponse(
        io.BytesIO(plaintext),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )


# ---------------------------------------------------------------------------
# Compliance manifest (Phase 8): source + license + provenance + consent basis
# travel with every delivered dataset, across all three modes.
# ---------------------------------------------------------------------------

def _compliance_manifest(submission: Submission, db: Session) -> dict:
    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    lic = data_request.license if (data_request and data_request.license) else None
    consent = (submission.validation_report or {}).get("collection", {}).get("consent")
    return {
        "submission_id": str(submission.id),
        "source": submission.source,                 # request | collect | catalog
        "license": ({"name": lic.name, "terms": lic.terms} if lic else None),
        "provenance": submission.owner_signature,
        "consent": consent,                          # present for collected (personal/location) data
        "dataset_hash": submission.dataset_hash,
        "record_count": submission.accepted_amount or submission.validated_amount,
        "category": data_request.category if data_request else None,
    }


@router.get("/{submission_id}/manifest")
def get_manifest(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The compliance manifest for a fill — visible to the request's buyer or the
    submitting provider."""
    submission = _get_submission_or_404(submission_id, db)
    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()
    if str(submission.provider_id) != str(current_user.id) and \
       (not data_request or str(data_request.requester_id) != str(current_user.id)):
        raise HTTPException(status_code=404, detail="Submission not found")
    return _compliance_manifest(submission, db)


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
    import uuid as _uuid
    from app.models import UserRole
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")

    submission = _get_submission_or_404(submission_id, db)

    # Revoke access on every axis:
    submission.access_expiry = datetime.utcnow()      # expire the URL gate now
    submission.quarantined = True                     # block the delivery gate
    submission.access_token_id = _uuid.uuid4().hex    # rotate → any outstanding token is dead
    submission.is_deleted = True                      # disappears from all queries

    audit.record(db, "takedown", actor_id=current_user.id,
                 object_type="submission", object_id=submission.id)
    db.commit()
    return {
        "submission_id": submission_id,
        "status": "taken_down",
        "message": "Submission removed and URL access revoked. File preserved for legal review.",
    }


# ---------------------------------------------------------------------------
# Reporter flow: anyone can flag a submission → quarantine pending admin review
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/report")
def report_submission(
    submission_id: str,
    reason: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Flag a submission as illegal / non-consented / infringing. Quarantines the
    dataset (blocks delivery) pending admin review. A provider cannot report their
    own submission. One report per reporter per submission.
    """
    from app.models import SubmissionFlag
    submission = _get_submission_or_404(submission_id, db)
    if str(submission.provider_id) == str(current_user.id):
        raise HTTPException(status_code=403, detail="You cannot report your own submission")

    existing = db.query(SubmissionFlag).filter(
        SubmissionFlag.submission_id == str(submission.id),
        SubmissionFlag.reporter_id == str(current_user.id),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="You have already reported this submission")

    db.add(SubmissionFlag(
        submission_id=submission.id,
        reporter_id=current_user.id,
        reason=reason,
    ))
    submission.quarantined = True
    db.commit()

    notify(
        None,
        "Submission reported",
        f"Submission {submission_id} was reported and quarantined pending review. Reason: {reason}",
    )
    return {"submission_id": submission_id, "status": "quarantined"}


# ---------------------------------------------------------------------------
# Admin: clear a quarantine after review (false positive)
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/unquarantine")
def unquarantine(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin clears a quarantine after reviewing (e.g. PII false positive)."""
    from app.models import UserRole
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")
    submission = _get_submission_or_404(submission_id, db)
    submission.quarantined = False
    db.commit()
    return {"submission_id": submission_id, "status": "cleared"}
