# app/admin_authz.py
#
# The admin panel's authorization core (admin panel design §3, §5). This is the
# highest-privilege surface in the app, so the access model is centralized HERE —
# one place decides "can this admin role do X" — rather than scattered per-route.
# That keeps the role→capability mapping auditable and leaves an Option-B (per-
# permission) migration open without committing to it now.
#
# Model: Option A fixed sub-roles. admin_role is orthogonal to UserRole; NULL = not
# an admin. Capabilities are string constants; each role maps to a fixed set.

import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import get_current_user, verify_totp
from app.db import get_db
from app.models import AdminRole, UserAuth as User

# ---------------------------------------------------------------------------
# Capabilities (string constants — one per discrete admin power)
# ---------------------------------------------------------------------------

# Tier 1 — observe (granted to every admin role)
CAP_VIEW = "view"                       # dashboard, users, activity, audit, metrics

# Tier 2 — support actions (state changes, all audited)
CAP_DISPUTE_RESOLVE = "dispute.resolve"
CAP_TXN_REFUND = "txn.refund"
CAP_USER_UNLOCK = "user.unlock"
CAP_USER_VERIFY_RESEND = "user.verify_resend"
CAP_USER_SUSPEND = "user.suspend"
CAP_USER_MFA_RESET = "user.mfa_reset"
CAP_DATASET_QUARANTINE = "dataset.quarantine"

# Admin management (Tier 3-adjacent — grant/revoke admin roles)
CAP_ADMIN_MANAGE = "admin.manage"

# Every admin role gets the Tier-1 observe capability.
_TIER1 = {CAP_VIEW}

# Role → capability set. SUPER_ADMIN is computed as "everything".
_ALL_CAPS = {
    CAP_VIEW, CAP_DISPUTE_RESOLVE, CAP_TXN_REFUND, CAP_USER_UNLOCK,
    CAP_USER_VERIFY_RESEND, CAP_USER_SUSPEND, CAP_USER_MFA_RESET,
    CAP_DATASET_QUARANTINE, CAP_ADMIN_MANAGE,
}

CAPABILITIES: dict[AdminRole, set[str]] = {
    AdminRole.SUPER_ADMIN: set(_ALL_CAPS),
    AdminRole.SUPPORT_LEAD: _TIER1 | {
        CAP_DISPUTE_RESOLVE, CAP_TXN_REFUND, CAP_USER_UNLOCK,
        CAP_USER_VERIFY_RESEND, CAP_USER_SUSPEND, CAP_USER_MFA_RESET,
        CAP_DATASET_QUARANTINE,
    },
    AdminRole.SUPPORT_AGENT: _TIER1 | {
        CAP_USER_UNLOCK, CAP_USER_VERIFY_RESEND, CAP_DATASET_QUARANTINE,
    },
    AdminRole.READ_ONLY: set(_TIER1),
}

# Sensitive actions that require step-up (re-enter a fresh TOTP) when the admin has
# MFA enabled (design §5). These move money, reset another user's MFA, or change who
# holds admin power.
STEP_UP_CAPS = {CAP_TXN_REFUND, CAP_USER_MFA_RESET, CAP_ADMIN_MANAGE}


def role_has(admin_role: AdminRole | None, cap: str) -> bool:
    if admin_role is None:
        return False
    return cap in CAPABILITIES.get(admin_role, set())


def capabilities_for(admin_role: AdminRole | None) -> list[str]:
    return sorted(CAPABILITIES.get(admin_role, set())) if admin_role else []


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def _require_admin_mfa() -> bool:
    # Mandatory MFA for admins (design §5). Behind a flag so dev/CI (and a fresh
    # bootstrap admin who hasn't enrolled yet) aren't bricked; enable in prod.
    return os.getenv("REQUIRE_ADMIN_MFA", "false").lower() == "true"


def current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Base admin gate: the user must hold an admin_role. When REQUIRE_ADMIN_MFA is
    on, they must also have MFA enabled (enroll via /auth/mfa first). A non-admin
    gets 403 — role denial doesn't leak object existence, so 403 is correct here."""
    if getattr(user, "admin_role", None) is None:
        raise HTTPException(status_code=403, detail="Admin access required")
    if _require_admin_mfa() and not user.mfa_enabled:
        raise HTTPException(
            status_code=403,
            detail="Admin accounts must enable MFA before using the admin panel.",
        )
    return user


def require_capability(cap: str):
    """Dependency factory: gate an admin route on a specific capability. For step-up
    capabilities, also require a valid current TOTP code (header X-MFA-Code or body)
    when the admin has MFA enabled."""
    def _dep(
        request: Request,
        admin: User = Depends(current_admin),
    ) -> User:
        if not role_has(admin.admin_role, cap):
            raise HTTPException(status_code=403, detail=f"Your admin role lacks '{cap}'")
        if cap in STEP_UP_CAPS and admin.mfa_enabled:
            code = request.headers.get("x-mfa-code")
            if not verify_totp(admin, code):
                raise HTTPException(
                    status_code=401,
                    detail="This action requires re-entering your MFA code (X-MFA-Code).",
                )
        return admin
    return _dep
