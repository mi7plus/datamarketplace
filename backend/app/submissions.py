# app/submissions.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Submission
from app.schemas import SubmissionCreateSchema

router = APIRouter()

@router.post("/")
def create_submission(data: SubmissionCreateSchema, db: Session = Depends(get_db)):
    submission = Submission(
        request_id=data.request_id,
        provider_id=1,  # TODO: replace with current user ID from JWT
        content_link=data.content_link,
        accepted_amount=data.amount_provided
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission