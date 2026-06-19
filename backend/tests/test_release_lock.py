# tests/test_release_lock.py
#
# F10: the release path (_release_and_pay) is the locked chokepoint for confirm /
# claim / lazy-download / sweep. No submission may be released twice via any
# combination of triggers. Requires a real Postgres (FOR UPDATE + the unique
# Ledger.external_ref constraint are the whole point — a mock can't reproduce it).

import uuid
import threading
import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import DataRequest, Submission, SubmissionStatus
from app.submissions import _release_and_pay

from tests.test_allocation_race import DB_URL  # reuse skip logic

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping real-DB release-lock tests",
)


@pytest.fixture(scope="module")
def engine():
    return create_engine(DB_URL, pool_size=8)


@pytest.fixture()
def Session(engine):
    return sessionmaker(bind=engine)


def _ids():
    return {k: str(uuid.uuid4()) for k in ("requester", "provider", "request", "submission")}


def _seed(engine, ids, *, status="ACCEPTED", with_dispute=False, request_status="PARTIALLY_FULFILLED"):
    with engine.begin() as conn:
        for role_key, role in (("requester", "REQUESTER"), ("provider", "PROVIDER")):
            conn.execute(text("""
                INSERT INTO user_auth (id, email, password_hash, role, stripe_account_id,
                                       created_at, is_deleted, version)
                VALUES (:uid, :email, 'x', :role, 'acct_test', now(), false, 1)
                ON CONFLICT DO NOTHING
            """), {"uid": ids[role_key], "email": f"{role_key}_{ids[role_key]}@t.com", "role": role})

        conn.execute(text("""
            INSERT INTO data_requests
                (id, title, status, budget, price_per_unit, pricing_mode, amount_required,
                 accepted_total, unit, requester_id, created_at, is_deleted, version)
            VALUES (:rid, 'release test', :rstatus, 100.0, 1.0, 'PER_UNIT',
                    100, 40, 'row', :req, now(), false, 1)
        """), {"rid": ids["request"], "req": ids["requester"], "rstatus": request_status})

        # Escrow hold so the ledger is consistent
        conn.execute(text("""
            INSERT INTO ledger (id, request_id, entry_type, amount, external_ref, created_at, is_deleted, version)
            VALUES (:lid, :rid, 'hold', 100.0, :ref, now(), false, 1)
        """), {"lid": str(uuid.uuid4()), "rid": ids["request"], "ref": f"hold_{ids['request']}"})

        conn.execute(text("""
            INSERT INTO submissions
                (id, request_id, provider_id, status, validated_amount, offered_amount,
                 accepted_amount, amount_due, accepted_at, content_link, storage_location,
                 created_at, is_deleted, version)
            VALUES (:sid, :rid, :prov, :status, 40, 40, 40, 40.0, :acc,
                    'test.csv', 'req/prov/test.csv', now(), false, 1)
        """), {
            "sid": ids["submission"], "rid": ids["request"], "prov": ids["provider"],
            "status": status, "acc": datetime.utcnow() - timedelta(hours=999),
        })

        if with_dispute:
            conn.execute(text("""
                INSERT INTO disputes (id, submission_id, opened_by_id, reason, status,
                                      created_at, is_deleted, version)
                VALUES (:did, :sid, :req, 'bad', 'open', now(), false, 1)
            """), {"did": str(uuid.uuid4()), "sid": ids["submission"], "req": ids["requester"]})


def _cleanup(engine, ids):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM disputes WHERE submission_id = :sid"), {"sid": ids["submission"]})
        conn.execute(text("DELETE FROM ledger WHERE request_id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM submissions WHERE request_id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM data_requests WHERE id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM user_auth WHERE id IN (:a, :b)"),
                     {"a": ids["requester"], "b": ids["provider"]})


def _release_count(Session, ids) -> int:
    with Session() as s:
        return s.execute(text(
            "SELECT count(*) FROM ledger WHERE submission_id = :sid AND entry_type = 'release'"
        ), {"sid": ids["submission"]}).scalar()


# ---------------------------------------------------------------------------
# 1. Idempotency (deterministic) — call the release path twice
# ---------------------------------------------------------------------------

class TestReleaseIdempotency:
    def test_double_release_is_one_entry_and_paid(self, engine, Session):
        ids = _ids()
        _seed(engine, ids)
        try:
            with Session() as db:
                sub1 = _release_and_pay(ids["submission"], db)
                assert sub1.status == SubmissionStatus.PAID

            # Second call must be a clean no-op (no 500, no second ledger entry)
            with Session() as db:
                sub2 = _release_and_pay(ids["submission"], db)
                assert sub2.status == SubmissionStatus.PAID

            assert _release_count(Session, ids) == 1
        finally:
            _cleanup(engine, ids)


# ---------------------------------------------------------------------------
# 2. Concurrency (threaded) — two triggers race on the same submission
# ---------------------------------------------------------------------------

class TestReleaseConcurrency:
    def test_two_threads_one_release(self, engine, Session):
        ids = _ids()
        _seed(engine, ids)
        try:
            results = []

            def _go():
                db = Session()
                try:
                    sub = _release_and_pay(ids["submission"], db)
                    results.append(sub.status)
                except Exception as exc:  # must NOT happen — no 500 on the loser
                    results.append(f"error:{exc}")
                finally:
                    db.close()

            t1 = threading.Thread(target=_go)
            t2 = threading.Thread(target=_go)
            t1.start(); t2.start()
            t1.join(); t2.join()

            assert all(r == SubmissionStatus.PAID for r in results), f"unexpected: {results}"
            assert _release_count(Session, ids) == 1, "exactly one release ledger row expected"
        finally:
            _cleanup(engine, ids)


# ---------------------------------------------------------------------------
# 3. Dispute race — dispute present at lock time blocks release
# ---------------------------------------------------------------------------

class TestDisputeBlocksUnderLock:
    def test_open_dispute_blocks_release_under_lock(self, engine, Session):
        ids = _ids()
        _seed(engine, ids, with_dispute=True)
        try:
            with Session() as db:
                sub = _release_and_pay(ids["submission"], db)
                # Under-lock dispute check must no-op (status unchanged, not PAID)
                assert sub.status == SubmissionStatus.ACCEPTED
            assert _release_count(Session, ids) == 0
        finally:
            _cleanup(engine, ids)
