# tests/test_audit.py
# H2 (S6): money/file events land in the append-only audit log; admin can read it.

import io
import csv
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping audit test")

client = TestClient(app)
SPEC = {"columns": [{"name": "id", "type": "integer", "required": True}], "unique_key": ["id"]}


def _csv(ids):
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(["id"])
    for i in ids:
        w.writerow([i])
    return buf.getvalue().encode()


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_purchase_and_takedown_are_audited():
    sx = uuid.uuid4().hex[:8]
    S = _login(f"sup_{sx}@t.io", "provider")
    B = _login(f"buy_{sx}@t.io", "requester")
    A = _login(f"adm_{sx}@t.io", "admin")
    emails = [f"sup_{sx}@t.io", f"buy_{sx}@t.io", f"adm_{sx}@t.io"]
    listing_id = pid = None
    try:
        listing_id = client.post("/listings/", headers=S,
            files={"file": ("b.csv", _csv(range(1, 11)), "text/csv")},
            data={"title": "anchor", "price_per_unit": 1.0, "unit": "row",
                  "spec": json.dumps(SPEC), "warranted": "true"}).json()["id"]
        pid = client.post(f"/listings/{listing_id}/purchase", headers=B, json={"quantity": 2}).json()["purchase"]["id"]
        client.get(f"/purchases/{pid}/download", headers=B)            # downloads aren't audited here, purchase is
        client.post(f"/listings/{listing_id}/takedown", headers=A)

        # audit log is admin-only
        assert client.get("/metrics/audit", headers=B).status_code == 403

        purchases_log = client.get("/metrics/audit?action=purchase", headers=A).json()
        assert any(e["object_id"] == pid for e in purchases_log)

        takedowns = client.get("/metrics/audit?action=takedown", headers=A).json()
        assert any(e["object_id"] == listing_id for e in takedowns)
        # entries carry actor + timestamp
        e = next(e for e in takedowns if e["object_id"] == listing_id)
        assert e["actor_id"] and e["created_at"]
    finally:
        with SessionLocal() as db:
            if pid:
                db.execute(text("DELETE FROM audit_log WHERE object_id IN (:p, :l)"),
                           {"p": pid, "l": listing_id})
                db.execute(text("DELETE FROM ledger WHERE purchase_id=:p"), {"p": pid})
                db.execute(text("DELETE FROM purchases WHERE id=:p"), {"p": pid})
            if listing_id:
                db.execute(text("DELETE FROM listings WHERE id=:l"), {"l": listing_id})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()
