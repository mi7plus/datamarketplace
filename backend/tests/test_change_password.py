# tests/test_change_password.py
# S3: changing the password re-authenticates with the current one and revokes all
# refresh sessions (old refresh cookie can no longer mint tokens).

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping change-password test",
)


def _cleanup(email):
    with SessionLocal() as db:
        db.execute(text("DELETE FROM user_auth WHERE email = :e"), {"e": email})
        db.commit()


def test_change_password_revokes_sessions():
    email = f"cp_{uuid.uuid4().hex[:8]}@t.io"
    client = TestClient(app)
    try:
        client.post("/auth/register", json={"email": email, "password": "oldpw1234", "role": "requester"})
        login = client.post("/auth/login", json={"email": email, "password": "oldpw1234"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}

        # refresh works before the change
        assert client.get("/auth/refresh").status_code == 200

        # wrong current password is rejected
        assert client.post("/auth/change-password", headers=hdr,
                           json={"current_password": "WRONG", "new_password": "newpw5678"}).status_code == 401
        # too-short new password rejected
        assert client.post("/auth/change-password", headers=hdr,
                           json={"current_password": "oldpw1234", "new_password": "short"}).status_code == 422

        # valid change succeeds
        ok = client.post("/auth/change-password", headers=hdr,
                         json={"current_password": "oldpw1234", "new_password": "newpw5678"})
        assert ok.status_code == 200, ok.text

        # old refresh cookie is now dead → 401
        assert client.get("/auth/refresh").status_code == 401
        # old password no longer logs in; new one does
        assert client.post("/auth/login", json={"email": email, "password": "oldpw1234"}).status_code == 401
        assert client.post("/auth/login", json={"email": email, "password": "newpw5678"}).status_code == 200
    finally:
        _cleanup(email)
