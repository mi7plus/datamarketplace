# tests/test_cors_origins.py
# CORS is an EXPLICIT allowlist: the canonical FRONTEND_URL, its www↔apex
# counterpart, and localhost for dev. No wildcard-subdomain regex. Never "*".

from app.main import cors_origins


def test_apex_allows_apex_and_www_but_not_random_subdomain():
    o = cors_origins({"FRONTEND_URL": "https://rowbound.com"})
    assert "https://rowbound.com" in o              # canonical origin allowed
    assert "https://www.rowbound.com" in o          # www counterpart allowed
    assert "http://localhost:3000" in o             # dev
    assert "https://evil.rowbound.com" not in o     # arbitrary subdomain NOT allowed
    assert "*" not in o


def test_www_frontend_url_allows_exactly_apex_www_localhost():
    o = cors_origins({"FRONTEND_URL": "https://www.rowbound.com"})
    assert set(o) == {
        "https://rowbound.com",
        "https://www.rowbound.com",
        "http://localhost:3000",
    }


def test_trailing_slash_stripped():
    assert "https://rowbound.com" in cors_origins({"FRONTEND_URL": "https://rowbound.com/"})


def test_unset_is_localhost_only():
    assert cors_origins({}) == ["http://localhost:3000"]


# End-to-end against the live middleware (configured from the process FRONTEND_URL at
# import — localhost in CI). localhost is always allowed; any rowbound.com subdomain
# NOT in the allowlist must be rejected (no ACAO), proving the broad regex is gone.
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_localhost_origin_allowed():
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_random_subdomain_blocked_get():
    r = client.get("/health", headers={"Origin": "https://evil.rowbound.com"})
    assert r.headers.get("access-control-allow-origin") is None


def test_random_subdomain_blocked_preflight():
    r = client.options("/listings/", headers={
        "Origin": "https://evil.rowbound.com",
        "Access-Control-Request-Method": "GET",
    })
    assert r.headers.get("access-control-allow-origin") is None
