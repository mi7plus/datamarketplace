# tests/test_collect_dispatch.py
# P5b: org accepts a funded collect request; agents submit entries validated
# against the form spec + geo/photo/consent QA gates.

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping collect dispatch test")

client = TestClient(app)

SPEC = {
    "fields": [
        {"name": "address", "type": "string", "required": True},
        {"name": "price", "type": "float", "required": True},
    ],
    "unique_key": ["address"],
    "geo_required": True, "photo_required": True, "consent_required": False,
}


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _funded_collect_request(R):
    created = client.post("/requests/", headers=R, json={
        "title": "Field survey", "unit": "record", "amount_required": 50,
        "pricing_mode": "per_unit", "price_per_unit": 1.0,
        "mode": "collect", "collection_spec": SPEC,
    }).json()
    client.post(f"/requests/{created['id']}/fund", headers=R)
    return created["id"]


def test_dispatch_and_entry_qa():
    sx = uuid.uuid4().hex[:8]
    R = _login(f"buy_{sx}@t.io", "requester")
    ORG = _login(f"org_{sx}@t.io", "provider")
    emails = [f"buy_{sx}@t.io", f"org_{sx}@t.io"]
    rid = did = None
    try:
        rid = _funded_collect_request(R)

        # Requester can't accept a collection; org can
        assert client.post("/collect/dispatches", headers=R, json={"request_id": rid}).status_code == 403
        disp = client.post("/collect/dispatches", headers=ORG, json={"request_id": rid})
        assert disp.status_code == 200, disp.text
        did = disp.json()["id"]

        # Valid entry (all fields + geo + photo)
        ok = client.post(f"/collect/dispatches/{did}/entries", headers=ORG, json={
            "data": {"address": "1 Main St", "price": "250000"},
            "geo_lat": 51.5, "geo_lng": -0.1, "photo_ref": "ph-1",
            "contributor_ref": "agent-7",
        })
        assert ok.status_code == 200 and ok.json()["status"] == "valid", ok.text

        # Missing photo → rejected by QA gate
        nophoto = client.post(f"/collect/dispatches/{did}/entries", headers=ORG, json={
            "data": {"address": "2 Main St", "price": "300000"},
            "geo_lat": 51.5, "geo_lng": -0.1,
        })
        assert nophoto.json()["status"] == "rejected"
        assert any("photo" in e for e in nophoto.json()["validation_errors"])

        # Bad type + missing geo → rejected with multiple errors
        bad = client.post(f"/collect/dispatches/{did}/entries", headers=ORG, json={
            "data": {"address": "3 Main St", "price": "not-a-number"},
            "photo_ref": "ph-3",
        })
        assert bad.json()["status"] == "rejected"
        errs = bad.json()["validation_errors"]
        assert any("price" in e for e in errs) and any("geo" in e for e in errs)

        # Dispatch counts: 3 total, 1 valid
        d = client.get(f"/collect/dispatches/{did}", headers=ORG).json()
        assert d["entries_total"] == 3 and d["entries_valid"] == 1

        # A stranger org cannot read the dispatch
        OTHER = _login(f"other_{sx}@t.io", "provider")
        emails.append(f"other_{sx}@t.io")
        assert client.get(f"/collect/dispatches/{did}", headers=OTHER).status_code == 404
    finally:
        with SessionLocal() as db:
            if did:
                db.execute(text("DELETE FROM collection_entries WHERE dispatch_id=:d"), {"d": did})
                db.execute(text("DELETE FROM collection_dispatches WHERE id=:d"), {"d": did})
            if rid:
                db.execute(text("DELETE FROM ledger WHERE request_id=:r"), {"r": rid})
                db.execute(text("DELETE FROM data_requests WHERE id=:r"), {"r": rid})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()


def test_finalize_compiles_dedups_and_settles():
    """P5c: finalize compiles valid+deduped entries into a Submission that the buyer
    accepts through the same engine."""
    sx = uuid.uuid4().hex[:8]
    R = _login(f"buy_{sx}@t.io", "requester")
    ORG = _login(f"org_{sx}@t.io", "provider")
    emails = [f"buy_{sx}@t.io", f"org_{sx}@t.io"]
    rid = did = sub_id = None
    try:
        rid = _funded_collect_request(R)
        did = client.post("/collect/dispatches", headers=ORG, json={"request_id": rid}).json()["id"]

        def _entry(addr, price):
            return client.post(f"/collect/dispatches/{did}/entries", headers=ORG, json={
                "data": {"address": addr, "price": price},
                "geo_lat": 51.5, "geo_lng": -0.1, "photo_ref": "ph",
                "consent_basis": "opt-in", "lawful_basis": "consent",
            })
        # 3 valid entries, one a duplicate address (dedup key) → 2 unique
        _entry("1 Main St", "100")
        _entry("2 Main St", "200")
        _entry("1 Main St", "150")     # duplicate key
        # 1 invalid (missing photo) — must be excluded
        client.post(f"/collect/dispatches/{did}/entries", headers=ORG, json={
            "data": {"address": "3 Main St", "price": "300"}, "geo_lat": 51.5, "geo_lng": -0.1})

        fin = client.post(f"/collect/dispatches/{did}/finalize", headers=ORG)
        assert fin.status_code == 200, fin.text
        body = fin.json()
        assert body["validated_amount"] == 2          # deduped, valid only
        assert body["deduplicated"] == 1
        assert body["submission_status"] == "validated"
        sub_id = body["submission_id"]

        # Buyer sees it in their review list and accepts → settles through the engine
        subs = client.get(f"/submissions/request/{rid}", headers=R).json()
        assert any(s["id"] == sub_id for s in subs)
        acc = client.post(f"/submissions/{sub_id}/accept", headers=R)
        assert acc.status_code == 200, acc.text
        assert acc.json()["submission"]["accepted_amount"] == 2
        assert acc.json()["request_accepted_total"] == 2

        # Re-finalize is blocked (dispatch now finalized)
        assert client.post(f"/collect/dispatches/{did}/finalize", headers=ORG).status_code == 409
    finally:
        with SessionLocal() as db:
            if rid:
                db.execute(text("DELETE FROM ledger WHERE request_id=:r"), {"r": rid})
            if did:
                db.execute(text("DELETE FROM collection_entries WHERE dispatch_id=:d"), {"d": did})
                db.execute(text("DELETE FROM collection_dispatches WHERE id=:d"), {"d": did})
            if sub_id:
                db.execute(text("DELETE FROM accepted_keys WHERE request_id=:r"), {"r": rid})
                db.execute(text("DELETE FROM submissions WHERE id=:s"), {"s": sub_id})
            if rid:
                db.execute(text("DELETE FROM data_requests WHERE id=:r"), {"r": rid})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.commit()
