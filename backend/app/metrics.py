# app/metrics.py
#
# Beachhead instrumentation (Phase 7). Internal/admin dashboard of the levers the
# business plan underwrites: fill rate, GMV, platform take, cross-mode fulfilment,
# repeat-buyer rate — overall and per vertical (DataRequest.category).

import os
from decimal import Decimal
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    DataRequest, Submission, Purchase, UserAuth as User, UserRole, RequestStatus,
    AuditLog, Dispute,
)
from app.auth import get_current_user

router = APIRouter()


def _admin_only(user: User):
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")


def _D(v) -> Decimal:
    return Decimal(str(v or 0))


def _fill_rate(requests: list[DataRequest]) -> float:
    required = sum((r.amount_required or 0) for r in requests)
    accepted = sum((r.accepted_total or 0) for r in requests)
    return round(accepted / required, 4) if required else 0.0


@router.get("/beachhead")
def beachhead(
    category: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Beachhead metrics, optionally scoped to one vertical (category)."""
    _admin_only(current_user)

    rq = db.query(DataRequest).filter(DataRequest.is_deleted == False)
    if category:
        rq = rq.filter(DataRequest.category == category)
    requests = rq.all()
    req_ids = [str(r.id) for r in requests]

    # Paid submissions tied to these requests → GMV + take + cross-mode counts.
    paid_subs = []
    if req_ids:
        paid_subs = db.query(Submission).filter(
            Submission.request_id.in_(req_ids),
            Submission.status == "paid",
            Submission.is_deleted == False,
        ).all()

    request_gmv = sum((_D(s.amount_due) for s in paid_subs), Decimal("0"))
    request_take = sum((_D(s.commission_amount) for s in paid_subs), Decimal("0"))

    # Cross-mode: requests whose accepted/paid fills span ≥2 distinct sources.
    sources_by_req: dict[str, set] = {}
    if req_ids:
        for s in db.query(Submission).filter(
            Submission.request_id.in_(req_ids),
            Submission.status.in_(["accepted", "partially_accepted", "paid"]),
            Submission.is_deleted == False,
        ).all():
            sources_by_req.setdefault(str(s.request_id), set()).add(s.source or "request")
    cross_mode = sum(1 for srcs in sources_by_req.values() if len(srcs) >= 2)

    # Repeat-buyer rate (buyers with >1 funded/active request).
    funded_states = (RequestStatus.OPEN, RequestStatus.PARTIALLY_FULFILLED, RequestStatus.COMPLETED, RequestStatus.EXPIRED)
    buyer_counts: dict[str, int] = {}
    for r in requests:
        if r.status in funded_states:
            buyer_counts[str(r.requester_id)] = buyer_counts.get(str(r.requester_id), 0) + 1
    buyers = len(buyer_counts)
    repeat = sum(1 for c in buyer_counts.values() if c > 1)
    repeat_rate = round(repeat / buyers, 4) if buyers else 0.0

    status_counts: dict[str, int] = {}
    for r in requests:
        status_counts[str(r.status)] = status_counts.get(str(r.status), 0) + 1

    # Per-category breakdown (only when not already scoped).
    by_category = []
    if not category:
        cats: dict[str, list] = {}
        for r in requests:
            cats.setdefault(r.category or "(uncategorized)", []).append(r)
        for cat, rs in sorted(cats.items()):
            ids = [str(r.id) for r in rs]
            csubs = [s for s in paid_subs if str(s.request_id) in ids]
            by_category.append({
                "category": cat,
                "requests": len(rs),
                "fill_rate": _fill_rate(rs),
                "gmv": str(sum((_D(s.amount_due) for s in csubs), Decimal("0"))),
            })

    # Catalog purchases (no category — direct buys).
    paid_purchases = db.query(Purchase).filter(
        Purchase.status == "paid", Purchase.is_deleted == False
    ).all()
    catalog_gmv = sum((_D(p.amount) for p in paid_purchases), Decimal("0"))
    catalog_take = sum((_D(p.commission_amount) for p in paid_purchases), Decimal("0"))

    return {
        "scope": category or "all",
        "requests": {"total": len(requests), "by_status": status_counts},
        "fill_rate": _fill_rate(requests),
        "gmv": str(request_gmv + catalog_gmv),
        "take": str(request_take + catalog_take),
        "cross_mode_requests": cross_mode,
        "buyers": buyers,
        "repeat_buyer_rate": repeat_rate,
        "by_category": by_category,
        "catalog": {
            "purchases": len(paid_purchases),
            "gmv": str(catalog_gmv),
            "take": str(catalog_take),
        },
    }


# ---------------------------------------------------------------------------
# Concierge tooling (cold-start) — manually source supply + seed the catalog
# ---------------------------------------------------------------------------

@router.get("/concierge/under-filled")
def under_filled(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Open requests still short of their target — where an admin should source supply."""
    _admin_only(current_user)
    rows = db.query(DataRequest).filter(
        DataRequest.is_deleted == False,
        DataRequest.status.in_([RequestStatus.OPEN, RequestStatus.PARTIALLY_FULFILLED]),
    ).all()
    out = []
    for r in rows:
        remaining = (r.amount_required or 0) - (r.accepted_total or 0)
        if remaining <= 0:
            continue
        out.append({
            "id": str(r.id),
            "title": r.title,
            "category": r.category,
            "mode": r.mode,
            "remaining": remaining,
            "fill_rate": round((r.accepted_total or 0) / r.amount_required, 4) if r.amount_required else 0.0,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    out.sort(key=lambda x: x["remaining"], reverse=True)
    return out


@router.post("/concierge/seed-catalog")
def seed_catalog(
    supplier_email: str = Query("concierge-supplier@rowbound.local"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pre-load anchor listings so the catalog is never empty for early buyers."""
    _admin_only(current_user)
    from app.seed_listings import seed
    created = seed(supplier_email)
    return {"seeded": created, "supplier_email": supplier_email}


@router.get("/audit")
def audit_log(
    action: str = Query(None),
    object_id: str = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The append-only audit trail (admin) — money/file events, newest first."""
    _admin_only(current_user)
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if object_id:
        q = q.filter(AuditLog.object_id == object_id)
    rows = q.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).all()
    return [{
        "id": str(r.id),
        "action": r.action,
        "actor_id": str(r.actor_id) if r.actor_id else None,
        "ip": r.ip,
        "object_type": r.object_type,
        "object_id": r.object_id,
        "meta": r.meta,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.get("/anomalies")
def anomalies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Internal anomaly flags (S5/S6) derived from existing data + the audit log:
    submission velocity bursts, account-creation velocity, dispute rate, locked
    accounts (auth-probe signal), shared-IP actor clusters (sybil/collusion), and
    recent payout-account changes. Surfaces what to investigate, not a verdict.
    """
    _admin_only(current_user)
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    vel_threshold = int(os.getenv("ANOMALY_SUBMISSION_VELOCITY", "20"))

    # Submission velocity per provider in the last 24h.
    recent_subs = db.query(Submission).filter(
        Submission.created_at >= day_ago, Submission.is_deleted == False
    ).all()
    per_provider: dict[str, int] = {}
    for s in recent_subs:
        per_provider[str(s.provider_id)] = per_provider.get(str(s.provider_id), 0) + 1
    velocity = [{"provider_id": p, "submissions_24h": n}
                for p, n in per_provider.items() if n >= vel_threshold]

    new_accounts_24h = db.query(User).filter(
        User.created_at >= day_ago, User.is_deleted == False
    ).count()

    # Dispute rate (open disputes vs paid submissions).
    open_disputes = db.query(Dispute).filter(Dispute.status == "open", Dispute.is_deleted == False).count()
    paid = db.query(Submission).filter(Submission.status == "paid", Submission.is_deleted == False).count()
    dispute_rate = round(open_disputes / paid, 4) if paid else 0.0

    # Auth-probe signal: locked or high-failed-attempt accounts.
    locked = db.query(User).filter(
        (User.account_locked == True) | (User.failed_login_attempts >= 5)  # noqa: E712
    ).count()

    # Sybil/collusion: IPs in the audit log used by >1 distinct actor.
    shared_ip: dict[str, set] = {}
    for a in db.query(AuditLog).filter(AuditLog.ip.isnot(None), AuditLog.actor_id.isnot(None)).all():
        shared_ip.setdefault(a.ip, set()).add(a.actor_id)
    shared_ip_clusters = [{"ip": ip, "actors": len(actors)} for ip, actors in shared_ip.items() if len(actors) > 1]

    recent_payout_changes = [{
        "actor_id": a.actor_id, "ip": a.ip,
        "created_at": a.created_at.isoformat() if a.created_at else None, "meta": a.meta,
    } for a in db.query(AuditLog).filter(
        AuditLog.action == "payout_change", AuditLog.created_at >= week_ago
    ).order_by(AuditLog.created_at.desc()).all()]

    return {
        "submission_velocity": velocity,
        "new_accounts_24h": new_accounts_24h,
        "dispute_rate": dispute_rate,
        "open_disputes": open_disputes,
        "locked_accounts": locked,
        "shared_ip_clusters": shared_ip_clusters,
        "recent_payout_changes": recent_payout_changes,
    }


@router.get("/leakage")
def leakage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Off-platform disintermediation signals: requests funded then expired unfilled,
    and requests where the buyer reviewed validated submissions but never accepted
    (samples seen, then possibly completed off-platform). Escrow + per-record
    settlement are the retention mechanic; these flags surface where it's leaking.
    """
    _admin_only(current_user)

    expired_unfilled = db.query(DataRequest).filter(
        DataRequest.is_deleted == False,
        DataRequest.status == RequestStatus.EXPIRED,
        DataRequest.accepted_total < DataRequest.amount_required,
    ).all()

    # Requests with validated (reviewable) submissions but nothing accepted.
    reviewed_ids = {
        str(s.request_id)
        for s in db.query(Submission).filter(
            Submission.status == "validated", Submission.is_deleted == False
        ).all()
    }
    abandoned = db.query(DataRequest).filter(
        DataRequest.is_deleted == False,
        DataRequest.status.in_([RequestStatus.OPEN, RequestStatus.PARTIALLY_FULFILLED]),
        DataRequest.accepted_total == 0,
    ).all()
    abandoned_after_review = [r for r in abandoned if str(r.id) in reviewed_ids]

    def _slim(r):
        return {"id": str(r.id), "title": r.title, "category": r.category,
                "accepted_total": r.accepted_total, "amount_required": r.amount_required}

    return {
        "funded_then_expired": {
            "count": len(expired_unfilled),
            "requests": [_slim(r) for r in expired_unfilled[:50]],
        },
        "reviewed_not_accepted": {
            "count": len(abandoned_after_review),
            "requests": [_slim(r) for r in abandoned_after_review[:50]],
        },
    }
