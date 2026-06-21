# app/metrics.py
#
# Beachhead instrumentation (Phase 7). Internal/admin dashboard of the levers the
# business plan underwrites: fill rate, GMV, platform take, cross-mode fulfilment,
# repeat-buyer rate — overall and per vertical (DataRequest.category).

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    DataRequest, Submission, Purchase, UserAuth as User, UserRole, RequestStatus,
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
