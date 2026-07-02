from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt, JWTError
from pydantic import BaseModel, EmailStr
import os
import uuid
import hashlib
import logging

from app.schemas import RegisterSchema, LoginSchema, TokenSchema
from app.models import UserAuth as User
from app.db import get_db
from app.ratelimit import rate_limit
from app.mailer import get_mailer

logger = logging.getLogger("auth")

router = APIRouter()

# Per-IP throttles on brute-force-prone auth endpoints (S6).
_login_rl = rate_limit("login", limit=10, window_seconds=60)
_register_rl = rate_limit("register", limit=5, window_seconds=60)
_refresh_rl = rate_limit("refresh", limit=30, window_seconds=60)

SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", 1))

# Login lockout (S3): after MAX_FAILED_LOGINS within a window, lock the account
# for LOCKOUT_MINUTES (time-based, so an attacker can't permanently DoS a victim).
MAX_FAILED_LOGINS = int(os.getenv("MAX_FAILED_LOGINS", "5"))
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# -----------------------------
# TOKEN FUNCTIONS
# -----------------------------

def create_access_token(user_id: str):
    payload = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "exp": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str):
    payload = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "exp": datetime.utcnow() + timedelta(days=30)
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _hash_refresh_token(token: str) -> str:
    """SHA-256 of the refresh token, stored server-side so logout can invalidate it.
    (SHA-256, not bcrypt: the JWT exceeds bcrypt's 72-byte input limit.)"""
    return hashlib.sha256(token.encode()).hexdigest()


# -----------------------------
# EMAIL VERIFICATION (Social-login plan, Phase 1)
# -----------------------------
# `is_verified` is the single "email proven" flag (reused as email_verified). A
# signed, expiring token is emailed on register; GET /auth/verify sets it true.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://localhost:3001")
EMAIL_VERIFICATION_EXPIRE_HOURS = int(os.getenv("EMAIL_VERIFICATION_EXPIRE_HOURS", "24"))


def create_email_verification_token(user_id: str) -> str:
    payload = {
        "sub": str(user_id),
        "purpose": "email_verify",
        "exp": datetime.utcnow() + timedelta(hours=EMAIL_VERIFICATION_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_email_verification_token(token: str) -> str:
    """Return the user_id from a valid email-verification token, or raise 400."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    if payload.get("purpose") != "email_verify" or not payload.get("sub"):
        raise HTTPException(status_code=400, detail="Invalid verification link")
    return payload["sub"]


def _send_verification_email(user) -> None:
    """Best-effort: email a verification link. Never raises — a mail failure must
    not block registration (the user can request a resend)."""
    try:
        token = create_email_verification_token(user.id)
        link = f"{PUBLIC_API_URL}/auth/verify?token={token}"
        get_mailer().send(
            to=user.email,
            subject="Verify your Rowbound email",
            body=(
                "Welcome to Rowbound.\n\n"
                f"Confirm your email address to finish setting up your account:\n{link}\n\n"
                f"This link expires in {EMAIL_VERIFICATION_EXPIRE_HOURS} hours. "
                "If you didn't sign up, you can ignore this email."
            ),
        )
    except Exception:
        logger.exception("failed to send verification email to %s", getattr(user, "email", "?"))


# -----------------------------
# REGISTER
# -----------------------------

@router.post("/register")
def register(data: RegisterSchema, db: Session = Depends(get_db), _rl=Depends(_register_rl)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = pwd_context.hash(data.password)

    user = User(
        email=data.email,
        password_hash=hashed,
        role=data.role
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # Email verification (Phase 1). Additive: registration still succeeds and the
    # account is usable; is_verified stays False until the link is clicked.
    _send_verification_email(user)

    return {"msg": "User registered", "verification_email_sent": True}


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    """Confirm an email from the link in the verification email. Sets is_verified,
    then redirects into the app. Idempotent — a second click is a clean no-op."""
    user_id = _decode_email_verification_token(token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid verification link")
    if not user.is_verified:
        user.is_verified = True
        db.commit()
    return RedirectResponse(url=f"{FRONTEND_URL}/login?verified=1", status_code=302)


_resend_rl = rate_limit("verify_resend", limit=5, window_seconds=300)


class ResendVerificationSchema(BaseModel):
    email: EmailStr


@router.post("/verify/resend")
def resend_verification(data: ResendVerificationSchema, db: Session = Depends(get_db), _rl=Depends(_resend_rl)):
    """Re-send the verification email. Returns the SAME response whether or not the
    email exists (no account enumeration); only actually sends if it's a real,
    still-unverified account."""
    user = db.query(User).filter(User.email == data.email).first()
    if user and not user.is_verified:
        _send_verification_email(user)
    return {"msg": "If that email is registered and unverified, a verification link has been sent."}


# -----------------------------
# LOGIN ⭐⭐⭐⭐⭐
# -----------------------------

@router.post("/login")
def login(
    data: LoginSchema,
    db: Session = Depends(get_db),
    response: Response = None,
    _rl=Depends(_login_rl),
):
    user = db.query(User).filter(User.email == data.email).first()

    # Reject while a lockout window is active (don't even check the password).
    if user and user.locked_until and user.locked_until > datetime.utcnow():
        raise HTTPException(
            status_code=423,
            detail="Account temporarily locked due to failed login attempts. Try again later.",
        )

    if not user or not pwd_context.verify(data.password, user.password_hash):
        # Count the failure and lock after the threshold (only for a real account).
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_LOGINS:
                user.account_locked = True
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Success — clear the failure state.
    user.failed_login_attempts = 0
    user.account_locked = False
    user.locked_until = None
    user.last_login_at = datetime.utcnow()

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    # Store the refresh token's hash so /auth/refresh can validate it and
    # /auth/logout can invalidate it. One active refresh token per user.
    user.refresh_token_hash = _hash_refresh_token(refresh_token)
    db.commit()

    if response is not None:
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=False,   # set True in production HTTPS
            samesite="lax"
        )

    return {
        "access_token": access_token
    }


@router.get("/refresh")
def refresh_token(
    request: Request,
    db: Session = Depends(get_db),
    _rl=Depends(_refresh_rl),
):
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    try:
        payload = jwt.decode(
            refresh_token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("sub")

        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(status_code=401)

        # The presented refresh token must match the one stored at login. After
        # logout (hash cleared) or a newer login (hash rotated), this fails → 401.
        if not user.refresh_token_hash or user.refresh_token_hash != _hash_refresh_token(refresh_token):
            raise HTTPException(status_code=401, detail="Refresh token is no longer valid")

        new_access_token = create_access_token(user.id)

        return {
            "access_token": new_access_token
        }

    except JWTError:
        raise HTTPException(status_code=401)

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("sub")

        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        return user

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# -----------------------------
# LOGOUT
# -----------------------------

@router.post("/logout")
def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Invalidate the server-side refresh token and delete the cookie. After this,
    /auth/refresh returns 401 — the httpOnly cookie can no longer mint tokens."""
    current_user.refresh_token_hash = None
    db.commit()
    response.delete_cookie("refresh_token")
    return {"msg": "Logged out"}


# -----------------------------
# CHANGE PASSWORD
# -----------------------------

from pydantic import BaseModel as _PydanticModel


class ChangePassword(_PydanticModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    data: ChangePassword,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change password after re-authenticating with the current one, and REVOKE all
    existing sessions: clearing refresh_token_hash makes every outstanding refresh
    cookie dead (a subsequent /auth/refresh returns 401), so a thief who grabbed a
    cookie is logged out the moment the real owner rotates their password (S3).
    """
    if not pwd_context.verify(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")

    current_user.password_hash = pwd_context.hash(data.new_password)
    current_user.refresh_token_hash = None      # revoke all refresh sessions
    db.commit()
    response.delete_cookie("refresh_token")
    return {"msg": "Password changed — all sessions signed out"}


# -----------------------------
# MFA (TOTP) — S3 HARDEN
# -----------------------------

import pyotp


class MFACode(_PydanticModel):
    code: str


def verify_totp(user: User, code: str | None) -> bool:
    """True if `code` is a valid current TOTP for the user (and MFA is set up)."""
    if not user.mfa_secret or not code:
        return False
    return pyotp.TOTP(user.mfa_secret).verify(code, valid_window=1)


@router.post("/mfa/enroll")
def mfa_enroll(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Begin TOTP enrolment: issue a secret + provisioning URI. Not active until verified."""
    secret = pyotp.random_base32()
    current_user.mfa_secret = secret
    current_user.mfa_enabled = False
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=current_user.email, issuer_name="Rowbound")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/mfa/verify")
def mfa_verify(data: MFACode, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Confirm a code to activate MFA."""
    if not verify_totp(current_user, data.code):
        raise HTTPException(status_code=400, detail="Invalid MFA code")
    current_user.mfa_enabled = True
    db.commit()
    return {"mfa_enabled": True}


@router.post("/mfa/disable")
def mfa_disable(data: MFACode, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Disable MFA (requires a valid current code)."""
    if not verify_totp(current_user, data.code):
        raise HTTPException(status_code=400, detail="Invalid MFA code")
    current_user.mfa_secret = None
    current_user.mfa_enabled = False
    db.commit()
    return {"mfa_enabled": False}