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
    create_access_token,  # noqa: F401 (kept for symmetry / future use)
    create_refresh_token,
    _hash_refresh_token,
)
from app.db import get_db
from app.social_auth import resolve_social_login

logger = logging.getLogger("oauth")
router = APIRouter()

# Where each provider's OIDC discovery lives.
# Microsoft: the `organizations` authority = work/school (Entra) accounts only, NOT
# personal Microsoft accounts (§7.4 decision). `common` would also admit personal MSA.
_DISCOVERY = {
    "google": "https://accounts.google.com/.well-known/openid-configuration",
    "microsoft": "https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration",
}

# Env var names holding each provider's client id/secret.
_CREDS = {
    "google": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "microsoft": ("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"),
}

oauth = OAuth()
_registered: set[str] = set()


def _public_api_url() -> str:
    # Read fresh (not captured at import) so it always reflects the injected task env.
    return os.getenv("PUBLIC_API_URL", "http://localhost:3001").rstrip("/")


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").split(",")[0].rstrip("/")


def _configured_providers() -> list[str]:
    """Providers whose client id AND secret are present in the environment right now.
    Read live from os.environ — the creds come from the injected prod secret, never a
    .env file, so registration must not depend on import-time or file state."""
    out = []
    for name, (id_var, secret_var) in _CREDS.items():
        if os.getenv(id_var) and os.getenv(secret_var):
            out.append(name)
    return out


def _client(provider: str):
    """Lazily register + return the authlib client for a provider. 404 if its creds
    aren't in the environment. Registration is deferred to first use so it can never
    be defeated by import ordering or a missing .env — it only asks os.environ."""
    if provider not in _configured_providers():
        raise HTTPException(status_code=404, detail=f"Sign-in provider '{provider}' is not available.")
    if provider not in _registered:
        id_var, secret_var = _CREDS[provider]
        oauth.register(
            name=provider,
            client_id=os.getenv(id_var),
            client_secret=os.getenv(secret_var),
            server_metadata_url=_DISCOVERY[provider],
            client_kwargs={"scope": "openid email profile"},
        )
        _registered.add(provider)
    return oauth.create_client(provider)


@router.get("/providers")
def list_providers():
    """Diagnostics: which social providers are actually configured in THIS running
    container (no secrets leaked — just names). Lets you confirm the prod task env has
    the creds without shelling in."""
    return {"configured": _configured_providers()}


@router.get("/{provider}/start")
async def oauth_start(provider: str, request: Request):
    """Kick off the authorization-code flow: stash state+nonce in the session cookie
    and 302 the browser to the provider's consent screen."""
    client = _client(provider)
    redirect_uri = f"{_public_api_url()}/auth/oauth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


def _claim_true(v) -> bool:
    """A claim is 'true' whether it arrives as a JSON bool or a string. (bool('false')
    is True in Python, so never rely on truthiness for string claims.)"""
    return v is True or v == 1 or (isinstance(v, str) and v.strip().lower() in {"true", "1"})


def _extract_identity(provider: str, claims: dict) -> tuple[str | None, str | None, bool]:
    """Pull (subject, email, email_verified) from a provider's ID-token claims.

    Google is standard OIDC — honour its `email_verified`.

    Microsoft ID tokens carry NO `email_verified`. We already restrict to the
    `organizations` authority (work/school tenants only). The strong signal that a
    tenant actually owns the email's domain is `xms_edov` (email-domain-owner-verified);
    when true, the email is safe to link on. Tenants that don't emit that optional claim
    fall back to "trusted because it's a work/school account" — UNLESS
    MICROSOFT_REQUIRE_EDOV=true, which enforces the stronger check (and will 403 logins
    from tenants that don't send xms_edov). `preferred_username` is the UPN fallback when
    no `email` claim is present."""
    subject = claims.get("sub")
    if provider == "microsoft":
        email = (claims.get("email") or claims.get("preferred_username") or "").strip() or None
        if _claim_true(claims.get("xms_edov")):
            verified = True
        else:
            verified = os.getenv("MICROSOFT_REQUIRE_EDOV", "false").lower() != "true"
        return subject, email, verified
    return subject, claims.get("email"), bool(claims.get("email_verified"))


@router.get("/{provider}/callback")
async def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    """Provider redirects back here with a code. Exchange it, verify the ID token,
    resolve/create the Rowbound user, set the refresh cookie, bounce to the frontend."""
    client = _client(provider)
    frontend = _frontend_url()
    try:
        token = await client.authorize_access_token(request)  # verifies state; exchanges code
    except OAuthError as exc:
        logger.warning("oauth callback error for %s: %s", provider, exc)
        return RedirectResponse(url=f"{frontend}/login?error=oauth", status_code=302)

    # With `openid` scope authlib parses + nonce-validates the ID token into userinfo.
    claims = token.get("userinfo")
    if not claims:
        return RedirectResponse(url=f"{frontend}/login?error=oauth", status_code=302)

    subject, email, email_verified = _extract_identity(provider, claims)
    if not subject:
        return RedirectResponse(url=f"{frontend}/login?error=oauth", status_code=302)

    try:
        user = resolve_social_login(
            db,
            provider=provider,
            subject=subject,
            email=email,
            email_verified=email_verified,
        )
    except HTTPException:
        # Only reachable on an unverified provider email (resolve_social_login raises
        # 403). Send them back to log in another way rather than surfacing a raw 403.
        return RedirectResponse(url=f"{frontend}/login?error=unverified_email", status_code=302)

    # Issue the session exactly like /auth/login: one active refresh token, hashed.
    refresh = create_refresh_token(user.id)
    user.refresh_token_hash = _hash_refresh_token(refresh)
    user.last_login_at = datetime.utcnow()
    db.commit()

    resp = RedirectResponse(url=f"{frontend}/auth/social", status_code=302)
    resp.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=_public_api_url().startswith("https"),
        samesite="lax",
    )
    return resp
