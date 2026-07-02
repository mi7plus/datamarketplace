# tests/test_email_verification.py
# Social-login plan, Phase 1: email verification + pluggable mailer.
# Verification is ADDITIVE — registration/login still work; is_verified starts
# False and flips true only when the emailed link is clicked.

import uuid
import pytest

import app.mailer as mailer_mod
from app.mailer import get_mailer, LogMailer, SesMailer
from app.auth import create_email_verification_token, _decode_email_verification_token


# ---- Pure unit tests (no DB) ------------------------------------------------

def test_verification_token_roundtrip():
    uid = str(uuid.uuid4())
    tok = create_email_verification_token(uid)
    assert _decode_email_verification_token(tok) == uid


def test_wrong_purpose_token_rejected():
    from jose import jwt
    from app.auth import SECRET_KEY, ALGORITHM
    from fastapi import HTTPException
    bad = jwt.encode({"sub": "x"}, SECRET_KEY, algorithm=ALGORITHM)  # no purpose
    with pytest.raises(HTTPException):
        _decode_email_verification_token(bad)


def test_mailer_selection(monkeypatch):
    monkeypatch.setattr(mailer_mod, "_mailer", None)
    monkeypatch.delenv("MAILER", raising=False)
    assert isinstance(get_mailer(), LogMailer)
    monkeypatch.setattr(mailer_mod, "_mailer", None)
    monkeypatch.setenv("MAILER", "ses")
    monkeypatch.setenv("AWS_REGION", "eu-north-1")
    assert isinstance(get_mailer(), SesMailer)   # constructs the SES client, doesn't send
    monkeypatch.setattr(mailer_mod, "_mailer", None)


# ---- API tests (need Postgres) ----------------------------------------------

from fastapi.testclient import TestClient
from app.main import app
from tests.test_allocation_race import DB_URL

pytestmark_db = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set")
client = TestClient(app)


class _FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def fake_mailer(monkeypatch):
    fm = _FakeMailer()
    monkeypatch.setattr(mailer_mod, "_mailer", fm)  # get_mailer() returns this
    yield fm
    monkeypatch.setattr(mailer_mod, "_mailer", None)


def _register(email, password="pw123456", role="requester"):
    return client.post("/auth/register", json={"email": email, "password": password, "role": role})


@pytestmark_db
def test_register_sends_verification_email_and_stays_unverified(fake_mailer):
    email = f"v_{uuid.uuid4().hex[:8]}@t.io"
    r = _register(email)
    assert r.status_code == 200, r.text
    assert r.json().get("verification_email_sent") is True
    assert len(fake_mailer.sent) == 1
    assert fake_mailer.sent[0]["to"] == email
    assert "/auth/verify?token=" in fake_mailer.sent[0]["body"]


@pytestmark_db
def test_verify_link_sets_flag_and_redirects(fake_mailer):
    email = f"v_{uuid.uuid4().hex[:8]}@t.io"
    _register(email)
    token = fake_mailer.sent[0]["body"].split("/auth/verify?token=")[1].split()[0]

    r = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert r.status_code == 302
    assert "verified=1" in r.headers["location"]

    # A second click is a clean no-op (still redirects, still verified).
    assert client.get(f"/auth/verify?token={token}", follow_redirects=False).status_code == 302


@pytestmark_db
def test_invalid_token_rejected():
    r = client.get("/auth/verify?token=not-a-real-token", follow_redirects=False)
    assert r.status_code == 400


@pytestmark_db
def test_unverified_user_can_still_login(fake_mailer):
    email = f"v_{uuid.uuid4().hex[:8]}@t.io"
    _register(email)  # never verified
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    assert r.status_code == 200, r.text
    assert r.json().get("access_token")


@pytestmark_db
def test_resend_does_not_enumerate(fake_mailer):
    # Unknown email → generic 200, nothing sent.
    r = client.post("/auth/verify/resend", json={"email": f"nobody_{uuid.uuid4().hex}@t.io"})
    assert r.status_code == 200
    assert len(fake_mailer.sent) == 0

    # Real, unverified email → same response, but an email IS sent.
    email = f"v_{uuid.uuid4().hex[:8]}@t.io"
    _register(email)
    fake_mailer.sent.clear()
    r2 = client.post("/auth/verify/resend", json={"email": email})
    assert r2.status_code == 200
    assert len(fake_mailer.sent) == 1 and fake_mailer.sent[0]["to"] == email
