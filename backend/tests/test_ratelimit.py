# tests/test_ratelimit.py
# S6: per-IP rate limiting on auth endpoints (brute-force resistance).

import uuid
import pytest
from types import SimpleNamespace
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.ratelimit as rl
from app.main import app


def _fake_request(ip="1.2.3.4"):
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


class TestLimiterUnit:
    def setup_method(self):
        rl.reset()

    def test_allows_up_to_limit_then_429(self, monkeypatch):
        monkeypatch.setenv("RATELIMIT_ENABLED", "true")
        dep = rl.rate_limit("b", limit=3, window_seconds=60)
        req = _fake_request()
        for _ in range(3):
            dep(req)                      # first 3 OK
        with pytest.raises(HTTPException) as e:
            dep(req)                      # 4th blocked
        assert e.value.status_code == 429

    def test_disabled_is_noop(self, monkeypatch):
        monkeypatch.setenv("RATELIMIT_ENABLED", "false")
        dep = rl.rate_limit("b", limit=1, window_seconds=60)
        req = _fake_request()
        for _ in range(50):
            dep(req)                      # never blocks when disabled

    def test_per_ip_isolation(self, monkeypatch):
        monkeypatch.setenv("RATELIMIT_ENABLED", "true")
        dep = rl.rate_limit("b", limit=1, window_seconds=60)
        dep(_fake_request("10.0.0.1"))
        dep(_fake_request("10.0.0.2"))   # different IP — own bucket, OK
        with pytest.raises(HTTPException):
            dep(_fake_request("10.0.0.1"))   # first IP over limit

    def test_xff_first_hop_used(self, monkeypatch):
        monkeypatch.setenv("RATELIMIT_ENABLED", "true")
        dep = rl.rate_limit("b", limit=1, window_seconds=60)
        r = SimpleNamespace(headers={"x-forwarded-for": "9.9.9.9, 10.0.0.1"},
                            client=SimpleNamespace(host="10.0.0.1"))
        dep(r)
        with pytest.raises(HTTPException):
            dep(r)                        # same forwarded client → blocked


class TestRegisterEndpointThrottled:
    def test_register_429_after_limit(self, monkeypatch):
        monkeypatch.setenv("RATELIMIT_ENABLED", "true")
        rl.reset()
        client = TestClient(app)
        # register limit is 5/min/IP; unique emails so 400-dupe doesn't mask it
        statuses = [
            client.post("/auth/register", json={
                "email": f"rl_{uuid.uuid4().hex[:8]}@t.io", "password": "pw123456",
                "role": "requester",
            }).status_code
            for _ in range(7)
        ]
        assert 429 in statuses, statuses
        # cleanup any users that were created before the limit hit
        from app.db import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("DELETE FROM user_auth WHERE email LIKE 'rl\\_%' ESCAPE '\\'"))
            db.commit()
        rl.reset()
