# tests/test_security_headers.py
# S6: baseline security headers on API responses + CORS pinned to explicit origins.

from fastapi.testclient import TestClient
from app.main import app, origins

client = TestClient(app)


class TestSecurityHeaders:
    def test_headers_present_on_response(self):
        # GET /requests/ is public (browse) — fine for header inspection.
        res = client.get("/requests/")
        assert res.headers.get("x-content-type-options") == "nosniff"
        assert res.headers.get("x-frame-options") == "DENY"
        assert res.headers.get("referrer-policy") == "no-referrer"
        assert "strict-transport-security" in res.headers


class TestCorsPinned:
    def test_allow_origins_is_not_wildcard(self):
        # allow_credentials=True forbids "*" — confirm the config is explicit.
        assert "*" not in origins
        assert any("localhost:3000" in o for o in origins)

    def test_allowed_origin_gets_acao(self):
        res = client.get("/requests/", headers={"Origin": "http://localhost:3000"})
        assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_disallowed_origin_gets_no_acao(self):
        res = client.get("/requests/", headers={"Origin": "https://evil.example.com"})
        # CORSMiddleware must not echo a non-allowed origin back.
        assert res.headers.get("access-control-allow-origin") != "https://evil.example.com"
