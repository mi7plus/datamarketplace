# tests/test_admin_panel.py
# Admin panel — RBAC foundation + Tier 1 (observe) + Tier 2 (actions).
# The security core is the capability model and the audit trail, so that's what's
# tested hardest here: role→capability gating, step-up, suspend-blocks-login, audit.

import uuid
import pytest
import pyotp
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import UserAuth, AdminRole, AuditLog
from app.admin_authz import (
    role_has, CAP_VIEW, CAP_USER_UNLOCK, CAP_TXN_REFUND, CAP_USER_SUSPEND,
    CAP_ADMIN_MANAGE, CAP_DATASET_QUARANTINE,
)
from tests.test_allocation_race import DB_URL

pytestmark = pytest.mark.skipif(DB_URL is None, reason="POSTGRES_* not set")
client = TestClient(app)


def _sx():
    return uuid.uuid4().hex[:8]


def _register(email, role="requester"):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})


def _login(email):
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _set(email, **attrs):
    db = SessionLocal()
    try:
        u = db.query(UserAuth).filter(UserAuth.email == email).first()
        for k, v in attrs.items():
            setattr(u, k, v)
        db.commit()
        return str(u.id)
    finally:
        db.close()


def _mk_admin(role: AdminRole):
    email = f"adm_{_sx()}@t.io"
    _register(email, "admin")
    _set(email, admin_role=role)
    return email, _login(email)


def _cleanup(*emails):
    db = SessionLocal()
    try:
        for e in emails:
            u = db.query(UserAuth).filter(UserAuth.email == e).first()
            if u:
                db.query(AuditLog).filter(AuditLog.actor_id == str(u.id)).delete()
                db.delete(u)
        db.commit()
    finally:
        db.close()


# ---- capability model (pure) ----------------------------------------------

def test_capability_matrix():
    assert role_has(AdminRole.SUPER_ADMIN, CAP_ADMIN_MANAGE)
    assert role_has(AdminRole.SUPPORT_LEAD, CAP_TXN_REFUND)
    assert not role_has(AdminRole.SUPPORT_LEAD, CAP_ADMIN_MANAGE)
    assert role_has(AdminRole.SUPPORT_AGENT, CAP_USER_UNLOCK)
    assert not role_has(AdminRole.SUPPORT_AGENT, CAP_TXN_REFUND)
    assert not role_has(AdminRole.SUPPORT_AGENT, CAP_USER_SUSPEND)
    assert role_has(AdminRole.READ_ONLY, CAP_VIEW)
    assert not role_has(AdminRole.READ_ONLY, CAP_USER_UNLOCK)
    assert not role_has(None, CAP_VIEW)


# ---- gate: non-admin & me --------------------------------------------------

def test_non_admin_forbidden_and_me():
    plain = f"u_{_sx()}@t.io"
    _register(plain, "requester")
    try:
        assert client.get("/admin/users", headers=_login(plain)).status_code == 403
        email, H = _mk_admin(AdminRole.READ_ONLY)
        me = client.get("/admin/me", headers=H).json()
        assert me["admin_role"] == "read_only" and me["capabilities"] == ["view"]
        _cleanup(email)
    finally:
        _cleanup(plain)


# ---- Tier 1 observe --------------------------------------------------------

def test_readonly_can_view_users_but_not_act():
    email, H = _mk_admin(AdminRole.READ_ONLY)
    target = f"t_{_sx()}@t.io"; _register(target)
    tid = _set(target)
    try:
        assert client.get("/admin/users", headers=H).status_code == 200
        assert client.get(f"/admin/users/{tid}", headers=H).status_code == 200
        assert client.get(f"/admin/users/{tid}/activity", headers=H).status_code == 200
        # read-only lacks every Tier-2 capability
        r = client.post(f"/admin/users/{tid}/unlock", headers=H, json={"reason": "x"})
        assert r.status_code == 403
    finally:
        _cleanup(email, target)


# ---- Tier 2 actions + audit ------------------------------------------------

def test_agent_unlock_writes_audit_but_cannot_refund_or_suspend():
    email, H = _mk_admin(AdminRole.SUPPORT_AGENT)
    target = f"t_{_sx()}@t.io"; _register(target)
    tid = _set(target, account_locked=True, failed_login_attempts=9)
    try:
        r = client.post(f"/admin/users/{tid}/unlock", headers=H, json={"reason": "cleared"})
        assert r.status_code == 200 and r.json()["account_locked"] is False
        # audit written
        db = SessionLocal()
        try:
            n = db.query(AuditLog).filter(
                AuditLog.action == "admin.user_unlock", AuditLog.object_id == tid
            ).count()
            assert n == 1
        finally:
            db.close()
        # agent can't refund or suspend
        assert client.post(f"/admin/users/{tid}/suspend", headers=H, json={"reason": "x"}).status_code == 403
        assert client.post(f"/admin/submissions/{uuid.uuid4()}/refund", headers=H, json={}).status_code == 403
    finally:
        _cleanup(email, target)


def test_lead_suspend_blocks_login_then_reactivate():
    email, H = _mk_admin(AdminRole.SUPPORT_LEAD)
    target = f"t_{_sx()}@t.io"; _register(target)
    tid = _set(target)
    try:
        assert client.post("/auth/login", json={"email": target, "password": "pw123456"}).status_code == 200
        assert client.post(f"/admin/users/{tid}/suspend", headers=H, json={"reason": "abuse"}).status_code == 200
        # suspended → login 403
        assert client.post("/auth/login", json={"email": target, "password": "pw123456"}).status_code == 403
        assert client.post(f"/admin/users/{tid}/reactivate", headers=H, json={"reason": "ok"}).status_code == 200
        assert client.post("/auth/login", json={"email": target, "password": "pw123456"}).status_code == 200
    finally:
        _cleanup(email, target)


def test_cannot_suspend_an_admin():
    email, H = _mk_admin(AdminRole.SUPPORT_LEAD)
    other, _ = _mk_admin(AdminRole.READ_ONLY)
    oid = _set(other)
    try:
        assert client.post(f"/admin/users/{oid}/suspend", headers=H, json={"reason": "x"}).status_code == 409
    finally:
        _cleanup(email, other)


def test_refund_capability_passes_then_404_for_missing_submission():
    email, H = _mk_admin(AdminRole.SUPPORT_LEAD)   # has CAP_TXN_REFUND, mfa off → no step-up
    try:
        r = client.post(f"/admin/submissions/{uuid.uuid4()}/refund", headers=H, json={"amount": 5})
        assert r.status_code == 404   # capability ok, submission just doesn't exist
    finally:
        _cleanup(email)


# ---- admin management + step-up -------------------------------------------

def test_super_admin_grants_and_revokes_role():
    email, H = _mk_admin(AdminRole.SUPER_ADMIN)
    target = f"t_{_sx()}@t.io"; _register(target)
    tid = _set(target)
    try:
        r = client.post(f"/admin/users/{tid}/admin-role", headers=H,
                        json={"admin_role": "support_agent", "reason": "promote"})
        assert r.status_code == 200 and r.json()["admin_role"] == "support_agent"
        # revoke
        r2 = client.post(f"/admin/users/{tid}/admin-role", headers=H,
                         json={"admin_role": None, "reason": "revoke"})
        assert r2.status_code == 200 and r2.json()["admin_role"] is None
    finally:
        _cleanup(email, target)


def test_cannot_revoke_own_super_admin():
    email, H = _mk_admin(AdminRole.SUPER_ADMIN)
    sid = _set(email)
    try:
        r = client.post(f"/admin/users/{sid}/admin-role", headers=H, json={"admin_role": "read_only"})
        assert r.status_code == 409
    finally:
        _cleanup(email)


def test_lead_cannot_manage_admins():
    email, H = _mk_admin(AdminRole.SUPPORT_LEAD)
    target = f"t_{_sx()}@t.io"; _register(target)
    tid = _set(target)
    try:
        r = client.post(f"/admin/users/{tid}/admin-role", headers=H, json={"admin_role": "read_only"})
        assert r.status_code == 403
    finally:
        _cleanup(email, target)


def test_step_up_required_when_mfa_enabled():
    email, H = _mk_admin(AdminRole.SUPER_ADMIN)
    secret = pyotp.random_base32()
    _set(email, mfa_secret=secret, mfa_enabled=True)
    target = f"t_{_sx()}@t.io"; _register(target)
    tid = _set(target)
    try:
        # sensitive action (admin.manage) with MFA on but no code → 401 step-up
        r = client.post(f"/admin/users/{tid}/admin-role", headers=H, json={"admin_role": "read_only"})
        assert r.status_code == 401
        # with a valid TOTP code → allowed
        code = pyotp.TOTP(secret).now()
        r2 = client.post(f"/admin/users/{tid}/admin-role",
                         headers={**H, "X-MFA-Code": code}, json={"admin_role": "read_only"})
        assert r2.status_code == 200
    finally:
        _cleanup(email, target)
