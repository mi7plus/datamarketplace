# tests/test_internal_callback.py
#
# Rust ingest plan: the /internal/ingest-result callback (async path). Python is
# the sole writer to the core schema; Rust POSTs a report and Python flips the
# submission + populates dedup staging. Auth via X-Internal-Secret; idempotent.

import uuid
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from app.main import app
from app.models import SubmissionKeyStaging
from tests.test_dedup_real_db import DB_URL, engine, Session, _ids, _seed  # noqa: E402

pytestmark = pytest.mark.skipif(
    DB_URL is None,
    reason="POSTGRES_* not set — skipping internal-callback tests",
)

SECRET = "test-internal-secret"
client = TestClient(app)


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("INGEST_CALLBACK_SECRET", SECRET)


def _pending_submission(engine, ids):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO submissions
                (id, request_id, provider_id, status, offered_amount, accepted_amount,
                 content_link, created_at, is_deleted, version)
            VALUES (:sid, :rid, :uid, 'PENDING', 0, 0, 'raw.csv', now(), false, 1)
        """), {"sid": ids["sub_a"], "rid": ids["request_id"], "uid": ids["user_id"]})


def _report(amount=3):
    return {
        "submission_id": None,  # set by caller
        "content_hash": "deadbeef",
        "report": {
            "status": "VALIDATED",
            "validated_amount": amount,
            "dataset_hash": "deadbeef",
            "quality_score": 0.9,
            "sample": [{"email": "a@b.com"}],
            "key_hashes": [f"h{i}" for i in range(amount)],
            "validation_report": {"conforming_rows": amount},
            "errors": [],
        },
    }


def _cleanup(engine, ids):
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM submission_key_staging WHERE submission_id IN "
            "(SELECT id FROM submissions WHERE request_id = :rid)"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM submissions WHERE request_id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM data_requests WHERE id = :rid"), {"rid": ids["request_id"]})
        conn.execute(text("DELETE FROM user_auth WHERE id = :uid"), {"uid": ids["user_id"]})


def test_callback_validates_and_populates_staging(engine, Session):
    ids = _ids()
    _seed(engine, ids)
    _pending_submission(engine, ids)
    try:
        body = _report(amount=3)
        body["submission_id"] = ids["sub_a"]
        r = client.post("/internal/ingest-result", json=body, headers={"X-Internal-Secret": SECRET})
        assert r.status_code == 200, r.text
        assert r.json()["submission_status"] == "validated"
        assert r.json()["validated_amount"] == 3
        with Session() as s:
            assert s.query(SubmissionKeyStaging).filter(
                SubmissionKeyStaging.submission_id == ids["sub_a"]).count() == 3

        # Idempotent: a re-delivered report is a no-op.
        r2 = client.post("/internal/ingest-result", json=body, headers={"X-Internal-Secret": SECRET})
        assert r2.status_code == 200
        assert r2.json()["status"] == "already_processed"
        with Session() as s:
            # No duplicate staging rows from the second call.
            assert s.query(SubmissionKeyStaging).filter(
                SubmissionKeyStaging.submission_id == ids["sub_a"]).count() == 3
    finally:
        _cleanup(engine, ids)


def test_callback_rejects_zero_validated(engine, Session):
    ids = _ids()
    _seed(engine, ids)
    _pending_submission(engine, ids)
    try:
        body = _report(amount=0)
        body["submission_id"] = ids["sub_a"]
        body["report"]["status"] = "REJECTED_INVALID"
        r = client.post("/internal/ingest-result", json=body, headers={"X-Internal-Secret": SECRET})
        assert r.json()["submission_status"] == "rejected_invalid"
    finally:
        _cleanup(engine, ids)


def test_callback_requires_valid_secret():
    body = _report()
    body["submission_id"] = str(uuid.uuid4())
    assert client.post("/internal/ingest-result", json=body).status_code == 401
    assert client.post("/internal/ingest-result", json=body,
                       headers={"X-Internal-Secret": "wrong"}).status_code == 401


def test_callback_disabled_without_env(monkeypatch):
    monkeypatch.delenv("INGEST_CALLBACK_SECRET", raising=False)
    body = _report()
    body["submission_id"] = str(uuid.uuid4())
    assert client.post("/internal/ingest-result", json=body,
                       headers={"X-Internal-Secret": "x"}).status_code == 503
