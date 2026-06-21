# tests/test_manifest.py
# P8a: every delivered dataset carries a compliance manifest — source + license
# (name/terms) + provenance + (where personal) consent basis.

import io
import csv
import json
import uuid
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping manifest test")

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


def _make_license(name, terms):
    lid = str(uuid.uuid4())
    with SessionLocal() as db:
        db.execute(text(
            "INSERT INTO licenses (id, name, terms, created_at, is_deleted, version) "
            "VALUES (:i, :n, :t, now(), false, 1)"), {"i": lid, "n": name, "t": terms})
        db.commit()
    return lid


def test_manifest_carries_license_and_source():
    sx = uuid.uuid4().hex[:8]
    R = _login(f"buy_{sx}@t.io", "requester")
    P = _login(f"prov_{sx}@t.io", "provider")
    S = _login(f"sup_{sx}@t.io", "provider")
    emails = [f"buy_{sx}@t.io", f"prov_{sx}@t.io", f"sup_{sx}@t.io"]
    lid = _make_license(f"CC-BY-{sx}", "Attribution required.")
    rid = listing_id = s1 = None
    pid = None
    try:
        # Request with a license, filled by an upload
        rid = client.post("/requests/", headers=R, json={
            "title": "m", "unit": "row", "amount_required": 5, "license_id": lid,
            "pricing_mode": "per_unit", "price_per_unit": 1.0, "spec": SPEC,
        }).json()["id"]
        client.post(f"/requests/{rid}/fund", headers=R)
        s1 = client.post("/submissions/", headers=P,
            files={"file": ("a.csv", _csv(range(1, 6)), "text/csv")},
            data={"request_id": rid, "offered_amount": 5, "warranted": "true"}).json()["id"]
        client.post(f"/submissions/{s1}/accept", headers=R)

        man = client.get(f"/submissions/{s1}/manifest", headers=R)
        assert man.status_code == 200, man.text
        m = man.json()
        assert m["source"] == "request"
        assert m["license"]["name"] == f"CC-BY-{sx}"
        assert m["license"]["terms"] == "Attribution required."
        assert m["record_count"] == 5

        # A stranger can't read the manifest
        O = _login(f"other_{sx}@t.io", "requester")
        emails.append(f"other_{sx}@t.io")
        assert client.get(f"/submissions/{s1}/manifest", headers=O).status_code == 404

        # Catalog purchase carries the listing's license + source=catalog
        listing_id = client.post("/listings/", headers=S,
            files={"file": ("b.csv", _csv(range(1, 9)), "text/csv")},
            data={"title": "anchor", "price_per_unit": 1.0, "unit": "row",
                  "license_id": lid, "provenance": "first-party",
                  "spec": json.dumps(SPEC), "warranted": "true"}).json()["id"]
        pid = client.post(f"/listings/{listing_id}/purchase", headers=R, json={"quantity": 3}).json()["purchase"]["id"]
        pm = client.get(f"/purchases/{pid}/manifest", headers=R).json()
        assert pm["source"] == "catalog"
        assert pm["license"]["name"] == f"CC-BY-{sx}"
        assert pm["provenance"] == "first-party"
        assert pm["record_count"] == 3
    finally:
        with SessionLocal() as db:
            db.execute(text("DELETE FROM ledger WHERE request_id=:r"), {"r": rid})
            db.execute(text("DELETE FROM accepted_keys WHERE request_id=:r"), {"r": rid})
            db.execute(text("DELETE FROM submissions WHERE request_id=:r"), {"r": rid})
            if pid:
                db.execute(text("DELETE FROM ledger WHERE purchase_id=:p"), {"p": pid})
                db.execute(text("DELETE FROM purchases WHERE id=:p"), {"p": pid})
            if listing_id:
                db.execute(text("DELETE FROM listings WHERE id=:l"), {"l": listing_id})
            db.execute(text("DELETE FROM data_requests WHERE id=:r"), {"r": rid})
            db.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            db.execute(text("DELETE FROM licenses WHERE id=:i"), {"i": lid})
            db.commit()
