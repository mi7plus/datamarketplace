# tests/test_listing_takedown.py
# P8b: admin takedown makes a catalog dataset unreachable across browse, purchase,
# cross-mode fill, and already-purchased download.

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

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping listing takedown test")

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


def test_listing_takedown_makes_it_unreachable():
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
        # buyer purchases some before takedown
        pid = client.post(f"/listings/{listing_id}/purchase", headers=B, json={"quantity": 2}).json()["purchase"]["id"]
        assert client.get(f"/purchases/{pid}/download", headers=B).status_code == 200

        # non-admin cannot take down
        assert client.post(f"/listings/{listing_id}/takedown", headers=S).status_code == 403
        # admin takedown
        assert client.post(f"/listings/{listing_id}/takedown", headers=A).status_code == 200

        # gone from catalog, no new purchase, existing download revoked (410)
        assert all(x["id"] != listing_id for x in client.get("/listings/").json())
        assert client.post(f"/listings/{listing_id}/purchase", headers=B, json={"quantity": 1}).status_code == 409
        assert client.get(f"/purchases/{pid}/download", headers=B).status_code == 410
    finally:
        with SessionLocal() as db:
            if pid:
                db.execute(text("DELETE FROM ledger WHERE purchase_id=:p"), {"p": pid})
                db.execute(text("DELETE FROM purchases WHERE id=:p"), {"p": pid})
            if listing_id:
                db.execute(text("DELETE FROM purchases WHERE listing_id=:l"), {"l": listing_id})
                db.execute(text("DELETE FROM listings WHERE id=:l"), {"l": listing_id})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()
