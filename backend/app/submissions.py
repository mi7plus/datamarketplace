# app/submissions.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Submission, UserAuth as User
from app.schemas import SubmissionCreateSchema
from app.auth import get_current_user

router = APIRouter()

@router.post("/")
def create_submission(
    data: SubmissionCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    submission = Submission(
        request_id=data.request_id,
        provider_id=current_user.id,
        content_link=data.content_link,
        offered_amount=data.offered_amount,
        accepted_amount=0,  # acceptance is a separate buyer act (Phase 4)
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission
