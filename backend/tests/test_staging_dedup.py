# tests/test_staging_dedup.py
#
# Rust ingest plan P2: the SQL anti-join dedup (USE_STAGING_DEDUP) must produce
# the SAME allocation as the proven in-Python path. We run the F7 partial-overlap
# scenarios with the flag ON and assert identical results, then check the staging
# table is what the anti-join read from.

import pytest
from sqlalchemy import text

from app.models import DataRequest, Submission, SubmissionStatus, AcceptedKey, SubmissionKeyStaging

# Reuse the real-DB harness from the existing dedup test.
from tests.test_dedup_real_db import (  # noqa: E402
    DB_URL, engine, Session, _ids, _seed, _insert_submission, _accept, _key_hash,
)

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping real-DB staging-dedup tests",
)


@pytest.fixture(autouse=True)
def _staging_on(monkeypatch):
    """Force the anti-join path for every test in this module."""
    monkeypatch.setenv("USE_STAGING_DEDUP", "true")


def _cleanup_with_staging(engine, ids):
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM submission_key_staging WHERE submission_id IN "
            "(SELECT id FROM submissions WHERE request_id = :rid)"
        ), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM accepted_keys WHERE request_id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM ledger WHERE request_id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM submissions WHERE request_id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM data_requests WHERE id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM user_auth WHERE id = :uid"), {"uid": ids["user_id"]})


class TestAntiJoinParity:
    def test_partial_overlap_pays_only_new(self, engine, Session):
        """Same as the in-Python F7 test: A=0–29, B=20–69 → B paid 40, 70 keys."""
        ids = _ids()
        _seed(engine, ids, amount_required=200)
        try:
            _insert_submission(engine, ids, "sub_a", [_key_hash(i) for i in range(0, 30)])
            _insert_submission(engine, ids, "sub_b", [_key_hash(i) for i in range(20, 70)])

            _, accepted_a = _accept(Session, ids, "sub_a")
            assert accepted_a == 30
            status_b, accepted_b = _accept(Session, ids, "sub_b")
            assert accepted_b == 40
            assert status_b == SubmissionStatus.PARTIALLY_ACCEPTED

            with Session() as s:
                assert s.query(AcceptedKey).filter(
                    AcceptedKey.request_id == ids["request_id"]).count() == 70
                # Staging was populated for both submissions (anti-join source).
                assert s.query(SubmissionKeyStaging).filter(
                    SubmissionKeyStaging.submission_id == ids["sub_b"]).count() == 50
        finally:
            _cleanup_with_staging(engine, ids)

    def test_full_overlap_rejected(self, engine, Session):
        ids = _ids()
        _seed(engine, ids, amount_required=200)
        try:
            a = [_key_hash(i) for i in range(0, 30)]
            _insert_submission(engine, ids, "sub_a", a)
            _insert_submission(engine, ids, "sub_b", list(a))
            _accept(Session, ids, "sub_a")
            status_b, accepted_b = _accept(Session, ids, "sub_b")
            assert accepted_b == 0
            assert status_b == SubmissionStatus.REJECTED
            with Session() as s:
                assert s.query(AcceptedKey).filter(
                    AcceptedKey.request_id == ids["request_id"]).count() == 30
        finally:
            _cleanup_with_staging(engine, ids)

    def test_cap_at_remaining(self, engine, Session):
        """Anti-join honours the budget cap: amount_required=40, B offers 50 new → 10."""
        ids = _ids()
        _seed(engine, ids, amount_required=40)
        try:
            _insert_submission(engine, ids, "sub_a", [_key_hash(i) for i in range(0, 30)])
            _insert_submission(engine, ids, "sub_b", [_key_hash(i) for i in range(30, 80)])
            _accept(Session, ids, "sub_a")            # fills 30 of 40
            _, accepted_b = _accept(Session, ids, "sub_b")
            assert accepted_b == 10                    # only 10 capacity left
            with Session() as s:
                assert s.get(DataRequest, ids["request_id"]).accepted_total == 40
        finally:
            _cleanup_with_staging(engine, ids)
