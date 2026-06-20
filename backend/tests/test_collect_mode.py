# tests/test_collect_mode.py
# P5a: Collect-mode requests carry a collection_spec (form fields + geo/photo/
# consent requirements); request mode validation.

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping collect-mode test")

client = TestClient(app)

COLLECTION_SPEC = {
    "fields": [
        {"name": "address", "type": "string", "required": True},
        {"name": "price", "type": "float", "required": True},
    ],
    "unique_key": ["address"],
    "geo_required": True,
    "photo_required": True,
    "consent_required": False,
    "coverage": ["region-A", "region-B"],
}


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_create_collect_request():
    sx = uuid.uuid4().hex[:8]
    R = _login(f"buy_{sx}@t.io", "requester")
    rid = None
    try:
        # collect mode without a spec is rejected
        bad = client.post("/requests/", headers=R, json={
            "title": "Field survey", "unit": "record", "amount_required": 50,
            "pricing_mode": "per_unit", "price_per_unit": 1.0, "mode": "collect",
        })
        assert bad.status_code == 422

        created = client.post("/requests/", headers=R, json={
            "title": "Field survey", "unit": "record", "amount_required": 50,
            "pricing_mode": "per_unit", "price_per_unit": 1.0,
            "mode": "collect", "collection_spec": COLLECTION_SPEC,
        })
        assert created.status_code == 200, created.text
        body = created.json()
        rid = body["id"]
        assert body["mode"] == "collect"
        assert body["collection_spec"]["geo_required"] is True
        assert body["collection_spec"]["unique_key"] == ["address"]

        # default mode stays "request"
        reg = client.post("/requests/", headers=R, json={
            "title": "Upload req", "unit": "row", "amount_required": 10,
            "pricing_mode": "per_unit", "price_per_unit": 1.0,
        })
        assert reg.json()["mode"] == "request"
        with SessionLocal() as db:
            db.execute(text("DELETE FROM data_requests WHERE id=:i"), {"i": reg.json()["id"]})
            db.commit()
    finally:
        with SessionLocal() as db:
            if rid:
                db.execute(text("DELETE FROM data_requests WHERE id=:i"), {"i": rid})
            db.execute(text("DELETE FROM user_auth WHERE email=:e"), {"e": f"buy_{sx}@t.io"})
            db.commit()
