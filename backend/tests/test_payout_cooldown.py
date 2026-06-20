# tests/test_payout_cooldown.py
# S3: a recently-changed payout destination cannot immediately receive releases.
# Release is deferred (submission stays ACCEPTED, no ledger 'release') during the
# cool-down, then proceeds once it elapses.

import uuid
import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Submission, SubmissionStatus
from app.submissions import _release_and_pay, PAYOUT_COOLDOWN_HOURS

from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping payout cool-down test",
)


@pytest.fixture(scope="module")
def engine():
    return create_engine(DB_URL, pool_size=5)


@pytest.fixture()
def Session(engine):
    return sessionmaker(bind=engine)


def _ids():
    return {k: str(uuid.uuid4()) for k in ("requester", "provider", "request", "submission")}


def _seed(engine, ids, *, payout_changed_at):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO user_auth (id, email, password_hash, role, stripe_account_id,
                                   payout_account_changed_at, created_at, is_deleted, version)
            VALUES (:uid, :email, 'x', 'REQUESTER', NULL, NULL, now(), false, 1)
        """), {"uid": ids["requester"], "email": f"req_{ids['requester']}@t.io"})
        conn.execute(text("""
            INSERT INTO user_auth (id, email, password_hash, role, stripe_account_id,
                                   payout_account_changed_at, created_at, is_deleted, version)
            VALUES (:uid, :email, 'x', 'PROVIDER', 'acct_test', :changed, now(), false, 1)
        """), {"uid": ids["provider"], "email": f"prov_{ids['provider']}@t.io", "changed": payout_changed_at})

        conn.execute(text("""
            INSERT INTO data_requests
                (id, title, status, budget, price_per_unit, pricing_mode, amount_required,
                 accepted_total, unit, requester_id, created_at, is_deleted, version)
            VALUES (:rid, 'cooldown', 'PARTIALLY_FULFILLED', 100.0, 1.0, 'PER_UNIT',
                    100, 40, 'row', :req, now(), false, 1)
        """), {"rid": ids["request"], "req": ids["requester"]})
        conn.execute(text("""
            INSERT INTO ledger (id, request_id, entry_type, amount, external_ref, created_at, is_deleted, version)
            VALUES (:lid, :rid, 'hold', 100.0, :ref, now(), false, 1)
        """), {"lid": str(uuid.uuid4()), "rid": ids["request"], "ref": f"hold_{ids['request']}"})
        conn.execute(text("""
            INSERT INTO submissions
                (id, request_id, provider_id, status, validated_amount, offered_amount,
                 accepted_amount, amount_due, accepted_at, content_link, storage_location,
                 created_at, is_deleted, version)
            VALUES (:sid, :rid, :prov, 'ACCEPTED', 40, 40, 40, 40.0, :acc,
                    'test.csv', 'k', now(), false, 1)
        """), {"sid": ids["submission"], "rid": ids["request"], "prov": ids["provider"],
               "acc": datetime.utcnow() - timedelta(hours=999)})


def _cleanup(engine, ids):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ledger WHERE request_id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM submissions WHERE request_id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM data_requests WHERE id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM user_auth WHERE id IN (:a,:b)"),
                     {"a": ids["requester"], "b": ids["provider"]})


def _release_rows(Session, ids):
    with Session() as s:
        return s.execute(text(
            "SELECT count(*) FROM ledger WHERE submission_id = :sid AND entry_type='release'"
        ), {"sid": ids["submission"]}).scalar()


def test_release_deferred_during_cooldown(engine, Session):
    ids = _ids()
    _seed(engine, ids, payout_changed_at=datetime.utcnow() - timedelta(hours=1))  # within cool-down
    try:
        with Session() as db:
            sub = _release_and_pay(ids["submission"], db)
            assert sub.status == SubmissionStatus.ACCEPTED   # deferred, not paid
        assert _release_rows(Session, ids) == 0
    finally:
        _cleanup(engine, ids)


def test_release_proceeds_after_cooldown(engine, Session):
    ids = _ids()
    # Changed long ago → cool-down elapsed
    _seed(engine, ids, payout_changed_at=datetime.utcnow() - timedelta(hours=PAYOUT_COOLDOWN_HOURS + 1))
    try:
        with Session() as db:
            sub = _release_and_pay(ids["submission"], db)
            assert sub.status == SubmissionStatus.PAID
        assert _release_rows(Session, ids) == 1
    finally:
        _cleanup(engine, ids)
