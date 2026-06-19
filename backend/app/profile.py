# app/profile.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.models import UserProfile, UserAuth as User
from app.schemas import ProfileCreate
from app.db import get_db
from app.auth import get_current_user

router = APIRouter()

@router.post("")
def create_or_update_profile(
    profile_data: ProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check if user already has a profile
    existing_profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    profile_fields = profile_data.dict(exclude_unset=True, exclude={"email"})

    if existing_profile:
        for field, value in profile_fields.items():
            setattr(existing_profile, field, value)
        db.commit()
        db.refresh(existing_profile)
        return {"message": "Profile updated", "profile": existing_profile}

    new_profile = UserProfile(
        user_id=current_user.id,
        **profile_data.dict(exclude={"email"})
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)
    return {"message": "Profile created", "profile": new_profile}

@router.get("/", response_model=ProfileCreate)
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile:
        return {
            "user_type": "",
            "firstName": "",
            "lastName": "",
            "companyName": "",
            "email": current_user.email,
            "phone": "",
            "address": ""
        }

    return ProfileCreate(
        user_type=profile.user_type or "",
        firstName=profile.first_name,
        lastName=profile.last_name,
        companyName=profile.company_name,
        email=current_user.email,
        phone=profile.phone,
        address=profile.address
    )