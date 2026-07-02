# tests/test_social_login.py
# Social-login plan Phase 2: the account-linking engine (§4.2) + login guards.
# Covers the §9 must-haves. Decisions: auto-link immediately (safe under the
# verification hard-gate); never act on an unverified provider email.

import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import UserAuth, UserIdentity, UserRole
from app.social_auth import resolve_social_login
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set")
client = TestClient(app)


def _email():
    return f"soc_{uuid.uuid4().hex[:10]}@t.io"


def _mk_password_user(db, email, *, verified):
    u = UserAuth(email=email, password_hash="x", role=UserRole.REQUESTER, is_verified=verified)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _cleanup(db, *emails):
    for email in emails:
        u = db.query(UserAuth).filter(UserAuth.email == email).first()
        if u:
            db.query(UserIdentity).filter(UserIdentity.user_id == u.id).delete()
            db.delete(u)
    db.commit()


def test_new_verified_email_creates_verified_user():
    db = SessionLocal(); email = _email()
    try:
        u = resolve_social_login(db, provider="google", subject="sub-" + email, email=email, email_verified=True)
        assert u.is_verified is True
        assert u.password_hash is None                       # social-only
        assert db.query(UserIdentity).filter(UserIdentity.user_id == u.id).count() == 1
    finally:
        _cleanup(db, email); db.close()


def test_subject_match_returns_same_user_no_duplicate():
    db = SessionLocal(); email = _email(); sub = "sub-" + email
    try:
        u1 = resolve_social_login(db, provider="google", subject=sub, email=email, email_verified=True)
        u2 = resolve_social_login(db, provider="google", subject=sub, email=email, email_verified=True)
        assert str(u1.id) == str(u2.id)
        assert db.query(UserIdentity).filter(UserIdentity.provider_subject == sub).count() == 1
    finally:
        _cleanup(db, email); db.close()


def test_verified_email_links_to_verified_existing_user():
    db = SessionLocal(); email = _email()
    try:
        existing = _mk_password_user(db, email, verified=True)
        u = resolve_social_login(db, provider="google", subject="sub-" + email, email=email, email_verified=True)
        assert str(u.id) == str(existing.id)                 # linked, not duplicated
        assert db.query(UserIdentity).filter(UserIdentity.user_id == existing.id).count() == 1
    finally:
        _cleanup(db, email); db.close()


def test_verified_email_autolinks_unverified_existing_and_verifies():
    # Decision §7.1 = auto-link immediately; safe because login is hard-gated so the
    # unverified account was inert. The provider proved the email → mark verified.
    db = SessionLocal(); email = _email()
    try:
        existing = _mk_password_user(db, email, verified=False)
        u = resolve_social_login(db, provider="microsoft", subject="sub-" + email, email=email, email_verified=True)
        assert str(u.id) == str(existing.id)
        db.refresh(existing)
        assert existing.is_verified is True                  # now verified
    finally:
        _cleanup(db, email); db.close()


def test_unverified_provider_email_never_touches_accounts():
    db = SessionLocal(); email = _email()
    try:
        _mk_password_user(db, email, verified=True)
        with pytest.raises(HTTPException) as ei:
            resolve_social_login(db, provider="google", subject="sub-x", email=email, email_verified=False)
        assert ei.value.status_code == 403
        # No identity was created for that subject.
        assert db.query(UserIdentity).filter(UserIdentity.provider_subject == "sub-x").count() == 0
    finally:
        _cleanup(db, email); db.close()


# ---- login guards ----------------------------------------------------------

def test_social_only_account_cannot_password_login():
    db = SessionLocal(); email = _email()
    try:
        resolve_social_login(db, provider="google", subject="sub-" + email, email=email, email_verified=True)
        r = client.post("/auth/login", json={"email": email, "password": "anything"})
        assert r.status_code == 401                          # null password_hash → invalid credentials
    finally:
        _cleanup(db, email); db.close()


def test_hard_gate_blocks_unverified_login_when_enabled(monkeypatch):
    db = SessionLocal(); email = _email()
    try:
        # A real password account, unverified.
        from app.auth import pwd_context
        u = UserAuth(email=email, password_hash=pwd_context.hash("pw123456"),
                     role=UserRole.REQUESTER, is_verified=False)
        db.add(u); db.commit()

        monkeypatch.setenv("REQUIRE_VERIFIED_EMAIL", "true")
        r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
        assert r.status_code == 403                          # hard-gated

        # Verify → login now succeeds.
        u.is_verified = True; db.commit()
        r2 = client.post("/auth/login", json={"email": email, "password": "pw123456"})
        assert r2.status_code == 200 and r2.json().get("access_token")
    finally:
        _cleanup(db, email); db.close()
