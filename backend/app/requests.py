# app/requests.py
import os
import csv
import io
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    DataRequest, UserAuth as User, UserRole, PricingMode, RequestStatus, Ledger,
    Listing, ListingStatus, Submission, AcceptedKey,
)
from app.schemas import DataRequestCreateSchema, DataRequestResponseSchema
from app.auth import get_current_user
from app.lifecycle import open_request, expire_request, validate_submission, accept_submission, mark_paid
from app.payments import get_payment_provider, ledger_balance
from app.storage import get_storage
from app.ingest import _parse_csv, _parse_jsonl

router = APIRouter()

PAYOUT_COOLDOWN_HOURS = int(os.getenv("PAYOUT_COOLDOWN_HOURS", "24"))


@router.post("/", response_model=DataRequestResponseSchema)
def create_request(
    data: DataRequestCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.REQUESTER:
        raise HTTPException(status_code=403, detail="Only requesters can post data requests")

    deadline = None
    if data.deadline:
        try:
            deadline = datetime.fromisoformat(data.deadline)
        except ValueError:
            raise HTTPException(status_code=422, detail="deadline must be a valid ISO datetime string")

    request = DataRequest(
        title=data.title,
        description=data.description,
        unit=data.unit,
        amount_required=data.amount_required,
        pricing_mode=PricingMode(data.pricing_mode),
        price_per_unit=data.price_per_unit,
        budget=data.budget,
        required_format=data.required_format,
        spec=data.spec.model_dump() if data.spec else None,
        category=data.category,
        mode=data.mode,
        collection_spec=data.collection_spec.model_dump() if data.collection_spec else None,
        deadline=deadline,
        license_id=data.license_id,
        requester_id=current_user.id,
        accepted_total=0,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@router.post("/{request_id}/fund", response_model=DataRequestResponseSchema)
def fund_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Requester funds a DRAFT request: hold budget in escrow → OPEN.
    This is the gate that lets providers submit.
    """
    request = db.query(DataRequest).filter(
        DataRequest.id == request_id,
        DataRequest.is_deleted == False,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if str(request.requester_id) != str(current_user.id):
        # 404, not 403 — don't confirm this request exists to a non-owner (S1).
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status != RequestStatus.DRAFT:
        raise HTTPException(
            status_code=409,
            detail=f"Request is already {request.status} — only DRAFT requests can be funded",
        )
    if not request.budget or request.budget <= 0:
        raise HTTPException(status_code=422, detail="Request must have a positive budget before funding")

    payment = get_payment_provider()
    payment.hold_escrow(request, db)
    request = open_request(request, db)
    db.commit()
    return request


@router.get("/{request_id}/matching-listings")
def matching_listings(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Catalog listings the buyer could fill this request from — same declared
    unique key, in stock, not their own. Powers the cross-mode funnel."""
    from app.listings import _serialize as _serialize_listing
    request = db.query(DataRequest).filter(DataRequest.id == request_id, DataRequest.is_deleted == False).first()
    if not request or str(request.requester_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Request not found")

    unique_key = (request.spec or {}).get("unique_key") or []
    if not unique_key:
        return []
    want = set(unique_key)

    listings = db.query(Listing).filter(
        Listing.is_deleted == False,
        Listing.status == ListingStatus.ACTIVE,
        Listing.quarantined == False,
        Listing.available_quantity > 0,
        Listing.supplier_id != current_user.id,
    ).all()
    return [
        _serialize_listing(l)
        for l in listings
        if set((l.spec or {}).get("unique_key") or []) == want
    ]


class FulfilFromListing(BaseModel):
    listing_id: str
    quantity: Optional[int] = None     # max records to pull; default = as much as fits


@router.post("/{request_id}/fulfil-from-listing")
def fulfil_from_listing(
    request_id: str,
    body: FulfilFromListing,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cross-mode fulfilment (the headline): fill part of an open request from a
    catalog listing. The listing's records are entity-resolved on the REQUEST's
    declared unique key, deduped against everything already accepted for the
    request (any source), capped at remaining demand, and settled per record
    through the request's single escrow. No record is paid for twice.
    """
    # --- locks: request first, then listing (consistent order) ---
    request = (
        db.execute(select(DataRequest).where(DataRequest.id == request_id).with_for_update())
        .scalars().first()
    )
    if not request or request.is_deleted:
        raise HTTPException(status_code=404, detail="Request not found")
    if str(request.requester_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Request not found")   # don't leak (S1)
    if request.status not in (RequestStatus.OPEN, RequestStatus.PARTIALLY_FULFILLED):
        raise HTTPException(status_code=409, detail=f"Request is not open for fulfilment (status: {request.status})")

    unique_key = (request.spec or {}).get("unique_key") or []
    if not unique_key:
        raise HTTPException(status_code=409,
                            detail="Cross-source fulfilment requires the request to declare a unique_key")

    listing = (
        db.execute(select(Listing).where(Listing.id == body.listing_id).with_for_update())
        .scalars().first()
    )
    if not listing or listing.is_deleted:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.quarantined or listing.status != ListingStatus.ACTIVE or (listing.available_quantity or 0) <= 0:
        raise HTTPException(status_code=409, detail="Listing is not available")

    remaining = (request.amount_required or 0) - (request.accepted_total or 0)
    if remaining <= 0:
        raise HTTPException(status_code=409, detail="Request is already filled")

    # Payout safety in real-money mode (mirrors purchase): supplier must be payable.
    payment = get_payment_provider()
    supplier = db.query(User).filter(User.id == str(listing.supplier_id)).first()
    if payment.requires_connected_account:
        if not supplier or not supplier.stripe_account_id:
            raise HTTPException(status_code=409, detail="This supplier cannot receive payouts yet.")
        if supplier.payout_account_changed_at and \
           datetime.utcnow() < supplier.payout_account_changed_at + timedelta(hours=PAYOUT_COOLDOWN_HOURS):
            raise HTTPException(status_code=409, detail="Supplier payout account changed recently — temporarily unavailable.")

    # Entity-resolve listing rows on the REQUEST's key; dedup vs accepted + within-batch.
    raw = get_storage().read(listing.storage_location)
    rows = _parse_jsonl(raw) if (listing.required_format == "jsonl") else _parse_csv(raw)
    already = {r.key_hash for r in db.query(AcceptedKey).filter(AcceptedKey.request_id == str(request.id)).all()}

    cap = min(remaining, listing.available_quantity)
    if body.quantity is not None:
        cap = min(cap, max(0, body.quantity))

    creditable_rows: list[dict] = []
    creditable_hashes: list[str] = []
    seen: set = set()
    for row in rows:
        if len(creditable_rows) >= cap:
            break
        kv = tuple(str(row.get(k, "")) for k in unique_key)
        kh = hashlib.sha256(repr(kv).encode()).hexdigest()
        if kh in already or kh in seen:
            continue
        seen.add(kh)
        creditable_rows.append(row)
        creditable_hashes.append(kh)

    accepted = len(creditable_rows)
    if accepted == 0:
        raise HTTPException(status_code=409, detail="Listing contributes no new records to this request")

    # Slice the credited rows into the buyer's deliverable.
    fieldnames = list(creditable_rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in creditable_rows:
        w.writerow(r)
    file_bytes = buf.getvalue().encode()

    submission = Submission(
        request_id=request.id,
        provider_id=listing.supplier_id,
        content_link=f"catalog-{listing.id}.csv",
        offered_amount=accepted,
        accepted_amount=0,
        file_size_bytes=len(file_bytes),
        mime_type="text/csv",
        storage_location=get_storage().save(f"catalog-fills/{request.id}/{listing.id}.csv", file_bytes),
        dataset_hash=hashlib.sha256(file_bytes).hexdigest(),
        key_hashes=creditable_hashes,
        quality_score=listing.quality_score or 1.0,
        owner_signature=f"catalog fill from listing {listing.id}",
        source="catalog",
    )
    db.add(submission)
    db.flush()
    validate_submission(
        submission, accepted,
        {"conforming_rows": accepted, "sample": (listing.sample or [])[:5],
         "unique_key": unique_key, "source": "catalog", "listing_id": str(listing.id)},
        db,
    )

    # Reuse the engine: caps at remaining, writes AcceptedKeys, bumps accepted_total,
    # advances request status — all in one locked transaction.
    submission, request = accept_submission(submission, request, db)

    # Catalog data already exists → settle immediately (no acceptance window).
    if submission.status in ("accepted", "partially_accepted"):
        from app.commission import compute_commission
        submission.commission_amount = compute_commission(submission.amount_due, submission.source)
        payment.release_to_provider(submission, db)
        submission = mark_paid(submission, db)

    listing.available_quantity = max(0, (listing.available_quantity or 0) - submission.accepted_amount)
    if listing.available_quantity == 0:
        listing.status = ListingStatus.SOLD_OUT
    db.commit()

    return {
        "submission_id": str(submission.id),
        "source": "catalog",
        "accepted_amount": submission.accepted_amount,
        "amount_due": str(submission.amount_due),
        "request_status": request.status,
        "request_accepted_total": request.accepted_total,
        "request_remaining": (request.amount_required or 0) - (request.accepted_total or 0),
    }


@router.post("/{request_id}/close", response_model=DataRequestResponseSchema)
def close_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Buyer closes a request early (before deadline). Transitions to EXPIRED and
    refunds any unspent escrow.
    """
    request = db.query(DataRequest).filter(
        DataRequest.id == request_id,
        DataRequest.is_deleted == False,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if str(request.requester_id) != str(current_user.id):
        # 404, not 403 — don't confirm this request exists to a non-owner (S1).
        raise HTTPException(status_code=404, detail="Request not found")

    request = expire_request(request, db)
    _refund_unspent(request, db)
    db.commit()
    return request


@router.get("/{request_id}/ledger")
def get_ledger(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Buyer sees the escrow ledger for their request."""
    request = db.query(DataRequest).filter(DataRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if str(request.requester_id) != str(current_user.id):
        # 404, not 403 — don't confirm this request exists to a non-owner (S1).
        raise HTTPException(status_code=404, detail="Request not found")

    entries = (
        db.query(Ledger)
        .filter(Ledger.request_id == request_id)
        .order_by(Ledger.created_at)
        .all()
    )
    return {
        "balance": ledger_balance(db, request_id),
        "entries": [
            {
                "id": str(e.id),
                "type": e.entry_type,
                "amount": e.amount,
                "external_ref": e.external_ref,
                "submission_id": str(e.submission_id) if e.submission_id else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


@router.get("/", response_model=List[DataRequestResponseSchema])
def list_requests(db: Session = Depends(get_db)):
    return db.query(DataRequest).filter(DataRequest.is_deleted == False).all()


@router.get("/{request_id}", response_model=DataRequestResponseSchema)
def get_request(request_id: str, db: Session = Depends(get_db)):
    request = db.query(DataRequest).filter(
        DataRequest.id == request_id,
        DataRequest.is_deleted == False,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return request


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _refund_unspent(request: DataRequest, db: Session) -> None:
    """Refund unspent escrow back to the buyer. Called on EXPIRED / close."""
    balance = ledger_balance(db, request.id)
    unspent = balance["remaining"]
    if unspent > 0:
        get_payment_provider().refund_to_buyer(request, unspent, db)
