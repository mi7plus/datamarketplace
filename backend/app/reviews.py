# app/reviews.py
#
# Reviews — 1-5 star ratings left by either party after a PAID submission.
# Rules:
#   - Only after the submission is PAID.
#   - One review per (author, submission) pair.
#   - Requester reviews the provider; provider reviews the requester.
#   - After each review, recompute the subject's UserAnalytics.reputation_score.

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as PydanticModel, Field
from sqlalchemy.orm import Session
from datetime import datetime

from app.db import get_db
from app.models import Review, Submission, DataRequest, UserAuth as User, UserAnalytics, SubmissionStatus, UserRole
from app.auth import get_current_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ReviewCreate(PydanticModel):
    submission_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None


class ReviewOut(PydanticModel):
    id: str
    submission_id: str
    rating: int
    comment: str | None
    author_id: str
    subject_id: str
    created_at: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _recompute_reputation(subject_id: str, db: Session) -> None:
    """Average all ratings for subject_id and update UserAnalytics."""
    reviews = db.query(Review).filter(Review.subject_id == str(subject_id)).all()
    if not reviews:
        return
    avg = sum(r.rating for r in reviews) / len(reviews)

    analytics = db.query(UserAnalytics).filter(UserAnalytics.user_id == str(subject_id)).first()
    if not analytics:
        analytics = UserAnalytics(user_id=str(subject_id))
        db.add(analytics)
    analytics.reputation_score = round(avg, 2)
    analytics.last_activity_at = datetime.utcnow()
    db.flush()


def _increment_transactions(user_id: str, successful: bool, db: Session) -> None:
    analytics = db.query(UserAnalytics).filter(UserAnalytics.user_id == str(user_id)).first()
    if not analytics:
        analytics = UserAnalytics(user_id=str(user_id))
        db.add(analytics)
    analytics.total_transactions = (analytics.total_transactions or 0) + 1
    if successful:
        analytics.successful_transactions = (analytics.successful_transactions or 0) + 1
    analytics.last_activity_at = datetime.utcnow()
    db.flush()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/", response_model=ReviewOut)
def create_review(
    data: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    submission = db.query(Submission).filter(
        Submission.id == data.submission_id,
        Submission.is_deleted == False,
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if submission.status != SubmissionStatus.PAID:
        raise HTTPException(status_code=409, detail="Reviews are only allowed after payment (PAID)")

    data_request = db.query(DataRequest).filter(DataRequest.id == str(submission.request_id)).first()

    # Determine who is reviewing whom
    is_requester = str(data_request.requester_id) == str(current_user.id)
    is_provider = str(submission.provider_id) == str(current_user.id)

    if not is_requester and not is_provider:
        raise HTTPException(status_code=403, detail="Only the requester or provider on this submission can leave a review")

    subject_id = str(submission.provider_id) if is_requester else str(data_request.requester_id)

    # One review per (author, submission)
    existing = db.query(Review).filter(
        Review.author_id == str(current_user.id),
        Review.submission_id == data.submission_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="You have already reviewed this submission")

    review = Review(
        request_id=str(data_request.id),
        submission_id=data.submission_id,
        author_id=str(current_user.id),
        subject_id=subject_id,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(review)
    db.flush()

    _recompute_reputation(subject_id, db)
    db.commit()
    db.refresh(review)

    return ReviewOut(
        id=str(review.id),
        submission_id=str(review.submission_id),
        rating=review.rating,
        comment=review.comment,
        author_id=str(review.author_id),
        subject_id=str(review.subject_id),
        created_at=review.created_at.isoformat() if review.created_at else None,
    )


@router.get("/user/{user_id}")
def get_user_reviews(user_id: str, db: Session = Depends(get_db)):
    """Public — anyone can see ratings for a user."""
    reviews = (
        db.query(Review)
        .filter(Review.subject_id == user_id)
        .order_by(Review.created_at.desc())
        .all()
    )
    avg = round(sum(r.rating for r in reviews) / len(reviews), 2) if reviews else None
    return {
        "user_id": user_id,
        "average_rating": avg,
        "review_count": len(reviews),
        "reviews": [
            {
                "id": str(r.id),
                "rating": r.rating,
                "comment": r.comment,
                "submission_id": str(r.submission_id),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reviews
        ],
    }
