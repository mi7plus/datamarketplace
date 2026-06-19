# tests/test_auto_release.py
#
# F8: providers are not stranded when the buyer disappears.
# Real-Postgres tests for the background sweep + provider claim path, plus unit
# checks for the shared window/dispute helper.

import uuid
import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import DataRequest, Submission, SubmissionStatus
from app.submissions import (
    run_auto_release_sweep,
    _window_elapsed,
    _auto_release_if_due,
    ACCEPTANCE_WINDOW_HOURS,
)

from tests.test_allocation_race import DB_URL  # reuse skip logic

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping real-DB auto-release tests",
)


@pytest.fixture(scope="module")
def engine():
    return create_engine(DB_URL, pool_size=5)


@pytest.fixture()
def Session(engine):
    return sessionmaker(bind=engine)


def _ids():
    return {k: str(uuid.uuid4()) for k in ("requester", "provider", "request", "submission")}


def _seed(engine, ids, *, accepted_hours_ago, with_dispute=False, status="ACCEPTED"):
    accepted_at = datetime.utcnow() - timedelta(hours=accepted_hours_ago)
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
            VALUES (:rid, 'sweep test', 'PARTIALLY_FULFILLED', 100.0, 1.0, 'PER_UNIT',
                    100, 40, 'row', :req, now(), false, 1)
        """), {"rid": ids["request"], "req": ids["requester"]})

        conn.execute(text("""
            INSERT INTO submissions
                (id, request_id, provider_id, status, validated_amount, offered_amount,
                 accepted_amount, amount_due, accepted_at, content_link, storage_location,
                 created_at, is_deleted, version)
            VALUES (:sid, :rid, :prov, :status, 40, 40, 40, 40.0, :acc,
                    'test.csv', 'req/prov/test.csv', now(), false, 1)
        """), {
            "sid": ids["submission"], "rid": ids["request"], "prov": ids["provider"],
            "status": status, "acc": accepted_at,
        })

        if with_dispute:
            conn.execute(text("""
                INSERT INTO disputes (id, submission_id, opened_by_id, reason, status,
                                      created_at, is_deleted, version)
                VALUES (:did, :sid, :req, 'bad data', 'open', now(), false, 1)
            """), {"did": str(uuid.uuid4()), "sid": ids["submission"], "req": ids["requester"]})


def _cleanup(engine, ids):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM disputes WHERE submission_id = :sid"), {"sid": ids["submission"]})
        conn.execute(text("DELETE FROM ledger WHERE request_id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM submissions WHERE request_id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM data_requests WHERE id = :rid"), {"rid": ids["request"]})
        conn.execute(text("DELETE FROM user_auth WHERE id IN (:a, :b)"),
                     {"a": ids["requester"], "b": ids["provider"]})


class TestSweep:
    def test_elapsed_window_no_dispute_is_released(self, engine, Session):
        """Buyer never returned, window elapsed, no dispute → sweep pays the provider."""
        ids = _ids()
        _seed(engine, ids, accepted_hours_ago=ACCEPTANCE_WINDOW_HOURS + 1)
        try:
            with Session() as db:
                released = run_auto_release_sweep(db)
            assert released >= 1
            with Session() as s:
                sub = s.get(Submission, ids["submission"])
                assert sub.status == SubmissionStatus.PAID
                # exactly one release entry in the ledger
                rel = s.execute(text(
                    "SELECT count(*) FROM ledger WHERE submission_id = :sid AND entry_type = 'release'"
                ), {"sid": ids["submission"]}).scalar()
                assert rel == 1
        finally:
            _cleanup(engine, ids)

    def test_within_window_not_released(self, engine, Session):
        """Window has NOT elapsed → sweep leaves it ACCEPTED."""
        ids = _ids()
        _seed(engine, ids, accepted_hours_ago=ACCEPTANCE_WINDOW_HOURS - 1)
        try:
            with Session() as db:
                run_auto_release_sweep(db)
            with Session() as s:
                sub = s.get(Submission, ids["submission"])
                assert sub.status == SubmissionStatus.ACCEPTED
        finally:
            _cleanup(engine, ids)

    def test_open_dispute_blocks_release(self, engine, Session):
        """Window elapsed but a dispute is open → sweep must NOT release."""
        ids = _ids()
        _seed(engine, ids, accepted_hours_ago=ACCEPTANCE_WINDOW_HOURS + 5, with_dispute=True)
        try:
            with Session() as db:
                run_auto_release_sweep(db)
            with Session() as s:
                sub = s.get(Submission, ids["submission"])
                assert sub.status == SubmissionStatus.ACCEPTED
        finally:
            _cleanup(engine, ids)

    def test_sweep_is_idempotent(self, engine, Session):
        """Running the sweep twice must not double-pay (no second release entry)."""
        ids = _ids()
        _seed(engine, ids, accepted_hours_ago=ACCEPTANCE_WINDOW_HOURS + 2)
        try:
            with Session() as db:
                run_auto_release_sweep(db)
            with Session() as db:
                run_auto_release_sweep(db)   # second pass — submission already PAID
            with Session() as s:
                rel = s.execute(text(
                    "SELECT count(*) FROM ledger WHERE submission_id = :sid AND entry_type = 'release'"
                ), {"sid": ids["submission"]}).scalar()
                assert rel == 1
        finally:
            _cleanup(engine, ids)


class TestWindowHelper:
    def test_window_elapsed_true_after_window(self):
        sub = SimpleNamespace(accepted_at=datetime.utcnow() - timedelta(hours=ACCEPTANCE_WINDOW_HOURS + 1))
        assert _window_elapsed(sub) is True

    def test_window_elapsed_false_before_window(self):
        sub = SimpleNamespace(accepted_at=datetime.utcnow() - timedelta(hours=1))
        assert _window_elapsed(sub) is False

    def test_window_elapsed_false_when_accepted_at_none(self):
        sub = SimpleNamespace(accepted_at=None)
        assert _window_elapsed(sub) is False
