# tests/test_anomalies.py
# H3 (S5/S6): admin anomaly flags — shape, admin-only, and shared-IP clustering.

import uuid
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping anomalies test")

client = TestClient(app)


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_anomalies_admin_only_and_shared_ip():
    sx = uuid.uuid4().hex[:8]
    R = _login(f"buy_{sx}@t.io", "requester")
    A = _login(f"adm_{sx}@t.io", "admin")
    emails = [f"buy_{sx}@t.io", f"adm_{sx}@t.io"]
    ip = f"203.0.113.{uuid.uuid4().int % 250}"
    a1, a2 = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        assert client.get("/metrics/anomalies", headers=R).status_code == 403

        # Two distinct actors sharing one IP in the audit log → a sybil cluster signal.
        with SessionLocal() as db:
            for actor in (a1, a2):
                db.execute(text(
                    "INSERT INTO audit_log (id, created_at, actor_id, ip, action, object_type, object_id) "
                    "VALUES (:i, now(), :a, :ip, 'download', 'submission', :o)"),
                    {"i": str(uuid.uuid4()), "a": actor, "ip": ip, "o": str(uuid.uuid4())})
            db.commit()

        body = client.get("/metrics/anomalies", headers=A).json()
        assert "submission_velocity" in body and "dispute_rate" in body
        cluster = next((c for c in body["shared_ip_clusters"] if c["ip"] == ip), None)
        assert cluster and cluster["actors"] >= 2
    finally:
        with SessionLocal() as db:
            db.execute(text("DELETE FROM audit_log WHERE ip=:ip"), {"ip": ip})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()
