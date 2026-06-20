# app/listings.py
#
# Mode 2 — Buy existing (catalog). Suppliers pre-list datasets priced per record;
# buyers purchase any portion (see purchases in this module's /purchase endpoint).
# Reuses the same ingest validation, file-safety, PII/quality, and dataset-hash
# machinery as Request submissions.

import json
from decimal import Decimal
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Listing, ListingStatus, License, Purchase, UserAuth as User, UserRole
from app.auth import get_current_user
from app.ingest import validate_dataset
from app.filesafety import assert_safe_text_upload
from app.storage import get_storage
from app.payments import append_ledger, purchase_balance

router = APIRouter()
purchases_router = APIRouter()

MAX_FILE_BYTES = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {"csv", "jsonl"}


def _serialize(listing: Listing, *, full: bool = False) -> dict:
    out = {
        "id": str(listing.id),
        "supplier_id": str(listing.supplier_id),
        "title": listing.title,
        "description": listing.description,
        "unit": listing.unit,
        "price_per_unit": float(listing.price_per_unit) if listing.price_per_unit is not None else None,
        "available_quantity": listing.available_quantity,
        "validated_amount": listing.validated_amount,
        "required_format": listing.required_format,
        "license_id": str(listing.license_id) if listing.license_id else None,
        "license_name": listing.license.name if listing.license else None,
        "provenance": listing.provenance,
        "quality_score": listing.quality_score,
        "status": listing.status,
        "quarantined": listing.quarantined,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
    }
    if full:
        out["spec"] = listing.spec
        out["pii_report"] = listing.pii_report
    return out


@router.post("/")
async def create_listing(
    title: str = Form(...),
    price_per_unit: float = Form(...),
    unit: str = Form("row"),
    description: str = Form(None),
    provenance: str = Form(None),
    license_id: str = Form(None),
    spec: str = Form(None),                 # JSON string
    warranted: bool = Form(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Supplier lists a dataset for sale, priced per record."""
    if current_user.role != UserRole.PROVIDER:
        raise HTTPException(status_code=403, detail="Only providers can list datasets")
    if not warranted:
        raise HTTPException(status_code=422, detail="Provider warranties must be affirmed before listing")
    if price_per_unit <= 0:
        raise HTTPException(status_code=422, detail="price_per_unit must be positive")

    spec_dict = None
    if spec:
        try:
            spec_dict = json.loads(spec)
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="spec must be valid JSON")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Only CSV and JSONL files are accepted, got .{ext}")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 100 MB limit")
    assert_safe_text_upload(file_bytes, file.filename or "upload")

    result = validate_dataset(file_bytes=file_bytes, filename=file.filename or "upload", spec=spec_dict)
    if result.validated_amount <= 0:
        raise HTTPException(status_code=422, detail="No valid records found in the uploaded file")

    if license_id:
        if not db.query(License).filter(License.id == license_id).first():
            raise HTTPException(status_code=422, detail="Unknown license_id")

    storage_key = f"listings/{current_user.id}/{file.filename}"
    storage_location = get_storage().save(storage_key, file_bytes)

    warranty_sig = (
        f"warranted by {current_user.email} at {datetime.utcnow().isoformat()}Z "
        f"— rights confirmed, no unconsented personal data"
    )

    listing = Listing(
        supplier_id=current_user.id,
        title=title,
        description=description,
        unit=unit,
        price_per_unit=Decimal(str(price_per_unit)),
        available_quantity=result.validated_amount,
        validated_amount=result.validated_amount,
        required_format=ext,
        spec=spec_dict,
        license_id=license_id or None,
        provenance=provenance,
        sample=result.sample,
        dataset_hash=result.dataset_hash,
        storage_location=storage_location,
        key_hashes=result.key_hashes or None,
        quality_score=result.quality_score,
        pii_report=result.pii_report or None,
        quarantined=(result.pii_report or {}).get("risk") == "high",
        owner_signature=warranty_sig,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return _serialize(listing, full=True)


@router.get("/")
def browse_listings(
    unit: str = Query(None),
    db: Session = Depends(get_db),
):
    """Public catalog — active, non-quarantined listings with stock remaining."""
    q = db.query(Listing).filter(
        Listing.is_deleted == False,
        Listing.status == ListingStatus.ACTIVE,
        Listing.quarantined == False,
        Listing.available_quantity > 0,
    )
    if unit:
        q = q.filter(Listing.unit == unit)
    listings = q.order_by(Listing.created_at.desc()).all()
    return [_serialize(x) for x in listings]


@router.get("/{listing_id}")
def get_listing(listing_id: str, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.id == listing_id, Listing.is_deleted == False).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return _serialize(listing, full=True)


@router.get("/{listing_id}/sample")
def get_listing_sample(listing_id: str, db: Session = Depends(get_db)):
    """Pre-purchase preview — the neutralized sample rows only, never the full file."""
    listing = db.query(Listing).filter(Listing.id == listing_id, Listing.is_deleted == False).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {
        "listing_id": str(listing.id),
        "sample": listing.sample or [],
        "sample_count": len(listing.sample or []),
    }


# ---------------------------------------------------------------------------
# Purchase: buy a portion, priced per record, settled through the ledger
# ---------------------------------------------------------------------------

class PurchaseRequest(BaseModel):
    quantity: int


def _slice_dataset(file_bytes: bytes, ext: str, quantity: int) -> bytes:
    """Return only the first `quantity` records — the buyer pays per record and
    receives exactly what they bought, not the whole file."""
    text = file_bytes.decode("utf-8-sig", errors="replace")
    if ext == "jsonl":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return ("\n".join(lines[:quantity]) + "\n").encode()
    lines = text.splitlines()
    if not lines:
        return file_bytes
    header, data = lines[0], lines[1:]
    return ("\n".join([header] + data[:quantity]) + "\n").encode()


def _serialize_purchase(p: Purchase) -> dict:
    return {
        "id": str(p.id),
        "listing_id": str(p.listing_id),
        "buyer_id": str(p.buyer_id),
        "quantity": p.quantity,
        "unit_price": float(p.unit_price) if p.unit_price is not None else None,
        "amount": float(p.amount) if p.amount is not None else None,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.post("/{listing_id}/purchase")
def purchase_listing(
    listing_id: str,
    body: PurchaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Buy `quantity` records from a listing (capped at availability), settled per
    record through the same escrow/ledger as Request fulfilment. The listing row is
    locked FOR UPDATE so concurrent buyers can't oversell the last records (mirrors
    the F2 accept lock).
    """
    if current_user.role != UserRole.REQUESTER:
        raise HTTPException(status_code=403, detail="Only buyers can purchase listings")
    if body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be positive")

    listing = (
        db.execute(select(Listing).where(Listing.id == listing_id).with_for_update())
        .scalars().first()
    )
    if not listing or listing.is_deleted:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.quarantined or listing.status != ListingStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Listing is not available for purchase")
    if (listing.available_quantity or 0) <= 0:
        raise HTTPException(status_code=409, detail="Listing is sold out")

    qty = min(body.quantity, listing.available_quantity)   # cap at availability
    unit_price = Decimal(str(listing.price_per_unit))
    amount = (Decimal(qty) * unit_price).quantize(Decimal("0.01"))

    purchase = Purchase(
        listing_id=listing.id, buyer_id=current_user.id,
        quantity=qty, unit_price=unit_price, amount=amount, status="pending",
    )
    db.add(purchase)
    db.flush()

    # Deliver exactly the purchased portion as the buyer's own file.
    src = get_storage().read(listing.storage_location)
    sliced = _slice_dataset(src, listing.required_format or "csv", qty)
    pkey = f"purchases/{current_user.id}/{purchase.id}.{listing.required_format or 'csv'}"
    purchase.storage_location = get_storage().save(pkey, sliced)

    # Settle through the ledger: hold then release (deterministic refs → idempotent).
    append_ledger(db, None, "hold", amount, f"phold_{purchase.id}", purchase_id=purchase.id)
    append_ledger(db, None, "release", amount, f"prelease_{purchase.id}", purchase_id=purchase.id)
    purchase.status = "paid"

    listing.available_quantity -= qty
    if listing.available_quantity <= 0:
        listing.status = ListingStatus.SOLD_OUT

    db.commit()
    db.refresh(purchase)
    bal = purchase_balance(db, purchase.id)
    return {
        "purchase": _serialize_purchase(purchase),
        "settled": str(bal["released"]),
        "remaining_in_listing": listing.available_quantity,
    }


@purchases_router.get("/")
def my_purchases(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(Purchase)
        .filter(Purchase.buyer_id == current_user.id, Purchase.is_deleted == False)
        .order_by(Purchase.created_at.desc())
        .all()
    )
    return [_serialize_purchase(p) for p in rows]


@purchases_router.get("/{purchase_id}/download")
def download_purchase(
    purchase_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gated delivery of the purchased portion — buyer-only, PAID-only, attachment."""
    purchase = db.query(Purchase).filter(
        Purchase.id == purchase_id, Purchase.is_deleted == False
    ).first()
    # 404 (not 403) on a wrong owner so we don't leak existence.
    if not purchase or str(purchase.buyer_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Purchase not found")
    if purchase.status != "paid":
        raise HTTPException(status_code=403, detail="Purchase is not settled")

    listing = db.query(Listing).filter(Listing.id == str(purchase.listing_id)).first()
    if listing and (listing.quarantined or listing.is_deleted):
        raise HTTPException(status_code=410, detail="This dataset has been taken down")
    if not purchase.storage_location:
        raise HTTPException(status_code=404, detail="No file on record for this purchase")

    fname = f"{(listing.title if listing else 'dataset')}.{listing.required_format if listing else 'csv'}"
    url = get_storage().presigned_url(purchase.storage_location, filename=fname)
    return {"url": url, "purchase_id": purchase_id, "quantity": purchase.quantity}
