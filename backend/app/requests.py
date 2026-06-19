# app/requests.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.db import get_db
from app.models import DataRequest, UserAuth as User, UserRole, PricingMode
from app.schemas import DataRequestCreateSchema, DataRequestResponseSchema
from app.auth import get_current_user

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
