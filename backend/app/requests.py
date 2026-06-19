# app/requests.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db import get_db
from app.models import DataRequest, UserAuth as User, UserRole
from app.schemas import DataRequestCreateSchema
from app.auth import get_current_user

router = APIRouter()

@router.post("/")
def create_request(
    data: DataRequestCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.REQUESTER:
        raise HTTPException(status_code=403, detail="Only requesters can post data requests")
    request = DataRequest(**data.dict(), requester_id=current_user.id)
    db.add(request)
    db.commit()
    db.refresh(request)
    return request

@router.get("/", response_model=List[DataRequestCreateSchema])
def list_requests(db: Session = Depends(get_db)):
    return db.query(DataRequest).filter(DataRequest.is_deleted == False).all()
