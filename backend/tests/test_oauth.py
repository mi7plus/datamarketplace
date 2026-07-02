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


def test_google_identity_uses_email_verified_claim():
    from app.oauth import _extract_identity
    sub, email, verified = _extract_identity("google", {"sub": "g1", "email": "a@b.io", "email_verified": True})
    assert (sub, email, verified) == ("g1", "a@b.io", True)
    _, _, v2 = _extract_identity("google", {"sub": "g1", "email": "a@b.io", "email_verified": False})
    assert v2 is False


def test_microsoft_identity_edov_and_fallbacks(monkeypatch):
    from app.oauth import _extract_identity
    # xms_edov true (as a string) → verified; falls back to preferred_username for email.
    sub, email, verified = _extract_identity(
        "microsoft", {"sub": "m1", "preferred_username": "u@corp.com", "xms_edov": "true"}
    )
    assert (sub, email, verified) == ("m1", "u@corp.com", True)

    # No xms_edov, default mode → trusted (work/school account).
    monkeypatch.delenv("MICROSOFT_REQUIRE_EDOV", raising=False)
    _, _, v_default = _extract_identity("microsoft", {"sub": "m1", "email": "u@corp.com"})
    assert v_default is True

    # No xms_edov, strict mode → NOT verified (resolve_social_login would then 403).
    monkeypatch.setenv("MICROSOFT_REQUIRE_EDOV", "true")
    _, _, v_strict = _extract_identity("microsoft", {"sub": "m1", "email": "u@corp.com"})
    assert v_strict is False


def test_session_middleware_is_installed():
    # authlib needs request.session; assert the middleware is wired so /start can
    # stash state+nonce. (Presence check — avoids a network call to a real provider.)
    from starlette.middleware.sessions import SessionMiddleware
    assert any(m.cls is SessionMiddleware for m in app.user_middleware)
