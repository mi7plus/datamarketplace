# tests/test_metrics.py
# P7b: beachhead metrics — admin-only; fill rate, GMV, take, cross-mode, repeat
# buyer, per-category breakdown.

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

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping metrics test")

client = TestClient(app)
SPEC = {"columns": [{"name": "id", "type": "integer", "required": True},
                    {"name": "value", "type": "string", "required": True}], "unique_key": ["id"]}


def _csv(ids):
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(["id", "value"])
    for i in ids:
        w.writerow([i, f"v{i}"])
    return buf.getvalue().encode()


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_beachhead_admin_only_and_aggregates():
    sx = uuid.uuid4().hex[:8]
    cat = f"vert_{sx}"
    R = _login(f"buy_{sx}@t.io", "requester")
    S = _login(f"sup_{sx}@t.io", "provider")
    A = _login(f"adm_{sx}@t.io", "admin")
    emails = [f"buy_{sx}@t.io", f"sup_{sx}@t.io", f"adm_{sx}@t.io"]
    rid = listing_id = None
    try:
        # non-admin is forbidden
        assert client.get("/metrics/beachhead", headers=R).status_code == 403

        # A funded request in our category, filled fully from the catalog (cross-... single mode here)
        rid = client.post("/requests/", headers=R, json={
            "title": "m", "unit": "row", "amount_required": 5, "category": cat,
            "pricing_mode": "per_unit", "price_per_unit": 2.0, "spec": SPEC,
        }).json()["id"]
        client.post(f"/requests/{rid}/fund", headers=R)
        listing_id = client.post("/listings/", headers=S,
            files={"file": ("b.csv", _csv(range(1, 6)), "text/csv")},
            data={"title": "anchor", "price_per_unit": 1.0, "unit": "row",
                  "spec": json.dumps(SPEC), "warranted": "true"}).json()["id"]
        fill = client.post(f"/requests/{rid}/fulfil-from-listing", headers=R, json={"listing_id": listing_id})
        assert fill.status_code == 200, fill.text

        # Scoped to our category: 5/5 filled, GMV = 5×$2 = 10, take = 10% (catalog) = 1.00
        m = client.get(f"/metrics/beachhead?category={cat}", headers=A).json()
        assert m["requests"]["total"] == 1
        assert m["fill_rate"] == 1.0
        assert float(m["gmv"]) >= 10.0
        assert float(m["take"]) >= 1.0
        assert m["buyers"] == 1
    finally:
        with SessionLocal() as db:
            db.execute(text("DELETE FROM ledger WHERE request_id=:r"), {"r": rid})
            db.execute(text("DELETE FROM accepted_keys WHERE request_id=:r"), {"r": rid})
            db.execute(text("DELETE FROM submissions WHERE request_id=:r"), {"r": rid})
            if listing_id:
                db.execute(text("DELETE FROM listings WHERE id=:l"), {"l": listing_id})
            db.execute(text("DELETE FROM data_requests WHERE id=:r"), {"r": rid})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()
