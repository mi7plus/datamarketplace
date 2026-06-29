# tests/test_webhook_signed.py
# The signed Stripe webhook path: construct_event returns a Stripe Event object,
# not a dict, so the handler must normalize before `.get()`. Regression test for
# the AttributeError 500.

import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set")

client = TestClient(app)
SECRET = "whsec_test_secret"


def _signed_headers(payload: bytes) -> dict:
    ts = int(time.time())
    signed = f"{ts}.{payload.decode()}".encode()
    sig = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return {"stripe-signature": f"t={ts},v1={sig}"}


def test_signed_webhook_returns_200(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "object": "event",
        "api_version": "2024-06-20",
        "created": int(time.time()),
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_test", "object": "payment_intent"}},
    }
    payload = json.dumps(event).encode()

    r = client.post("/webhooks/stripe", content=payload, headers=_signed_headers(payload))
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "payment_intent.succeeded"


def test_bad_signature_is_rejected(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    payload = json.dumps({"id": "evt_x", "type": "x"}).encode()
    r = client.post("/webhooks/stripe", content=payload,
                    headers={"stripe-signature": "t=1,v1=deadbeef"})
    assert r.status_code == 400
