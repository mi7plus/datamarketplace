# app/requests.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.db import get_db
from app.models import DataRequest
from app.schemas import DataRequestCreateSchema

router = APIRouter()

@router.post("/")
def create_request(data: DataRequestCreateSchema, db: Session = Depends(get_db)):
    request = DataRequest(**data.dict())
    db.add(request)
    db.commit()
    db.refresh(request)
    return request

@router.get("/", response_model=List[DataRequestCreateSchema])
def list_requests(db: Session = Depends(get_db)):
    return db.query(DataRequest).all()