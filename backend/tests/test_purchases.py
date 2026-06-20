# tests/test_purchases.py
# P4b: catalog purchase — per-record settlement through the ledger, quantity capped
# at availability, gated delivery of exactly the purchased portion.

import io
import csv
import json
import uuid
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from app.payments import purchase_balance
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping purchases test")

client = TestClient(app)
SPEC = {"columns": [{"name": "id", "type": "integer", "required": True},
                    {"name": "value", "type": "string", "required": True}], "unique_key": ["id"]}


def _csv(n):
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(["id", "value"])
    for i in range(1, n + 1):
        w.writerow([i, f"v{i}"])
    return buf.getvalue().encode()


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_purchase_settles_caps_and_delivers_portion():
    sx = uuid.uuid4().hex[:8]
    P = _login(f"sup_{sx}@t.io", "provider")
    B = _login(f"buy_{sx}@t.io", "requester")
    emails = [f"sup_{sx}@t.io", f"buy_{sx}@t.io"]
    listing_id = None
    purchase_ids = []
    try:
        created = client.post("/listings/", headers=P,
            files={"file": ("d.csv", _csv(10), "text/csv")},
            data={"title": "Anchor", "price_per_unit": 3.0, "unit": "row",
                  "spec": json.dumps(SPEC), "warranted": "true"})
        listing_id = created.json()["id"]

        # Provider cannot buy; quantity must be positive
        assert client.post(f"/listings/{listing_id}/purchase", headers=P, json={"quantity": 1}).status_code == 403
        assert client.post(f"/listings/{listing_id}/purchase", headers=B, json={"quantity": 0}).status_code == 422

        # Buy 4 of 10 → settles 4 × $3 = $12; 6 remain
        r1 = client.post(f"/listings/{listing_id}/purchase", headers=B, json={"quantity": 4})
        assert r1.status_code == 200, r1.text
        body = r1.json()
        purchase_ids.append(body["purchase"]["id"])
        assert body["purchase"]["quantity"] == 4
        assert body["purchase"]["amount"] == 12.0
        assert body["purchase"]["status"] == "paid"
        assert body["remaining_in_listing"] == 6

        # Ledger invariant for the purchase: held == released, remaining 0
        with SessionLocal() as db:
            bal = purchase_balance(db, purchase_ids[0])
            assert bal["held"] == bal["released"] == Decimal("12.00")
            assert bal["remaining"] == Decimal("0")

        # Gated delivery: buyer downloads exactly 4 records (sliced)
        dl = client.get(f"/purchases/{purchase_ids[0]}/download", headers=B)
        assert dl.status_code == 200
        assert dl.json()["quantity"] == 4

        # Another buyer can't download someone else's purchase (404, no leak)
        O = _login(f"other_{sx}@t.io", "requester")
        emails.append(f"other_{sx}@t.io")
        assert client.get(f"/purchases/{purchase_ids[0]}/download", headers=O).status_code == 404

        # Over-buy the rest: ask for 100, capped to remaining 6 → sold out
        r2 = client.post(f"/listings/{listing_id}/purchase", headers=B, json={"quantity": 100})
        assert r2.status_code == 200, r2.text
        purchase_ids.append(r2.json()["purchase"]["id"])
        assert r2.json()["purchase"]["quantity"] == 6
        assert r2.json()["remaining_in_listing"] == 0

        # Listing now sold out → hidden from catalog + further purchase 409
        assert all(x["id"] != listing_id for x in client.get("/listings/").json())
        assert client.post(f"/listings/{listing_id}/purchase", headers=B, json={"quantity": 1}).status_code == 409

        # my purchases lists both
        mine = client.get("/purchases/", headers=B).json()
        assert len(mine) >= 2
    finally:
        with SessionLocal() as db:
            for pid in purchase_ids:
                db.execute(text("DELETE FROM ledger WHERE purchase_id=:p"), {"p": pid})
            db.execute(text("DELETE FROM purchases WHERE listing_id=:l"), {"l": listing_id})
            if listing_id:
                db.execute(text("DELETE FROM listings WHERE id=:l"), {"l": listing_id})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()
