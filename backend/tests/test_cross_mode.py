# tests/test_cross_mode.py
# P6b: cross-mode fulfilment — one request filled by an upload (request mode) AND a
# catalog listing, deduped across sources on the request's unique key, capped at
# target, settled per accepted record through one escrow. No record paid twice.

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

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping cross-mode test")

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


def test_request_filled_by_upload_plus_catalog_deduped():
    sx = uuid.uuid4().hex[:8]
    R = _login(f"buy_{sx}@t.io", "requester")
    P = _login(f"prov_{sx}@t.io", "provider")
    S = _login(f"sup_{sx}@t.io", "provider")
    emails = [f"buy_{sx}@t.io", f"prov_{sx}@t.io", f"sup_{sx}@t.io"]
    rid = listing_id = None
    try:
        # Funded request for 10 @ $1, unique key = id
        rid = client.post("/requests/", headers=R, json={
            "title": "blend", "unit": "row", "amount_required": 10,
            "pricing_mode": "per_unit", "price_per_unit": 1.0, "spec": SPEC,
        }).json()["id"]
        client.post(f"/requests/{rid}/fund", headers=R)

        # Mode 1 (upload): provider submits ids 1-6, buyer accepts → 6 of 10
        s1 = client.post("/submissions/", headers=P,
            files={"file": ("a.csv", _csv(range(1, 7)), "text/csv")},
            data={"request_id": rid, "offered_amount": 6, "warranted": "true"}).json()
        a1 = client.post(f"/submissions/{s1['id']}/accept", headers=R)
        assert a1.json()["request_accepted_total"] == 6

        # Mode 2 (catalog): supplier lists ids 4-13 (overlap 4,5,6)
        listing_id = client.post("/listings/", headers=S,
            files={"file": ("b.csv", _csv(range(4, 14)), "text/csv")},
            data={"title": "anchor", "price_per_unit": 0.5, "unit": "row",
                  "spec": json.dumps(SPEC), "warranted": "true"}).json()["id"]

        # Cross-mode fill: dedups 4,5,6, caps at remaining 4 → accepts 7,8,9,10
        fill = client.post(f"/requests/{rid}/fulfil-from-listing", headers=R,
                           json={"listing_id": listing_id})
        assert fill.status_code == 200, fill.text
        body = fill.json()
        assert body["source"] == "catalog"
        assert body["accepted_amount"] == 4          # only the 4 genuinely new records
        assert body["request_status"] == "completed"
        assert body["request_accepted_total"] == 10
        assert body["request_remaining"] == 0

        # No record paid twice: accepted_keys holds each of ids 1-10 exactly once
        with SessionLocal() as db:
            n = db.execute(text("SELECT count(*) FROM accepted_keys WHERE request_id=:r"), {"r": rid}).scalar()
            assert n == 10
            # the catalog fill is PAID and tagged source=catalog
            row = db.execute(text(
                "SELECT status, source, accepted_amount, amount_due, commission_amount "
                "FROM submissions WHERE id=:s"),
                {"s": body["submission_id"]}).first()
            # raw SQL returns the enum NAME (uppercase); source is a plain string
            assert row.status == "PAID" and row.source == "catalog" and row.accepted_amount == 4
            # take-rate (Phase 7): catalog = 10% of 4 × $1.00 = $0.40
            assert float(row.amount_due) == 4.0 and float(row.commission_amount) == 0.40
            # listing stock reduced by the 4 used (10 listed - 4)
            avail = db.execute(text("SELECT available_quantity FROM listings WHERE id=:l"),
                               {"l": listing_id}).scalar()
            assert avail == 6

        # Request is full now → another fill is refused
        again = client.post(f"/requests/{rid}/fulfil-from-listing", headers=R, json={"listing_id": listing_id})
        assert again.status_code == 409
    finally:
        with SessionLocal() as db:
            db.execute(text("DELETE FROM ledger WHERE request_id=:r"), {"r": rid})
            db.execute(text("DELETE FROM accepted_keys WHERE request_id=:r"), {"r": rid})
            db.execute(text("DELETE FROM submissions WHERE request_id=:r"), {"r": rid})
            if listing_id:
                db.execute(text("DELETE FROM purchases WHERE listing_id=:l"), {"l": listing_id})
                db.execute(text("DELETE FROM listings WHERE id=:l"), {"l": listing_id})
            db.execute(text("DELETE FROM data_requests WHERE id=:r"), {"r": rid})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()


def test_fill_requires_unique_key():
    sx = uuid.uuid4().hex[:8]
    R = _login(f"buy_{sx}@t.io", "requester")
    S = _login(f"sup_{sx}@t.io", "provider")
    emails = [f"buy_{sx}@t.io", f"sup_{sx}@t.io"]
    rid = listing_id = None
    try:
        # request with NO unique_key
        rid = client.post("/requests/", headers=R, json={
            "title": "nokey", "unit": "row", "amount_required": 5,
            "pricing_mode": "per_unit", "price_per_unit": 1.0,
        }).json()["id"]
        client.post(f"/requests/{rid}/fund", headers=R)
        listing_id = client.post("/listings/", headers=S,
            files={"file": ("b.csv", _csv(range(1, 6)), "text/csv")},
            data={"title": "x", "price_per_unit": 0.5, "unit": "row", "warranted": "true"}).json()["id"]
        r = client.post(f"/requests/{rid}/fulfil-from-listing", headers=R, json={"listing_id": listing_id})
        assert r.status_code == 409
    finally:
        with SessionLocal() as db:
            db.execute(text("DELETE FROM ledger WHERE request_id=:r"), {"r": rid})
            if listing_id:
                db.execute(text("DELETE FROM listings WHERE id=:l"), {"l": listing_id})
            db.execute(text("DELETE FROM data_requests WHERE id=:r"), {"r": rid})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()
