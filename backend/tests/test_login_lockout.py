# tests/test_login_lockout.py
# S3: failed-login lockout is enforced (not just modelled) — N failures lock the
# account for a window; correct password is refused while locked; success resets.

import uuid
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from app.auth import MAX_FAILED_LOGINS

from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping login lockout test",
)

client = TestClient(app)


def _cleanup(email):
    with SessionLocal() as db:
        db.execute(text("DELETE FROM user_auth WHERE email = :e"), {"e": email})
        db.commit()


def test_lockout_after_threshold_and_reset_on_success():
    email = f"lock_{uuid.uuid4().hex[:8]}@t.io"
    try:
        client.post("/auth/register", json={"email": email, "password": "rightpw123", "role": "requester"})

        # N wrong-password attempts → all 401
        for _ in range(MAX_FAILED_LOGINS):
            r = client.post("/auth/login", json={"email": email, "password": "wrong"})
            assert r.status_code == 401

        # Now locked: even the CORRECT password is refused with 423
        r = client.post("/auth/login", json={"email": email, "password": "rightpw123"})
        assert r.status_code == 423, r.text

        # Account row reflects the lock
        with SessionLocal() as db:
            row = db.execute(text(
                "SELECT account_locked, failed_login_attempts, locked_until FROM user_auth WHERE email = :e"
            ), {"e": email}).first()
            assert row.account_locked is True
            assert row.failed_login_attempts >= MAX_FAILED_LOGINS
            assert row.locked_until is not None

            # Simulate the window elapsing
            db.execute(text(
                "UPDATE user_auth SET locked_until = :t WHERE email = :e"
            ), {"t": datetime.utcnow() - timedelta(minutes=1), "e": email})
            db.commit()

        # After the window, correct password succeeds and clears the failure state
        r = client.post("/auth/login", json={"email": email, "password": "rightpw123"})
        assert r.status_code == 200, r.text

        with SessionLocal() as db:
            row = db.execute(text(
                "SELECT account_locked, failed_login_attempts, locked_until FROM user_auth WHERE email = :e"
            ), {"e": email}).first()
            assert row.account_locked is False
            assert row.failed_login_attempts == 0
            assert row.locked_until is None
    finally:
        _cleanup(email)
