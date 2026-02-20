# app/profile.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.models import UserProfile, User
from app.schemas import ProfileCreate
from app.db import get_db
from app.auth_dependencies import get_current_user

router = APIRouter()

@router.post("")
def create_or_update_profile(
    profile_data: ProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check if user already has a profile
    existing_profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if existing_profile:
        # Update existing profile
        for field, value in profile_data.dict(exclude_unset=True).items():
            setattr(existing_profile, field, value)
        db.commit()
        db.refresh(existing_profile)
        return {"message": "Profile updated", "profile": existing_profile}

    # Create new profile
    new_profile = UserProfile(
        user_id=current_user.id,
        **profile_data.dict()
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)
    return {"message": "Profile created", "profile": new_profile}