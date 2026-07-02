# tests/test_oauth.py
# Social-login plan Phase 3: the OAuth transport wiring. The linking logic is
# covered by test_social_login.py; here we only assert the endpoint plumbing.
# We DON'T exercise the live Google dance (network + real creds) — that's manual.

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_unconfigured_provider_returns_404():
    # Microsoft is intentionally not configured (§7.4 deferred) → clean 404, not 500.
    r = client.get("/auth/oauth/microsoft/start", follow_redirects=False)
    assert r.status_code == 404

    r2 = client.get("/auth/oauth/microsoft/callback", follow_redirects=False)
    assert r2.status_code == 404


def test_session_middleware_is_installed():
    # authlib needs request.session; assert the middleware is wired so /start can
    # stash state+nonce. (Presence check — avoids a network call to a real provider.)
    from starlette.middleware.sessions import SessionMiddleware
    assert any(m.cls is SessionMiddleware for m in app.user_middleware)
