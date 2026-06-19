# app/profile.py
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.models import UserProfile, UserAuth as User, UserRole
from app.schemas import ProfileCreate
from app.db import get_db
from app.auth import get_current_user
from app.payments import get_payment_provider

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


# ---------------------------------------------------------------------------
# Stripe Connect onboarding (providers only)
# ---------------------------------------------------------------------------

@router.get("/stripe-connect")
def stripe_connect_link(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a Stripe Connect onboarding URL so the provider can receive payouts."""
    if current_user.role != UserRole.PROVIDER:
        raise HTTPException(status_code=403, detail="Only providers use Stripe Connect")

    frontend = os.getenv("FRONTEND_URL", "http://localhost:3000")
    return_url = f"{frontend}/profile?stripe=success"
    refresh_url = f"{frontend}/profile?stripe=refresh"

    payment = get_payment_provider()
    url, acct_id = payment.create_connect_link(current_user, return_url, refresh_url)

    # Persist the account id if it was just created
    if not current_user.stripe_account_id or current_user.stripe_account_id != acct_id:
        current_user.stripe_account_id = acct_id
        db.commit()

    return {"url": url, "stripe_account_id": acct_id}


@router.get("/stripe-status")
def stripe_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return whether the provider has a connected Stripe account."""
    return {"connected": bool(current_user.stripe_account_id)}