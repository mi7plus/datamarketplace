# app/profile.py
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.models import UserProfile, UserAuth as User, UserRole
from app.schemas import ProfileCreate
from app.db import get_db
from app.auth import get_current_user
from app.payments import get_payment_provider
from app.notifications import notify

PAYOUT_COOLDOWN_HOURS = int(os.getenv("PAYOUT_COOLDOWN_HOURS", "24"))

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

    if not current_user.stripe_account_id:
        # First-time onboarding — establish the destination, no cool-down.
        current_user.stripe_account_id = acct_id
        db.commit()
    elif current_user.stripe_account_id != acct_id:
        # CHANGING the payout destination — the most lucrative ATO target.
        # Stamp a cool-down so the new account can't immediately receive releases,
        # and send an out-of-band notice so the real owner can react.
        current_user.stripe_account_id = acct_id
        current_user.payout_account_changed_at = datetime.utcnow()
        db.commit()
        notify(
            current_user,
            "Your payout account was changed",
            "Your Rowbound payout destination was updated. If this wasn't you, contact "
            f"support immediately. Releases are held for {PAYOUT_COOLDOWN_HOURS}h as a "
            "security measure.",
        )

    return {"url": url, "stripe_account_id": acct_id}


@router.get("/stripe-status")
def stripe_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return whether the provider has a connected Stripe account."""
    return {"connected": bool(current_user.stripe_account_id)}