# tests/test_mfa.py
# H4 (S3 HARDEN): TOTP enrol/verify + step-up MFA gate on payout-account changes.

import uuid
import pytest
import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping MFA test")

client = TestClient(app)


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_mfa_enrol_and_payout_step_up():
    sx = uuid.uuid4().hex[:8]
    P = _login(f"prov_{sx}@t.io", "provider")
    email = f"prov_{sx}@t.io"
    try:
        # Before MFA: payout surface is reachable without a code
        assert client.get("/profile/stripe-connect", headers=P).status_code == 200

        # Enrol → get secret; wrong code fails to activate
        enroll = client.post("/auth/mfa/enroll", headers=P).json()
        secret = enroll["secret"]
        assert enroll["otpauth_uri"].startswith("otpauth://")
        assert client.post("/auth/mfa/verify", headers=P, json={"code": "000000"}).status_code == 400

        # Correct code activates MFA
        totp = pyotp.TOTP(secret)
        assert client.post("/auth/mfa/verify", headers=P, json={"code": totp.now()}).status_code == 200

        # Now the payout surface requires step-up: no/invalid code → 401, valid → 200
        assert client.get("/profile/stripe-connect", headers=P).status_code == 401
        assert client.get("/profile/stripe-connect?mfa_code=000000", headers=P).status_code == 401
        assert client.get(f"/profile/stripe-connect?mfa_code={totp.now()}", headers=P).status_code == 200

        # Disabling requires a valid code
        assert client.post("/auth/mfa/disable", headers=P, json={"code": totp.now()}).status_code == 200
        assert client.get("/profile/stripe-connect", headers=P).status_code == 200
    finally:
        with SessionLocal() as db:
            db.execute(text("DELETE FROM audit_log WHERE actor_id = (SELECT id FROM user_auth WHERE email=:e)"),
                       {"e": email})
            db.execute(text("DELETE FROM user_auth WHERE email=:e"), {"e": email})
            db.commit()
