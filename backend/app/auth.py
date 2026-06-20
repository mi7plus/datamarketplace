from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt, JWTError
import os
import uuid
import hashlib

from app.schemas import RegisterSchema, LoginSchema, TokenSchema
from app.models import UserAuth as User
from app.db import get_db

router = APIRouter()

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
# REGISTER
# -----------------------------

@router.post("/register")
def register(data: RegisterSchema, db: Session = Depends(get_db)):
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

    return {"msg": "User registered"}


# -----------------------------
# LOGIN ⭐⭐⭐⭐⭐
# -----------------------------

@router.post("/login")
def login(
    data: LoginSchema,
    db: Session = Depends(get_db),
    response: Response = None
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
    db: Session = Depends(get_db)
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