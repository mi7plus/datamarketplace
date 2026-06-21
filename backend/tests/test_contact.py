# tests/test_contact.py
# U2: contact intake — routes by reason, validates, consent required, honeypot +
# time-trap drop bots silently.

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db import SessionLocal
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set — skipping contact test")

client = TestClient(app)


def _payload(**over):
    base = {"name": "Dana", "email": f"d_{uuid.uuid4().hex[:6]}@t.io", "reason": "buyer",
            "message": "I'd like to buy data.", "consent": True, "elapsed_ms": 5000}
    base.update(over)
    return base


def _count(email):
    with SessionLocal() as db:
        return db.execute(text("SELECT count(*) FROM contact_messages WHERE email=:e"), {"e": email}).scalar()


def test_valid_submission_stored():
    p = _payload()
    r = client.post("/contact/", json=p)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert _count(p["email"]) == 1
    with SessionLocal() as db:
        db.execute(text("DELETE FROM contact_messages WHERE email=:e"), {"e": p["email"]})
        db.commit()


def test_consent_required_and_reason_validated():
    assert client.post("/contact/", json=_payload(consent=False)).status_code == 422
    assert client.post("/contact/", json=_payload(reason="spam")).status_code == 422


def test_honeypot_and_timetrap_drop_silently():
    p1 = _payload(company_website="http://bot.example")
    assert client.post("/contact/", json=p1).status_code == 200
    assert _count(p1["email"]) == 0          # honeypot → dropped, not stored

    p2 = _payload(elapsed_ms=100)
    assert client.post("/contact/", json=p2).status_code == 200
    assert _count(p2["email"]) == 0          # too fast → dropped
