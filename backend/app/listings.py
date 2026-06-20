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
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Listing, ListingStatus, License, UserAuth as User, UserRole
from app.auth import get_current_user
from app.ingest import validate_dataset
from app.filesafety import assert_safe_text_upload
from app.storage import get_storage

router = APIRouter()

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
