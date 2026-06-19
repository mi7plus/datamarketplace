# backend/tests/test_e2e_full_loop.py
#
# End-to-end acceptance gate for the whole core loop, driven through the real
# routers against live Postgres + LocalStorage + FakePaymentProvider (all defaults).
#
# Exercises together: spec -> escrow hold -> ingest/validation -> capped allocation
# -> cross-provider dedup (F7) -> window/sweep release (F8/F9) -> release-path lock
# (F10) -> ledger integrity -> gated download -> review.
#
# Requires a live Postgres (conftest.py loads backend/.env). Skips otherwise.
# Repeatable: unique emails per run + explicit ordered cleanup of every row created.

import io
import csv
import uuid
import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from app.models import Submission, SubmissionStatus, RequestStatus
from app.payments import ledger_balance
from app.submissions import run_auto_release_sweep

from tests.test_allocation_race import DB_URL  # reuse skip logic

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping E2E loop test",
)

client = TestClient(app)


def _csv(ids):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "value"])
    for i in ids:
        w.writerow([i, f"v{i}"])
    return buf.getvalue().encode()


def _register_login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user_id(db, email):
    return db.execute(text("SELECT id FROM user_auth WHERE email = :e"), {"e": email}).scalar()


def _cleanup(db, rid, sub_ids, emails):
    uids = [str(_user_id(db, e)) for e in emails]
    db.execute(text("DELETE FROM reviews WHERE request_id = :rid"), {"rid": rid})
    db.execute(text("DELETE FROM accepted_keys WHERE request_id = :rid"), {"rid": rid})
    db.execute(text("DELETE FROM ledger WHERE request_id = :rid"), {"rid": rid})
    db.execute(text("DELETE FROM disputes WHERE submission_id::text = ANY(:sids)"), {"sids": sub_ids})
    db.execute(text("DELETE FROM submissions WHERE request_id = :rid"), {"rid": rid})
    db.execute(text("DELETE FROM data_requests WHERE id = :rid"), {"rid": rid})
    db.execute(text("DELETE FROM user_analytics WHERE user_id::text = ANY(:uids)"), {"uids": uids})
    db.execute(text("DELETE FROM user_auth WHERE id::text = ANY(:uids)"), {"uids": uids})
    db.commit()


def test_full_loop_dedup_cap_and_sweep_release():
    suffix = uuid.uuid4().hex[:8]
    r_email = f"r_{suffix}@test.io"
    p1_email = f"p1_{suffix}@test.io"
    p2_email = f"p2_{suffix}@test.io"

    R = _register_login(r_email, "requester")
    P1 = _register_login(p1_email, "provider")
    P2 = _register_login(p2_email, "provider")

    db = SessionLocal()
    rid = None
    sub_ids = []
    try:
        # 2–3: create + fund
        create = client.post("/requests/", headers=R, json={
            "title": "ids", "unit": "row", "amount_required": 10,
            "pricing_mode": "per_unit", "price_per_unit": 1.0, "budget": 10.0,
            "required_format": "csv",
            "spec": {
                "columns": [
                    {"name": "id", "type": "integer", "required": True},
                    {"name": "value", "type": "string", "required": True},
                ],
                "unique_key": ["id"],
            },
            "deadline": (datetime.utcnow() + timedelta(days=7)).isoformat(),
        })
        assert create.status_code == 200, create.text
        req = create.json()
        rid = req["id"]
        assert req["status"] == RequestStatus.DRAFT

        fund = client.post(f"/requests/{rid}/fund", headers=R)
        assert fund.status_code == 200, fund.text
        assert fund.json()["status"] == RequestStatus.OPEN
        assert ledger_balance(db, rid)["held"] == Decimal("10.00")

        # 4–5: P1 submits ids 1–6, accepted fully
        s1r = client.post("/submissions/", headers=P1,
            files={"file": ("a.csv", _csv(range(1, 7)), "text/csv")},
            data={"request_id": rid, "offered_amount": 6, "warranted": "true"})
        assert s1r.status_code == 200, s1r.text
        s1 = s1r.json()
        sub_ids.append(s1["id"])
        assert s1["status"] == SubmissionStatus.VALIDATED
        assert s1["validated_amount"] == 6

        a1 = client.post(f"/submissions/{s1['id']}/accept", headers=R)
        assert a1.status_code == 200, a1.text
        assert a1.json()["submission"]["accepted_amount"] == 6
        assert a1.json()["request_status"] == RequestStatus.PARTIALLY_FULFILLED
        assert a1.json()["request_accepted_total"] == 6

        # 6–7: P2 submits ids 4–13 (3 overlap: 4,5,6) — capped to 4 new, NO 500 (F7)
        s2r = client.post("/submissions/", headers=P2,
            files={"file": ("b.csv", _csv(range(4, 14)), "text/csv")},
            data={"request_id": rid, "offered_amount": 10, "warranted": "true"})
        assert s2r.status_code == 200, s2r.text
        s2 = s2r.json()
        sub_ids.append(s2["id"])
        assert s2["validated_amount"] == 10

        # Gate: a VALIDATED (not-yet-accepted) submission's full file is NOT downloadable;
        # the sample preview is. (Post-F4 the gate opens at ACCEPTED, not only PAID.)
        assert client.get(f"/submissions/{s2['id']}/download", headers=R).status_code == 403
        assert client.get(f"/submissions/{s2['id']}/sample", headers=R).status_code == 200

        a2 = client.post(f"/submissions/{s2['id']}/accept", headers=R)
        assert a2.status_code == 200, a2.text   # regression guard for F7 (no 500)
        body = a2.json()
        assert body["submission"]["accepted_amount"] == 4, body
        assert body["submission"]["status"] == SubmissionStatus.PARTIALLY_ACCEPTED
        assert body["request_status"] == RequestStatus.COMPLETED
        assert body["request_accepted_total"] == 10

        # accepted_keys must hold each of ids 1–10 exactly once
        key_count = db.execute(text(
            "SELECT count(*) FROM accepted_keys WHERE request_id = :rid"), {"rid": rid}).scalar()
        assert key_count == 10, f"expected 10 unique accepted keys, got {key_count}"

        # 8: during the acceptance window the buyer CAN download an ACCEPTED submission
        # to verify before releasing funds (F4) — status is still ACCEPTED, not yet PAID.
        with SessionLocal() as s:
            assert s.get(Submission, s1["id"]).status == SubmissionStatus.ACCEPTED
        assert client.get(f"/submissions/{s1['id']}/download", headers=R).status_code == 200

        # 9: elapse the window then sweep — both released (F8/F9), exactly once (F10)
        db.query(Submission).filter(Submission.id.in_(sub_ids)).update(
            {Submission.accepted_at: datetime.utcnow() - timedelta(hours=999)},
            synchronize_session=False,
        )
        db.commit()
        released = run_auto_release_sweep(db)
        assert released == 2

        with SessionLocal() as s:
            for sid in sub_ids:
                assert s.get(Submission, sid).status == SubmissionStatus.PAID

        # 10: download now works
        assert client.get(f"/submissions/{s1['id']}/download", headers=R).status_code == 200

        # 11: requester reviews P1
        rev = client.post("/reviews/", headers=R, json={
            "submission_id": s1["id"], "rating": 5, "comment": "great",
        })
        assert rev.status_code == 200, rev.text
        p1_id = str(_user_id(db, p1_email))
        analytics = client.get(f"/reviews/user/{p1_id}")
        assert analytics.status_code == 200
        assert analytics.json()["review_count"] == 1

        # 12: final ledger integrity — exact, no epsilon, never over budget
        bal = ledger_balance(db, rid)
        assert bal["released"] == Decimal("10.00")
        assert bal["remaining"] == Decimal("0")
        assert bal["held"] == bal["released"] + bal["refunded"] + bal["remaining"]
    finally:
        if rid is not None:
            _cleanup(db, rid, sub_ids, [r_email, p1_email, p2_email])
        db.close()
