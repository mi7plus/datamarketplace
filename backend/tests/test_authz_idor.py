# tests/test_authz_idor.py
#
# S1 — object-level authorization / IDOR.
# User B attempts EVERY object action on user A's request and submission and must
# be refused (404 on ownership miss — no existence leak; 403 on role miss). Also
# checks the crown jewel: full-file download is owner-scoped and PAID/ACCEPTED-gated.
#
# Real Postgres via conftest. Repeatable: unique emails + ordered cleanup.

import io
import csv
import uuid
import pytest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal

from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping IDOR test",
)

client = TestClient(app)


def _csv(ids):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "value"])
    for i in ids:
        w.writerow([i, f"v{i}"])
    return buf.getvalue().encode()


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _uid(db, email):
    return db.execute(text("SELECT id FROM user_auth WHERE email = :e"), {"e": email}).scalar()


def test_user_b_cannot_touch_user_a_objects():
    sfx = uuid.uuid4().hex[:8]
    emails = {
        "A": f"a_{sfx}@t.io", "PA": f"pa_{sfx}@t.io",
        "B": f"b_{sfx}@t.io", "PB": f"pb_{sfx}@t.io",
    }
    A = _login(emails["A"], "requester")
    PA = _login(emails["PA"], "provider")
    B = _login(emails["B"], "requester")     # attacker (requester)
    PB = _login(emails["PB"], "provider")    # attacker (provider)

    db = SessionLocal()
    rid = None
    sub_ids = []
    try:
        # A creates + funds a request
        rid = client.post("/requests/", headers=A, json={
            "title": "ids", "unit": "row", "amount_required": 100,
            "pricing_mode": "per_unit", "price_per_unit": 1.0, "budget": 100.0,
            "required_format": "csv",
            "spec": {"columns": [
                {"name": "id", "type": "integer", "required": True},
                {"name": "value", "type": "string", "required": True}],
                "unique_key": ["id"]},
            "deadline": (datetime.utcnow() + timedelta(days=7)).isoformat(),
        }).json()["id"]
        assert client.post(f"/requests/{rid}/fund", headers=A).status_code == 200

        # P_A submits two datasets; A accepts the first (-> ACCEPTED), leaves 2nd VALIDATED
        s1 = client.post("/submissions/", headers=PA,
            files={"file": ("a.csv", _csv(range(1, 6)), "text/csv")},
            data={"request_id": rid, "offered_amount": 5, "warranted": "true"}).json()["id"]
        s2 = client.post("/submissions/", headers=PA,
            files={"file": ("b.csv", _csv(range(50, 55)), "text/csv")},
            data={"request_id": rid, "offered_amount": 5, "warranted": "true"}).json()["id"]
        sub_ids = [s1, s2]
        assert client.post(f"/submissions/{s1}/accept", headers=A).status_code == 200

        # ---- B (requester, not the owner) is refused on every object action: 404 ----
        assert client.post(f"/requests/{rid}/fund", headers=B).status_code == 404
        assert client.post(f"/requests/{rid}/close", headers=B).status_code == 404
        assert client.get(f"/requests/{rid}/ledger", headers=B).status_code == 404
        assert client.post(f"/submissions/{s1}/accept", headers=B).status_code == 404
        assert client.post(f"/submissions/{s1}/confirm", headers=B).status_code == 404
        assert client.post(f"/submissions/{s2}/reject", headers=B).status_code == 404
        assert client.get(f"/submissions/{s1}/download", headers=B).status_code == 404
        assert client.get(f"/submissions/{s1}/sample", headers=B).status_code == 404
        assert client.post(f"/disputes/{s1}/open", headers=B, json={"reason": "x"}).status_code == 404
        assert client.get(f"/disputes/{s1}", headers=B).status_code == 404

        # ---- P_B (provider, not THIS submission's provider) refused: 404 ----
        assert client.post(f"/submissions/{s1}/claim", headers=PB).status_code == 404
        assert client.get(f"/submissions/{s1}/sample", headers=PB).status_code == 404

        # ---- Role gates (403 — role denial doesn't leak a specific object) ----
        # A requester cannot upload a submission
        up = client.post("/submissions/", headers=B,
            files={"file": ("c.csv", _csv(range(1, 3)), "text/csv")},
            data={"request_id": rid, "offered_amount": 2, "warranted": "true"})
        assert up.status_code == 403, up.text
        # Non-admin cannot resolve disputes / list disputes / takedown
        assert client.post(f"/disputes/{s1}/resolve", headers=A, json={"outcome": "paid"}).status_code == 403
        assert client.get("/disputes/", headers=A).status_code == 403
        assert client.post(f"/submissions/{s1}/takedown", headers=A).status_code == 403

        # ---- Crown jewel: download is owner-scoped AND status-gated ----
        # The owner A can NOT download a non-PAID/non-ACCEPTED (VALIDATED) submission
        assert client.get(f"/submissions/{s2}/download", headers=A).status_code == 403
        # The owner A CAN see the ledger and sample (positive control — not over-locked)
        assert client.get(f"/requests/{rid}/ledger", headers=A).status_code == 200
        assert client.get(f"/submissions/{s1}/sample", headers=A).status_code == 200

    finally:
        uids = [str(_uid(db, e)) for e in emails.values()]
        db.execute(text("DELETE FROM reviews WHERE request_id = :rid"), {"rid": rid})
        db.execute(text("DELETE FROM disputes WHERE submission_id::text = ANY(:s)"), {"s": sub_ids})
        db.execute(text("DELETE FROM accepted_keys WHERE request_id = :rid"), {"rid": rid})
        db.execute(text("DELETE FROM ledger WHERE request_id = :rid"), {"rid": rid})
        db.execute(text("DELETE FROM submissions WHERE request_id = :rid"), {"rid": rid})
        db.execute(text("DELETE FROM data_requests WHERE id = :rid"), {"rid": rid})
        db.execute(text("DELETE FROM user_analytics WHERE user_id::text = ANY(:u)"), {"u": uids})
        db.execute(text("DELETE FROM user_auth WHERE id::text = ANY(:u)"), {"u": uids})
        db.commit()
        db.close()


def test_unauthenticated_is_rejected():
    # No token at all → 401 on protected object routes
    fake = str(uuid.uuid4())
    assert client.get(f"/requests/{fake}/ledger").status_code in (401, 403)
    assert client.post(f"/submissions/{fake}/accept").status_code in (401, 403)
