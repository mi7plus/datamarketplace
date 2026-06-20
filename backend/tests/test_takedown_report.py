# tests/test_takedown_report.py
# S4b: reporter flow quarantines a dataset (blocks delivery); admin takedown
# revokes access (gate + token + soft-delete); admin can clear a quarantine.

import io
import csv
import uuid
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from app.models import Submission, SubmissionStatus

from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(
    DB_URL is None, reason="POSTGRES_* not set — skipping takedown/report test",
)

client = TestClient(app)


def _csv(ids):
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(["id", "value"])
    for i in ids:
        w.writerow([i, f"v{i}"])
    return buf.getvalue().encode()


def _login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _uid(db, email):
    return str(db.execute(text("SELECT id FROM user_auth WHERE email=:e"), {"e": email}).scalar())


def _make_paid_submission(db, rid, sid, requester_id, provider_id):
    """Seed a request + a PAID submission directly so download is allowed."""
    db.execute(text("""
        INSERT INTO data_requests (id,title,status,budget,price_per_unit,pricing_mode,
            amount_required,accepted_total,unit,requester_id,created_at,is_deleted,version)
        VALUES (:rid,'t','PARTIALLY_FULFILLED',100,1.0,'PER_UNIT',100,5,'row',:req,now(),false,1)
    """), {"rid": rid, "req": requester_id})
    db.execute(text("""
        INSERT INTO submissions (id,request_id,provider_id,status,validated_amount,offered_amount,
            accepted_amount,amount_due,content_link,storage_location,quarantined,
            created_at,is_deleted,version)
        VALUES (:sid,:rid,:prov,'PAID',5,5,5,5.0,'d.csv','k',false,now(),false,1)
    """), {"sid": sid, "rid": rid, "prov": provider_id})
    db.commit()


def test_report_quarantines_and_takedown_revokes():
    suffix = uuid.uuid4().hex[:8]
    R = _login(f"r_{suffix}@t.io", "requester")
    P = _login(f"p_{suffix}@t.io", "provider")
    A = _login(f"a_{suffix}@t.io", "admin")

    db = SessionLocal()
    rid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    emails = [f"r_{suffix}@t.io", f"p_{suffix}@t.io", f"a_{suffix}@t.io"]
    try:
        req_id = _uid(db, emails[0]); prov_id = _uid(db, emails[1])
        _make_paid_submission(db, rid, sid, req_id, prov_id)

        # Buyer can download the PAID submission
        assert client.get(f"/submissions/{sid}/download", headers=R).status_code == 200

        # Provider cannot report their own submission
        assert client.post(f"/submissions/{sid}/report", headers=P,
                           data={"reason": "x"}).status_code == 403

        # Buyer reports it → quarantined; download now blocked (403)
        rep = client.post(f"/submissions/{sid}/report", headers=R, data={"reason": "looks like scraped PII"})
        assert rep.status_code == 200, rep.text
        with SessionLocal() as s:
            assert s.get(Submission, sid).quarantined is True
        assert client.get(f"/submissions/{sid}/download", headers=R).status_code == 403

        # Duplicate report from same reporter → 409
        assert client.post(f"/submissions/{sid}/report", headers=R, data={"reason": "again"}).status_code == 409

        # Admin clears the quarantine → download works again
        assert client.post(f"/submissions/{sid}/unquarantine", headers=A).status_code == 200
        assert client.get(f"/submissions/{sid}/download", headers=R).status_code == 200

        # Admin takedown → token rotated, gate expired, soft-deleted → unreachable (404)
        with SessionLocal() as s:
            tok_before = s.get(Submission, sid).access_token_id
        assert client.post(f"/submissions/{sid}/takedown", headers=A).status_code == 200
        with SessionLocal() as s:
            sub = s.get(Submission, sid)
            assert sub.is_deleted is True
            assert sub.quarantined is True
            assert sub.access_token_id != tok_before     # token revoked
            assert sub.access_expiry <= datetime.utcnow()
        # Download endpoint can no longer find it
        assert client.get(f"/submissions/{sid}/download", headers=R).status_code == 404
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM submission_flags WHERE submission_id=:sid"), {"sid": sid})
            s.execute(text("DELETE FROM submissions WHERE id=:sid"), {"sid": sid})
            s.execute(text("DELETE FROM data_requests WHERE id=:rid"), {"rid": rid})
            s.execute(text("DELETE FROM user_auth WHERE email = ANY(:e)"), {"e": emails})
            s.commit()
        db.close()
