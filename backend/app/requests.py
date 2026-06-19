# app/requests.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.db import get_db
from app.models import DataRequest, UserAuth as User, UserRole, PricingMode, RequestStatus, Ledger
from app.schemas import DataRequestCreateSchema, DataRequestResponseSchema
from app.auth import get_current_user
from app.lifecycle import open_request, expire_request
from app.payments import get_payment_provider, ledger_balance

router = APIRouter()


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
        raise HTTPException(status_code=403, detail="Not your request")
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
        raise HTTPException(status_code=403, detail="Not your request")

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
        raise HTTPException(status_code=403, detail="Not your request")

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
