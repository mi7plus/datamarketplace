# app/collect.py
#
# Mode 3 — Collect (forms / field). A BYO-workforce org accepts a funded Collect
# request and its agents submit structured entries; each entry is QA'd (fields +
# geo-stamp + photo evidence + consent/lawful-basis). On finalize (collect_finalize),
# the valid, deduped entries are compiled into a Submission that settles through the
# same engine as Request/Catalog.

import csv
import hashlib
import io
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    DataRequest, CollectionDispatch, CollectionEntry, Submission,
    UserAuth as User, UserRole,
)
from app.auth import get_current_user
from app.ingest import _parse_value, _neutralize_sample, scan_pii_rows, SAMPLE_ROWS
from app.lifecycle import validate_submission
from app.storage import get_storage

router = APIRouter()


class DispatchCreate(BaseModel):
    request_id: UUID


class EntryCreate(BaseModel):
    data: dict
    contributor_ref: str | None = None
    geo_lat: float | None = None
    geo_lng: float | None = None
    photo_ref: str | None = None
    consent_basis: str | None = None
    lawful_basis: str | None = None


def _validate_entry(payload: EntryCreate, collection_spec: dict) -> list[str]:
    """Return a list of QA errors for an entry; empty list = valid."""
    errors: list[str] = []
    fields = (collection_spec or {}).get("fields", [])

    for f in fields:
        name, ftype, required = f["name"], f["type"], f.get("required", True)
        raw = payload.data.get(name)
        if raw in (None, ""):
            if required:
                errors.append(f"missing required field '{name}'")
            continue
        ok, _ = _parse_value(str(raw), ftype)
        if not ok:
            errors.append(f"field '{name}' is not a valid {ftype}")

    # Field-collection QA gates (the fraud surface)
    if collection_spec.get("geo_required") and (payload.geo_lat is None or payload.geo_lng is None):
        errors.append("geo-stamp (geo_lat/geo_lng) is required")
    if collection_spec.get("photo_required") and not payload.photo_ref:
        errors.append("photo evidence (photo_ref) is required")
    if collection_spec.get("consent_required") and not payload.consent_basis:
        errors.append("consent_basis is required for this collection")
    return errors


def _serialize_dispatch(d: CollectionDispatch, db: Session) -> dict:
    total = db.query(CollectionEntry).filter(CollectionEntry.dispatch_id == str(d.id)).count()
    valid = db.query(CollectionEntry).filter(
        CollectionEntry.dispatch_id == str(d.id), CollectionEntry.status == "valid"
    ).count()
    return {
        "id": str(d.id),
        "request_id": str(d.request_id),
        "org_id": str(d.org_id),
        "status": d.status,
        "submission_id": str(d.submission_id) if d.submission_id else None,
        "entries_total": total,
        "entries_valid": valid,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.post("/dispatches")
def create_dispatch(
    body: DispatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """An org with field labor accepts a funded Collect request."""
    if current_user.role != UserRole.PROVIDER:
        raise HTTPException(status_code=403, detail="Only providers (BYO-workforce orgs) can accept collections")

    request = db.query(DataRequest).filter(
        DataRequest.id == str(body.request_id), DataRequest.is_deleted == False
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.mode != "collect":
        raise HTTPException(status_code=409, detail="Request is not a collect-mode request")
    if request.status not in ("open", "partially_fulfilled"):
        raise HTTPException(status_code=409, detail=f"Request is not accepting collections (status: {request.status})")

    existing = db.query(CollectionDispatch).filter(
        CollectionDispatch.request_id == str(request.id),
        CollectionDispatch.org_id == str(current_user.id),
        CollectionDispatch.status == "open",
    ).first()
    if existing:
        return _serialize_dispatch(existing, db)

    dispatch = CollectionDispatch(request_id=request.id, org_id=current_user.id, status="open")
    db.add(dispatch)
    db.commit()
    db.refresh(dispatch)
    return _serialize_dispatch(dispatch, db)


@router.post("/dispatches/{dispatch_id}/entries")
def add_entry(
    dispatch_id: str,
    body: EntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit one structured field entry; validated against the request's collection_spec."""
    dispatch = db.query(CollectionDispatch).filter(
        CollectionDispatch.id == dispatch_id, CollectionDispatch.is_deleted == False
    ).first()
    if not dispatch:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    if str(dispatch.org_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Dispatch not found")   # don't leak
    if dispatch.status != "open":
        raise HTTPException(status_code=409, detail="Dispatch is no longer accepting entries")

    request = db.query(DataRequest).filter(DataRequest.id == str(dispatch.request_id)).first()
    errors = _validate_entry(body, request.collection_spec or {})

    entry = CollectionEntry(
        dispatch_id=dispatch.id,
        contributor_ref=body.contributor_ref,
        data=body.data,
        geo_lat=body.geo_lat, geo_lng=body.geo_lng,
        photo_ref=body.photo_ref,
        consent_basis=body.consent_basis,
        lawful_basis=body.lawful_basis,
        status="valid" if not errors else "rejected",
        validation_errors=errors or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {
        "id": str(entry.id),
        "status": entry.status,
        "validation_errors": errors,
    }


@router.get("/dispatches/{dispatch_id}")
def get_dispatch(
    dispatch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dispatch = db.query(CollectionDispatch).filter(
        CollectionDispatch.id == dispatch_id, CollectionDispatch.is_deleted == False
    ).first()
    if not dispatch:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    request = db.query(DataRequest).filter(DataRequest.id == str(dispatch.request_id)).first()
    # Visible to the owning org or the request's buyer.
    if str(dispatch.org_id) != str(current_user.id) and \
       (not request or str(request.requester_id) != str(current_user.id)):
        raise HTTPException(status_code=404, detail="Dispatch not found")
    return _serialize_dispatch(dispatch, db)


@router.post("/dispatches/{dispatch_id}/finalize")
def finalize_dispatch(
    dispatch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compile the dispatch's valid, deduped entries into a Submission that flows
    through the SAME engine as Request/Catalog (buyer reviews → accept caps against
    remaining demand + cross-source dedup → escrow settles per record). Consent /
    lawful-basis is preserved per entry for audit/takedown.
    """
    dispatch = db.query(CollectionDispatch).filter(
        CollectionDispatch.id == dispatch_id, CollectionDispatch.is_deleted == False
    ).first()
    if not dispatch:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    if str(dispatch.org_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Dispatch not found")
    if dispatch.status != "open":
        raise HTTPException(status_code=409, detail="Dispatch is not open")

    request = db.query(DataRequest).filter(DataRequest.id == str(dispatch.request_id)).first()
    spec = request.collection_spec or {}
    field_names = [f["name"] for f in spec.get("fields", [])]
    unique_key = spec.get("unique_key") or []

    entries = (
        db.query(CollectionEntry)
        .filter(CollectionEntry.dispatch_id == str(dispatch.id), CollectionEntry.status == "valid")
        .order_by(CollectionEntry.created_at)
        .all()
    )
    if not entries:
        raise HTTPException(status_code=409, detail="No valid entries to finalize")

    # Dedup within the dispatch by the declared key (cross-source dedup happens at accept).
    seen: set = set()
    deduped: list[CollectionEntry] = []
    for e in entries:
        if unique_key:
            kv = tuple(str((e.data or {}).get(k, "")) for k in unique_key)
            if kv in seen:
                continue
            seen.add(kv)
        deduped.append(e)

    # Compile to a CSV dataset (the deliverable), compute hashes + sample.
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(field_names)
    for e in deduped:
        w.writerow([(e.data or {}).get(f, "") for f in field_names])
    file_bytes = buf.getvalue().encode()
    dataset_hash = hashlib.sha256(file_bytes).hexdigest()

    key_hashes = []
    if unique_key:
        for e in deduped:
            kv = tuple(str((e.data or {}).get(k, "")) for k in unique_key)
            key_hashes.append(hashlib.sha256(repr(kv).encode()).hexdigest())

    sample = _neutralize_sample([
        {f: (e.data or {}).get(f) for f in field_names} for e in deduped[:SAMPLE_ROWS]
    ])
    validated_amount = len(deduped)

    storage_key = f"collect/{dispatch.org_id}/{dispatch.id}.csv"
    storage_location = get_storage().save(storage_key, file_bytes)

    # Consent posture for the collected data (per-entry detail stays on CollectionEntry).
    consent_summary = {
        "consent_required": bool(spec.get("consent_required")),
        "with_consent_basis": sum(1 for e in deduped if e.consent_basis),
        "with_lawful_basis": sum(1 for e in deduped if e.lawful_basis),
        "geo_stamped": sum(1 for e in deduped if e.geo_lat is not None),
        "photo_evidenced": sum(1 for e in deduped if e.photo_ref),
    }

    submission = Submission(
        request_id=request.id,
        provider_id=current_user.id,
        content_link=f"collection-{dispatch.id}.csv",
        offered_amount=validated_amount,
        accepted_amount=0,
        file_size_bytes=len(file_bytes),
        mime_type="text/csv",
        storage_location=storage_location,
        dataset_hash=dataset_hash,
        key_hashes=key_hashes or None,
        quality_score=1.0,   # per-entry QA already enforced field/geo/photo/consent gates
        owner_signature=f"collected via dispatch {dispatch.id} by {current_user.email} at {datetime.utcnow().isoformat()}Z",
    )
    db.add(submission)
    db.flush()

    report = {
        "total_rows": len(entries),
        "conforming_rows": validated_amount,
        "rejected_rows": 0,
        "duplicate_rows": len(entries) - validated_amount,
        "sample": sample,
        "pii": scan_pii_rows([{f: (e.data or {}).get(f) for f in field_names} for e in deduped]),
        "collection": {"dispatch_id": str(dispatch.id), "consent": consent_summary},
    }
    if unique_key:
        report["unique_key"] = unique_key

    validate_submission(submission, validated_amount, report, db)

    dispatch.submission_id = submission.id
    dispatch.status = "finalized"
    db.commit()
    db.refresh(submission)

    return {
        "dispatch": _serialize_dispatch(dispatch, db),
        "submission_id": str(submission.id),
        "submission_status": submission.status,
        "validated_amount": validated_amount,
        "deduplicated": len(entries) - validated_amount,
    }
