# tests/test_listings.py
# P4a: catalog listings — supplier lists a dataset (reusing ingest/validation),
# buyers browse + preview sample. PII high-risk auto-quarantines (hidden from catalog).

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

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping listings test")

client = TestClient(app)

SPEC = {"columns": [{"name": "id", "type": "integer", "required": True},
                    {"name": "value", "type": "string", "required": True}],
        "unique_key": ["id"]}


def _csv(rows):
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(["id", "value"])
    for i, v in rows:
        w.writerow([i, v])
    return buf.getvalue().encode()


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _list(headers, rows, price=2.0, warranted="true"):
    return client.post("/listings/", headers=headers,
        files={"file": ("d.csv", _csv(rows), "text/csv")},
        data={"title": "Anchor set", "price_per_unit": price, "unit": "row",
              "provenance": "first-party CRM export", "spec": json.dumps(SPEC),
              "warranted": warranted})


def test_list_browse_and_sample():
    suffix = uuid.uuid4().hex[:8]
    P = _login(f"sup_{suffix}@t.io", "provider")
    R = _login(f"buy_{suffix}@t.io", "requester")
    emails = [f"sup_{suffix}@t.io", f"buy_{suffix}@t.io"]
    listing_id = None
    try:
        # requester cannot list
        assert _list(R, [(1, "a")]).status_code == 403
        # missing warranty rejected
        assert _list(P, [(1, "a")], warranted="false").status_code == 422

        created = _list(P, [(i, f"v{i}") for i in range(1, 21)], price=2.0)
        assert created.status_code == 200, created.text
        body = created.json()
        listing_id = body["id"]
        assert body["validated_amount"] == 20
        assert body["available_quantity"] == 20
        assert body["price_per_unit"] == 2.0
        assert body["provenance"] == "first-party CRM export"

        # public browse shows it
        catalog = client.get("/listings/").json()
        assert any(x["id"] == listing_id for x in catalog)

        # sample preview available pre-purchase
        sample = client.get(f"/listings/{listing_id}/sample").json()
        assert sample["sample_count"] > 0

        # detail carries license/provenance/spec
        detail = client.get(f"/listings/{listing_id}").json()
        assert detail["spec"]["unique_key"] == ["id"]
    finally:
        with SessionLocal() as db:
            if listing_id:
                db.execute(text("DELETE FROM listings WHERE id=:i"), {"i": listing_id})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()


def test_high_pii_listing_is_quarantined_and_hidden():
    suffix = uuid.uuid4().hex[:8]
    P = _login(f"sup_{suffix}@t.io", "provider")
    listing_id = None
    try:
        # pervasive emails → high PII risk → quarantined
        rows = [(i, f"user{i}@example.com") for i in range(1, 13)]
        created = _list(P, rows)
        assert created.status_code == 200, created.text
        listing_id = created.json()["id"]
        assert created.json()["quarantined"] is True
        # hidden from public catalog
        assert all(x["id"] != listing_id for x in client.get("/listings/").json())
    finally:
        with SessionLocal() as db:
            if listing_id:
                db.execute(text("DELETE FROM listings WHERE id=:i"), {"i": listing_id})
            db.execute(text("DELETE FROM user_auth WHERE email=:e"), {"e": f"sup_{suffix}@t.io"})
            db.commit()
