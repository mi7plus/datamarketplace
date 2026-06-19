# tests/test_auth_logout.py
#
# FE5: logout invalidates the server-side refresh token. After logout, the
# httpOnly refresh cookie can no longer mint access tokens (/auth/refresh -> 401).
# Requires a live Postgres (conftest loads backend/.env).

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal

from tests.test_allocation_race import DB_URL  # reuse skip logic

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping auth logout test",
)


def _cleanup(email):
    with SessionLocal() as db:
        db.execute(text("DELETE FROM user_auth WHERE email = :e"), {"e": email})
        db.commit()


def test_logout_invalidates_refresh_token():
    email = f"logout_{uuid.uuid4().hex[:8]}@test.io"
    # Fresh cookie jar per client instance
    client = TestClient(app)
    try:
        assert client.post("/auth/register", json={
            "email": email, "password": "pw123456", "role": "requester",
        }).status_code in (200, 201)

        login = client.post("/auth/login", json={"email": email, "password": "pw123456"})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        # The login response must have set the httpOnly refresh cookie
        assert "refresh_token" in login.cookies or "refresh_token" in client.cookies

        # Refresh works while the session is valid
        r1 = client.get("/auth/refresh")
        assert r1.status_code == 200, r1.text
        assert r1.json()["access_token"]

        # Logout invalidates the server-side hash and clears the cookie
        out = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert out.status_code == 200, out.text

        # Subsequent refresh must now fail
        r2 = client.get("/auth/refresh")
        assert r2.status_code == 401, f"expected 401 after logout, got {r2.status_code}: {r2.text}"
    finally:
        _cleanup(email)


def test_refresh_without_cookie_is_401():
    client = TestClient(app)
    assert client.get("/auth/refresh").status_code == 401
