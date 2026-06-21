# tests/test_concierge.py
# P7c: concierge + leakage tooling — admin-only; under-filled requests, catalog
# seeding, leakage signals.

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping concierge test")

client = TestClient(app)
SPEC = {"columns": [{"name": "id", "type": "integer", "required": True}], "unique_key": ["id"]}


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_concierge_and_leakage_admin_only():
    sx = uuid.uuid4().hex[:8]
    R = _login(f"buy_{sx}@t.io", "requester")
    A = _login(f"adm_{sx}@t.io", "admin")
    emails = [f"buy_{sx}@t.io", f"adm_{sx}@t.io"]
    seed_email = f"seedsup_{sx}@rowbound.local"
    emails.append(seed_email)
    rid = None
    try:
        # under-filled requires admin
        assert client.get("/metrics/concierge/under-filled", headers=R).status_code == 403

        # A funded, unfilled request shows up as under-filled
        rid = client.post("/requests/", headers=R, json={
            "title": f"uf_{sx}", "unit": "row", "amount_required": 10,
            "pricing_mode": "per_unit", "price_per_unit": 1.0, "spec": SPEC,
        }).json()["id"]
        client.post(f"/requests/{rid}/fund", headers=R)

        uf = client.get("/metrics/concierge/under-filled", headers=A).json()
        mine = next((x for x in uf if x["id"] == rid), None)
        assert mine and mine["remaining"] == 10 and mine["fill_rate"] == 0.0

        # Catalog seeding (admin) creates anchor listings
        seeded = client.post(f"/metrics/concierge/seed-catalog?supplier_email={seed_email}", headers=A)
        assert seeded.status_code == 200
        assert seeded.json()["seeded"] >= 1
        assert any(x["id"] for x in client.get("/listings/").json())   # catalog now non-empty

        # leakage endpoint is admin-only and returns the two signal buckets
        assert client.get("/metrics/leakage", headers=R).status_code == 403
        lk = client.get("/metrics/leakage", headers=A).json()
        assert "funded_then_expired" in lk and "reviewed_not_accepted" in lk
    finally:
        with SessionLocal() as db:
            db.execute(text("DELETE FROM ledger WHERE request_id=:r"), {"r": rid})
            db.execute(text("DELETE FROM data_requests WHERE id=:r"), {"r": rid})
            # clean seeded listings + seed supplier
            sup = db.execute(text("SELECT id FROM user_auth WHERE email=:e"), {"e": seed_email}).scalar()
            if sup:
                db.execute(text("DELETE FROM listings WHERE supplier_id=:s"), {"s": str(sup)})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()
