# app/social_auth.py
#
# Account-linking engine for social login (design doc §4.2). This is the security
# heart — the OAuth dance is the easy part. Pure DB logic, no HTTP/provider code,
# so it's unit-testable against the §9 must-have cases.
#
# Locked decisions baked in:
#  - AUTO-LINK IMMEDIATELY on a provider-verified email (design §7.1). This is safe
#    ONLY because login is hard-gated on verification (REQUIRE_VERIFIED_EMAIL): an
#    unverified account is inert (no password login → no planted payout/data), so a
#    verified social login can safely claim it. If the hard-gate is ever removed,
#    this becomes an account-takeover path — revisit then.
#  - NEVER act on a provider email whose `email_verified` claim is false/absent.
#  - The stable key is the OIDC `sub` (provider_subject), never the email.

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import UserAuth, UserIdentity, UserRole

# New social-only signups default to buyer; they can change it in their profile.
DEFAULT_SOCIAL_ROLE = UserRole.REQUESTER


def _find_identity(db: Session, provider: str, subject: str) -> UserIdentity | None:
    return (
        db.query(UserIdentity)
        .filter(
            UserIdentity.provider == provider,
            UserIdentity.provider_subject == subject,
            UserIdentity.is_deleted == False,  # noqa: E712
        )
        .first()
    )


def _add_identity(db: Session, user: UserAuth, provider: str, subject: str, email: str) -> None:
    if not _find_identity(db, provider, subject):
        db.add(UserIdentity(user_id=user.id, provider=provider, provider_subject=subject, email_at_link=email))


def resolve_social_login(db: Session, *, provider: str, subject: str, email: str | None,
                         email_verified: bool) -> UserAuth:
    """Resolve a verified provider identity to a Rowbound user, creating or linking
    per §4.2. Returns the user to issue a session for; raises 403 when the provider
    email isn't verified (so it can never touch an existing account)."""
    # 1) Stable subject match — this identity has signed in before. Email irrelevant.
    ident = _find_identity(db, provider, subject)
    if ident:
        user = (
            db.query(UserAuth)
            .filter(UserAuth.id == str(ident.user_id), UserAuth.is_deleted == False)  # noqa: E712
            .first()
        )
        if user:
            return user

    # 2) No subject match → only a provider-VERIFIED email may touch accounts.
    if not email_verified:
        raise HTTPException(
            status_code=403,
            detail=f"Your {provider} account's email is not verified; sign in another way.",
        )
    email = (email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=403, detail="The provider returned no email.")

    existing = (
        db.query(UserAuth)
        .filter(func.lower(UserAuth.email) == email, UserAuth.is_deleted == False)  # noqa: E712
        .first()
    )

    if existing is None:
        # Brand-new social user — verified, no password.
        user = UserAuth(email=email, password_hash=None, role=DEFAULT_SOCIAL_ROLE, is_verified=True)
        db.add(user)
        db.flush()
        _add_identity(db, user, provider, subject, email)
        db.commit()
        db.refresh(user)
        return user

    # Existing account with this verified email → auto-link. The provider proved the
    # email, so mark it verified (see the module note on why this is safe).
    if not existing.is_verified:
        existing.is_verified = True
    _add_identity(db, existing, provider, subject, email)
    db.commit()
    db.refresh(existing)
    return existing
