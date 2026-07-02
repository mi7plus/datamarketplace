# app/admin.py
#
# Admin panel API (admin panel design, Tiers 1–2). Every route is gated by the RBAC
# capability model in admin_authz; every state-changing (Tier-2) action writes an
# append-only AuditLog entry with actor, target, and reason. The panel is the app's
# highest-privilege surface — treat each endpoint as a target.
#
# Tier 1 (observe): dashboard/users/activity/audit — capability CAP_VIEW, all admins.
# Tier 2 (support): unlock, suspend, resend-verification, reset-MFA, quarantine,
#   refund, resolve-dispute — each its own capability, sensitive ones step-up.

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit import record, client_ip
from app.admin_authz import (
    current_admin, require_capability, capabilities_for,
    CAP_USER_UNLOCK, CAP_USER_SUSPEND, CAP_USER_VERIFY_RESEND, CAP_USER_MFA_RESET,
    CAP_DATASET_QUARANTINE, CAP_TXN_REFUND, CAP_ADMIN_MANAGE,
)
from app.db import get_db
from app.models import (
    AdminRole, UserAuth as User, UserProfile, UserAnalytics, UserIdentity,
    DataRequest, Submission, Purchase, Dispute,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _user_summary(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "role": u.role.value if u.role else None,
        "admin_role": u.admin_role.value if u.admin_role else None,
        "is_verified": bool(u.is_verified),
        "mfa_enabled": bool(u.mfa_enabled),
        "account_locked": bool(u.account_locked),
        "suspended": bool(u.suspended),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


# ---------------------------------------------------------------------------
# Me — the current admin's identity + capabilities (drives the frontend UI)
# ---------------------------------------------------------------------------

@router.get("/me")
def admin_me(admin: User = Depends(current_admin)):
    return {
        "id": str(admin.id),
        "email": admin.email,
        "admin_role": admin.admin_role.value if admin.admin_role else None,
        "mfa_enabled": bool(admin.mfa_enabled),
        "capabilities": capabilities_for(admin.admin_role),
    }


# ---------------------------------------------------------------------------
# Tier 1 — Users (list/search + detail + activity)
# ---------------------------------------------------------------------------

@router.get("/users")
def list_users(
    q: str = Query(None, description="email substring search"),
    role: str = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
):
    query = db.query(User).filter(User.is_deleted == False)  # noqa: E712
    if q:
        query = query.filter(func.lower(User.email).like(f"%{q.lower()}%"))
    if role:
        query = query.filter(User.role == role)
    total = query.count()
    rows = query.order_by(User.created_at.desc()).offset(max(offset, 0)).limit(min(limit, 200)).all()
    return {"total": total, "users": [_user_summary(u) for u in rows]}


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
):
    u = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()  # noqa: E712
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    analytics = db.query(UserAnalytics).filter(UserAnalytics.user_id == user_id).first()
    identities = db.query(UserIdentity).filter(UserIdentity.user_id == user_id).all()
    out = _user_summary(u)
    out.update({
        "locked_until": u.locked_until.isoformat() if u.locked_until else None,
        "failed_login_attempts": u.failed_login_attempts or 0,
        "profile": {
            "user_type": profile.user_type if profile else None,
            "first_name": profile.first_name if profile else None,
            "last_name": profile.last_name if profile else None,
            "company_name": profile.company_name if profile else None,
            "phone": profile.phone if profile else None,
        } if profile else None,
        "analytics": {
            "reputation_score": analytics.reputation_score if analytics else None,
            "total_transactions": analytics.total_transactions if analytics else None,
            "successful_transactions": analytics.successful_transactions if analytics else None,
        } if analytics else None,
        "identities": [
            {"provider": i.provider, "email_at_link": i.email_at_link,
             "linked_at": i.created_at.isoformat() if i.created_at else None}
            for i in identities
        ],
    })
    return out


@router.get("/users/{user_id}/activity")
def user_activity(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(current_admin),
):
    """A customer's full marketplace footprint: requests, submissions, purchases,
    disputes opened. Read-only cross-object view for support triage."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    requests = db.query(DataRequest).filter(DataRequest.requester_id == user_id).all()
    submissions = db.query(Submission).filter(Submission.provider_id == user_id).all()
    purchases = db.query(Purchase).filter(Purchase.buyer_id == user_id).all()
    disputes = db.query(Dispute).filter(Dispute.opened_by_id == user_id).all()

    return {
        "requests": [
            {"id": str(r.id), "title": r.title, "status": r.status.value if r.status else None,
             "budget": str(r.budget) if r.budget is not None else None,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in requests
        ],
        "submissions": [
            {"id": str(s.id), "request_id": str(s.request_id),
             "status": s.status.value if s.status else None,
             "accepted_amount": s.accepted_amount, "quarantined": bool(s.quarantined),
             "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in submissions
        ],
        "purchases": [
            {"id": str(p.id), "listing_id": str(p.listing_id), "status": p.status,
             "amount": str(p.amount) if p.amount is not None else None,
             "created_at": p.created_at.isoformat() if p.created_at else None}
            for p in purchases
        ],
        "disputes": [
            {"id": str(d.id), "submission_id": str(d.submission_id), "status": d.status,
             "reason": d.reason, "created_at": d.created_at.isoformat() if d.created_at else None}
            for d in disputes
        ],
    }


# ---------------------------------------------------------------------------
# Tier 2 — Support actions. Each: capability-gated + audited (+ step-up if sensitive)
# ---------------------------------------------------------------------------

class ReasonBody(BaseModel):
    reason: str | None = None


def _audit_admin(db, request, admin, action, *, object_type, object_id, reason, extra=None):
    meta = {"reason": reason, "admin_role": admin.admin_role.value if admin.admin_role else None}
    if extra:
        meta.update(extra)
    record(db, action, actor_id=admin.id, ip=client_ip(request),
           object_type=object_type, object_id=object_id, meta=meta)


def _load_user(db, user_id) -> User:
    u = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()  # noqa: E712
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: str, body: ReasonBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USER_UNLOCK)),
):
    """Clear a lockout: reset failed-login counter + lock window."""
    u = _load_user(db, user_id)
    u.account_locked = False
    u.failed_login_attempts = 0
    u.locked_until = None
    _audit_admin(db, request, admin, "admin.user_unlock",
                 object_type="user", object_id=user_id, reason=body.reason)
    db.commit()
    return _user_summary(u)


@router.post("/users/{user_id}/suspend")
def suspend_user(
    user_id: str, body: ReasonBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USER_SUSPEND)),
):
    """Suspend an account (blocks login). Can't suspend an admin — protect the panel."""
    u = _load_user(db, user_id)
    if u.admin_role is not None:
        raise HTTPException(status_code=409, detail="Cannot suspend an admin account")
    u.suspended = True
    u.refresh_token_hash = None   # kill active sessions immediately
    _audit_admin(db, request, admin, "admin.user_suspend",
                 object_type="user", object_id=user_id, reason=body.reason)
    db.commit()
    return _user_summary(u)


@router.post("/users/{user_id}/reactivate")
def reactivate_user(
    user_id: str, body: ReasonBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USER_SUSPEND)),
):
    u = _load_user(db, user_id)
    u.suspended = False
    _audit_admin(db, request, admin, "admin.user_reactivate",
                 object_type="user", object_id=user_id, reason=body.reason)
    db.commit()
    return _user_summary(u)


@router.post("/users/{user_id}/resend-verification")
def resend_verification(
    user_id: str, body: ReasonBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USER_VERIFY_RESEND)),
):
    u = _load_user(db, user_id)
    if u.is_verified:
        raise HTTPException(status_code=409, detail="User is already verified")
    from app.auth import _send_verification_email
    _send_verification_email(u)
    _audit_admin(db, request, admin, "admin.user_resend_verification",
                 object_type="user", object_id=user_id, reason=body.reason)
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/reset-mfa")
def reset_mfa(
    user_id: str, body: ReasonBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USER_MFA_RESET)),   # step-up enforced
):
    """Reset a user's MFA (account-recovery). A takeover vector, so it's step-up-gated
    and audited. Clears the secret so they must re-enroll."""
    u = _load_user(db, user_id)
    u.mfa_secret = None
    u.mfa_enabled = False
    _audit_admin(db, request, admin, "admin.user_reset_mfa",
                 object_type="user", object_id=user_id, reason=body.reason)
    db.commit()
    return _user_summary(u)


@router.post("/submissions/{submission_id}/quarantine")
def quarantine_submission(
    submission_id: str, body: ReasonBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_DATASET_QUARANTINE)),
):
    """Flag a dataset to block delivery pending review."""
    s = db.query(Submission).filter(Submission.id == submission_id, Submission.is_deleted == False).first()  # noqa: E712
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")
    s.quarantined = True
    _audit_admin(db, request, admin, "admin.dataset_quarantine",
                 object_type="submission", object_id=submission_id, reason=body.reason)
    db.commit()
    return {"id": submission_id, "quarantined": True}


@router.post("/submissions/{submission_id}/unquarantine")
def unquarantine_submission(
    submission_id: str, body: ReasonBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_DATASET_QUARANTINE)),
):
    s = db.query(Submission).filter(Submission.id == submission_id, Submission.is_deleted == False).first()  # noqa: E712
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")
    s.quarantined = False
    _audit_admin(db, request, admin, "admin.dataset_unquarantine",
                 object_type="submission", object_id=submission_id, reason=body.reason)
    db.commit()
    return {"id": submission_id, "quarantined": False}


class RefundBody(BaseModel):
    reason: str | None = None
    amount: float | None = None   # optional partial; defaults to the submission's amount_due


@router.post("/submissions/{submission_id}/refund")
def refund_submission(
    submission_id: str, body: RefundBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_TXN_REFUND)),   # step-up enforced
):
    """Refund a settled/held submission's escrow to the buyer, bounded by the ledger
    balance for that request. Money action — step-up + audit required."""
    from app.payments import get_payment_provider, ledger_balance

    s = db.query(Submission).filter(Submission.id == submission_id, Submission.is_deleted == False).first()  # noqa: E712
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")
    req = db.query(DataRequest).filter(DataRequest.id == str(s.request_id)).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    amount = body.amount if body.amount is not None else float(s.amount_due or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Nothing to refund for this submission")
    remaining = float(ledger_balance(db, request_id=str(req.id))["remaining"])
    if amount > remaining:
        raise HTTPException(status_code=409, detail=f"Refund {amount} exceeds held balance {remaining}")

    get_payment_provider().refund_to_buyer(req, amount, db)
    _audit_admin(db, request, admin, "admin.txn_refund",
                 object_type="submission", object_id=submission_id, reason=body.reason,
                 extra={"amount": amount, "request_id": str(req.id)})
    db.commit()
    return {"submission_id": submission_id, "refunded": amount, "request_id": str(req.id)}


# ---------------------------------------------------------------------------
# Admin management (SUPER_ADMIN only) — grant/revoke admin roles. Step-up + audited.
# ---------------------------------------------------------------------------

class GrantAdminBody(BaseModel):
    admin_role: str | None = None   # one of AdminRole values; null = revoke admin access
    reason: str | None = None


@router.post("/users/{user_id}/admin-role")
def set_admin_role(
    user_id: str, body: GrantAdminBody, request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_ADMIN_MANAGE)),   # SUPER_ADMIN, step-up
):
    """Grant or revoke an admin role. Only SUPER_ADMIN. A super-admin can't demote
    themselves (avoid locking the org out of the last super-admin by accident)."""
    u = _load_user(db, user_id)

    new_role = None
    if body.admin_role:
        try:
            new_role = AdminRole(body.admin_role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid admin_role '{body.admin_role}'")

    if str(u.id) == str(admin.id) and new_role != AdminRole.SUPER_ADMIN:
        raise HTTPException(status_code=409, detail="You cannot revoke your own super-admin access")

    before = u.admin_role.value if u.admin_role else None
    u.admin_role = new_role
    if new_role is None:
        u.refresh_token_hash = None   # revoking admin takes effect immediately
    _audit_admin(db, request, admin, "admin.role_change",
                 object_type="user", object_id=user_id, reason=body.reason,
                 extra={"before": before, "after": new_role.value if new_role else None})
    db.commit()
    return _user_summary(u)
