# app/oauth.py
#
# Social-login plan Phase 3 — the OAuth/OIDC dance (Google). The security-critical
# part (who a verified identity resolves to) lives in social_auth.resolve_social_login;
# this module is just the transport: authorization-code flow with PKCE-less server
# secret, CSRF `state` + replay `nonce` (both handled by authlib via the session
# cookie), and server-side ID-token verification against the provider's JWKS.
#
# Only providers whose client id+secret are configured get registered, so an
# unconfigured deploy (dev/CI without creds) simply 404s the endpoints rather than
# crashing on startup. Microsoft/Entra is intentionally deferred (§7.4).
#
# The callback never puts the access token in the URL. It sets ONLY the httpOnly
# refresh cookie (exactly like /auth/login) and bounces to the frontend, which mints
# the in-memory access token via /auth/refresh — the same path used on page reload.
# Keeps the token out of browser history / logs and reuses the proven refresh flow.

import logging
import os
from datetime import datetime

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import (
    FRONTEND_URL,
    PUBLIC_API_URL,
    create_access_token,  # noqa: F401 (kept for symmetry / future use)
    create_refresh_token,
    _hash_refresh_token,
)
from app.db import get_db
from app.social_auth import resolve_social_login

logger = logging.getLogger("oauth")
router = APIRouter()

# Refresh cookie is Secure only when the API is served over https (prod). On
# http://localhost dev it must stay non-Secure or the browser drops it.
_COOKIE_SECURE = PUBLIC_API_URL.startswith("https")

oauth = OAuth()
_CONFIGURED: set[str] = set()

_GOOGLE_ID = os.getenv("GOOGLE_CLIENT_ID")
_GOOGLE_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
if _GOOGLE_ID and _GOOGLE_SECRET:
    oauth.register(
        name="google",
        client_id=_GOOGLE_ID,
        client_secret=_GOOGLE_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    _CONFIGURED.add("google")


def _client(provider: str):
    if provider not in _CONFIGURED:
        raise HTTPException(status_code=404, detail=f"Sign-in provider '{provider}' is not available.")
    return oauth.create_client(provider)


@router.get("/{provider}/start")
async def oauth_start(provider: str, request: Request):
    """Kick off the authorization-code flow: stash state+nonce in the session cookie
    and 302 the browser to the provider's consent screen."""
    client = _client(provider)
    redirect_uri = f"{PUBLIC_API_URL}/auth/oauth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback")
async def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    """Provider redirects back here with a code. Exchange it, verify the ID token,
    resolve/create the Rowbound user, set the refresh cookie, bounce to the frontend."""
    client = _client(provider)
    try:
        token = await client.authorize_access_token(request)  # verifies state; exchanges code
    except OAuthError as exc:
        logger.warning("oauth callback error for %s: %s", provider, exc)
        return RedirectResponse(url=f"{FRONTEND_URL}/login?error=oauth", status_code=302)

    # With `openid` scope authlib parses + nonce-validates the ID token into userinfo.
    claims = token.get("userinfo")
    if not claims:
        return RedirectResponse(url=f"{FRONTEND_URL}/login?error=oauth", status_code=302)

    subject = claims.get("sub")
    if not subject:
        return RedirectResponse(url=f"{FRONTEND_URL}/login?error=oauth", status_code=302)

    try:
        user = resolve_social_login(
            db,
            provider=provider,
            subject=subject,
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified")),
        )
    except HTTPException:
        # Only reachable on an unverified provider email (resolve_social_login raises
        # 403). Send them back to log in another way rather than surfacing a raw 403.
        return RedirectResponse(url=f"{FRONTEND_URL}/login?error=unverified_email", status_code=302)

    # Issue the session exactly like /auth/login: one active refresh token, hashed.
    refresh = create_refresh_token(user.id)
    user.refresh_token_hash = _hash_refresh_token(refresh)
    user.last_login_at = datetime.utcnow()
    db.commit()

    resp = RedirectResponse(url=f"{FRONTEND_URL}/auth/social", status_code=302)
    resp.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
    )
    return resp
