# tests/test_allocation_race.py
#
# Real-database concurrency tests for the accept endpoint.
# Requires a live Postgres with the app schema applied.
# Skipped automatically when DATABASE_URL / POSTGRES_* env vars are absent.
#
# Run against a real DB:
#   POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=... pytest tests/test_allocation_race.py -v

import os
import threading
import uuid
import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import DataRequest, Submission, SubmissionStatus, AcceptedKey

# Build a DATABASE_URL from individual env vars (same logic as db.py)
def _build_url() -> str | None:
    user = os.getenv("POSTGRES_USER")
    pwd  = os.getenv("POSTGRES_PASSWORD")
    db   = os.getenv("POSTGRES_DB")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    if not all([user, pwd, db]):
        return None
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


DB_URL = _build_url()
pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB not set — skipping real-DB race tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    return create_engine(DB_URL, pool_size=5)


@pytest.fixture()
def Session(engine):
    return sessionmaker(bind=engine)


def _make_ids():
    return {k: str(uuid.uuid4()) for k in
            ("user_id", "request_id", "submission_id", "submission2_id")}


def _seed(engine, ids: dict, amount_required: int = 100):
    """Insert minimal rows needed for the race test. Cleaned up after."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO user_auth (id, email, password_hash, role, created_at, is_deleted, version)
            VALUES (:uid, :email, 'x', 'REQUESTER', now(), false, 1)
            ON CONFLICT DO NOTHING
        """), {"uid": ids["user_id"], "email": f"race_{ids['user_id']}@test.com"})

        conn.execute(text("""
            INSERT INTO data_requests
                (id, title, status, budget, price_per_unit, pricing_mode, amount_required,
                 accepted_total, unit, requester_id, created_at, is_deleted, version)
            VALUES (:rid, 'race test', 'OPEN', :budget, :ppu, 'PER_UNIT',
                    :amt, 0, 'row', :uid, now(), false, 1)
        """), {
            "rid": ids["request_id"],
            "budget": float(amount_required) * 1.0,
            "ppu": 1.0,
            "amt": amount_required,
            "uid": ids["user_id"],
        })

        for sid_key in ("submission_id", "submission2_id"):
            conn.execute(text("""
                INSERT INTO submissions
                    (id, request_id, provider_id, status, validated_amount, offered_amount,
                     accepted_amount, content_link, created_at, is_deleted, version)
                VALUES (:sid, :rid, :uid, 'VALIDATED', :va, :va, 0,
                        'test.csv', now(), false, 1)
            """), {
                "sid": ids[sid_key],
                "rid": ids["request_id"],
                "uid": ids["user_id"],
                "va": amount_required,   # each claims the full amount
            })


def _cleanup(engine, ids: dict):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ledger WHERE request_id = :rid"),
                     {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM submissions WHERE request_id = :rid"),
                     {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM data_requests WHERE id = :rid"),
                     {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM user_auth WHERE id = :uid"),
                     {"uid": ids["user_id"]})


# ---------------------------------------------------------------------------
# Test A — two concurrent accepts of the SAME submission
# Only one should succeed; accepted_total incremented exactly once.
# ---------------------------------------------------------------------------

class TestDoubleAcceptSameSubmission:
    def test_only_one_accept_succeeds(self, engine, Session):
        ids = _make_ids()
        _seed(engine, ids, amount_required=100)
        try:
            results: list[str] = []
            errors:  list[Exception] = []

            def _do_accept(submission_id: str):
                from app.lifecycle import accept_submission
                from app.models import DataRequest, Submission, SubmissionStatus
                from sqlalchemy import select

                session = Session()
                try:
                    # Mimic the endpoint: lock request, re-lock submission, run accept
                    data_request = session.execute(
                        select(DataRequest)
                        .where(DataRequest.id == ids["request_id"])
                        .with_for_update()
                    ).scalars().first()

                    sub = session.execute(
                        select(Submission)
                        .where(Submission.id == submission_id)
                        .with_for_update()
                    ).scalars().first()

                    if not sub or sub.status != SubmissionStatus.VALIDATED:
                        results.append("rejected_409")
                        return

                    accept_submission(sub, data_request, session)
                    results.append("ok")
                except Exception as exc:
                    errors.append(exc)
                    results.append(f"error:{exc}")
                    try:
                        session.rollback()
                    except Exception:
                        pass
                finally:
                    session.close()

            t1 = threading.Thread(target=_do_accept, args=(ids["submission_id"],))
            t2 = threading.Thread(target=_do_accept, args=(ids["submission_id"],))
            t1.start(); t2.start()
            t1.join(); t2.join()

            # Exactly one thread must have succeeded
            ok_count = results.count("ok")
            assert ok_count == 1, f"Expected 1 success, got: {results}"

            # accepted_total must equal accepted_amount of the winning accept (≤ 100)
            with Session() as s:
                req = s.get(DataRequest, ids["request_id"])
                sub = s.get(Submission, ids["submission_id"])
                assert req.accepted_total == sub.accepted_amount
                assert req.accepted_total > 0

        finally:
            _cleanup(engine, ids)


# ---------------------------------------------------------------------------
# Test B — two DIFFERENT submissions racing for the last N slots
# Total accepted must not exceed amount_required.
# ---------------------------------------------------------------------------

class TestTwoSubmissionsRaceLastSlot:
    def test_total_accepted_never_exceeds_required(self, engine, Session):
        ids = _make_ids()
        amount_required = 50
        _seed(engine, ids, amount_required=amount_required)
        try:
            results: list[str] = []

            def _do_accept(submission_id: str):
                from app.lifecycle import accept_submission
                from app.models import DataRequest, Submission, SubmissionStatus
                from sqlalchemy import select

                session = Session()
                try:
                    data_request = session.execute(
                        select(DataRequest)
                        .where(DataRequest.id == ids["request_id"])
                        .with_for_update()
                    ).scalars().first()

                    sub = session.execute(
                        select(Submission)
                        .where(Submission.id == submission_id)
                        .with_for_update()
                    ).scalars().first()

                    if not sub or sub.status != SubmissionStatus.VALIDATED:
                        results.append("rejected_409")
                        return

                    accept_submission(sub, data_request, session)
                    results.append("ok")
                except Exception as exc:
                    results.append(f"error:{exc}")
                    try:
                        session.rollback()
                    except Exception:
                        pass
                finally:
                    session.close()

            t1 = threading.Thread(target=_do_accept, args=(ids["submission_id"],))
            t2 = threading.Thread(target=_do_accept, args=(ids["submission2_id"],))
            t1.start(); t2.start()
            t1.join(); t2.join()

            with Session() as s:
                req = s.get(DataRequest, ids["request_id"])
                sub1 = s.get(Submission, ids["submission_id"])
                sub2 = s.get(Submission, ids["submission2_id"])

                total_accepted = (sub1.accepted_amount or 0) + (sub2.accepted_amount or 0)
                assert total_accepted == amount_required, (
                    f"Expected exactly {amount_required} units accepted, got {total_accepted}"
                )
                assert req.accepted_total == amount_required

        finally:
            _cleanup(engine, ids)
