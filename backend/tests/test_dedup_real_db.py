# tests/test_dedup_real_db.py
#
# F7: cross-provider dedup against a REAL Postgres.
# The bug being guarded is an IntegrityError (500) on partial overlap caused by
# persisting key_hashes[:accepted] instead of the genuinely-new keys. Only a real
# DB with the uq_accepted_key unique constraint can reproduce it — a MagicMock can't.
#
# Skipped automatically when POSTGRES_* env vars are absent (conftest loads .env).

import hashlib
import threading
import uuid
import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session as OrmSession
from sqlalchemy import select

from app.models import DataRequest, Submission, SubmissionStatus, AcceptedKey
from app.lifecycle import accept_submission


# Reuse the same URL-building / skip logic as the race harness
from tests.test_allocation_race import DB_URL, _build_url  # noqa: E402

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping real-DB dedup tests",
)


def _key_hash(i: int) -> str:
    """Stable hash for record index i (matches ingest's repr(tuple) scheme loosely;
    here we only need uniqueness + determinism, not parity with ingest)."""
    return hashlib.sha256(f"record-{i}".encode()).hexdigest()


@pytest.fixture(scope="module")
def engine():
    return create_engine(DB_URL, pool_size=5)


@pytest.fixture()
def Session(engine):
    return sessionmaker(bind=engine)


def _ids():
    return {k: str(uuid.uuid4()) for k in ("user_id", "request_id", "sub_a", "sub_b")}


def _seed(engine, ids, amount_required=200):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO user_auth (id, email, password_hash, role, created_at, is_deleted, version)
            VALUES (:uid, :email, 'x', 'REQUESTER', now(), false, 1)
            ON CONFLICT DO NOTHING
        """), {"uid": ids["user_id"], "email": f"dedup_{ids['user_id']}@test.com"})

        conn.execute(text("""
            INSERT INTO data_requests
                (id, title, status, budget, price_per_unit, pricing_mode, amount_required,
                 accepted_total, unit, requester_id, created_at, is_deleted, version)
            VALUES (:rid, 'dedup test', 'OPEN', :budget, 1.0, 'PER_UNIT',
                    :amt, 0, 'row', :uid, now(), false, 1)
        """), {
            "rid": ids["request_id"],
            "budget": float(amount_required),
            "amt": amount_required,
            "uid": ids["user_id"],
        })


def _insert_submission(engine, ids, sub_key, key_hashes):
    """Insert a VALIDATED submission carrying the given key_hashes (JSON column)."""
    import json
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO submissions
                (id, request_id, provider_id, status, validated_amount, offered_amount,
                 accepted_amount, content_link, key_hashes, created_at, is_deleted, version)
            VALUES (:sid, :rid, :uid, 'VALIDATED', :va, :va, 0,
                    'test.csv', CAST(:kh AS json), now(), false, 1)
        """), {
            "sid": ids[sub_key],
            "rid": ids["request_id"],
            "uid": ids["user_id"],
            "va": len(key_hashes),
            "kh": json.dumps(key_hashes),
        })


def _cleanup(engine, ids):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM accepted_keys WHERE request_id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM ledger WHERE request_id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM submissions WHERE request_id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM data_requests WHERE id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM user_auth WHERE id = :uid"), {"uid": ids["user_id"]})


def _accept(Session, ids, sub_key):
    """Run the locked accept path for one submission, like the endpoint does."""
    session = Session()
    try:
        req = session.execute(
            select(DataRequest).where(DataRequest.id == ids["request_id"]).with_for_update()
        ).scalars().first()
        sub = session.execute(
            select(Submission).where(Submission.id == ids[sub_key]).with_for_update()
        ).scalars().first()
        accept_submission(sub, req, session)
        return sub.status, sub.accepted_amount
    finally:
        session.close()


# ---------------------------------------------------------------------------
# F7 acceptance criteria
# ---------------------------------------------------------------------------

class TestPartialOverlap:
    def test_partial_overlap_no_500_pays_only_new(self, engine, Session):
        """
        A accepts records 0–29 (30). B submits 20–69 (50: 10 overlap, 40 new).
        B → PARTIALLY_ACCEPTED, accepted_amount == 40, no 500,
        accepted_keys for the request == 70 rows (0–69, each once).
        """
        ids = _ids()
        _seed(engine, ids, amount_required=200)
        try:
            a_hashes = [_key_hash(i) for i in range(0, 30)]
            b_hashes = [_key_hash(i) for i in range(20, 70)]
            _insert_submission(engine, ids, "sub_a", a_hashes)
            _insert_submission(engine, ids, "sub_b", b_hashes)

            status_a, accepted_a = _accept(Session, ids, "sub_a")
            assert accepted_a == 30

            # The bug: this used to raise IntegrityError (500). Must succeed now.
            status_b, accepted_b = _accept(Session, ids, "sub_b")
            assert accepted_b == 40, f"B should be paid for 40 new records, got {accepted_b}"
            assert status_b == SubmissionStatus.PARTIALLY_ACCEPTED

            with Session() as s:
                key_count = s.query(AcceptedKey).filter(
                    AcceptedKey.request_id == ids["request_id"]
                ).count()
                assert key_count == 70, f"Expected 70 unique accepted keys, got {key_count}"

                req = s.get(DataRequest, ids["request_id"])
                assert req.accepted_total == 70
        finally:
            _cleanup(engine, ids)

    def test_no_overlap_full_credit(self, engine, Session):
        """B's records are entirely disjoint from A's → B gets full credit."""
        ids = _ids()
        _seed(engine, ids, amount_required=200)
        try:
            a_hashes = [_key_hash(i) for i in range(0, 30)]
            b_hashes = [_key_hash(i) for i in range(100, 140)]   # disjoint
            _insert_submission(engine, ids, "sub_a", a_hashes)
            _insert_submission(engine, ids, "sub_b", b_hashes)

            _accept(Session, ids, "sub_a")
            status_b, accepted_b = _accept(Session, ids, "sub_b")
            assert accepted_b == 40
            assert status_b == SubmissionStatus.ACCEPTED

            with Session() as s:
                key_count = s.query(AcceptedKey).filter(
                    AcceptedKey.request_id == ids["request_id"]
                ).count()
                assert key_count == 70
        finally:
            _cleanup(engine, ids)

    def test_full_overlap_rejected(self, engine, Session):
        """B resubmits exactly A's records → B REJECTED, 0 paid, no new keys, no 500."""
        ids = _ids()
        _seed(engine, ids, amount_required=200)
        try:
            a_hashes = [_key_hash(i) for i in range(0, 30)]
            b_hashes = list(a_hashes)   # identical
            _insert_submission(engine, ids, "sub_a", a_hashes)
            _insert_submission(engine, ids, "sub_b", b_hashes)

            _accept(Session, ids, "sub_a")
            status_b, accepted_b = _accept(Session, ids, "sub_b")
            assert accepted_b == 0
            assert status_b == SubmissionStatus.REJECTED

            with Session() as s:
                key_count = s.query(AcceptedKey).filter(
                    AcceptedKey.request_id == ids["request_id"]
                ).count()
                assert key_count == 30, "No new keys should be added for a fully-overlapping submission"
        finally:
            _cleanup(engine, ids)
