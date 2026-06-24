# tests/test_db_tls_policy.py
# C3: production DB TLS must fail closed. assert_db_tls_policy takes an explicit
# env dict so these are deterministic (no process-env mutation).

import pytest
from app.db import assert_db_tls_policy


def test_dev_is_unaffected():
    # No APP_ENV / non-prod → anything goes (plaintext local Postgres).
    assert_db_tls_policy({})
    assert_db_tls_policy({"APP_ENV": "dev", "DB_SSLMODE": "prefer"})


@pytest.mark.parametrize("mode", ["prefer", "allow", "disable", None])
def test_prod_refuses_weak_sslmode(mode):
    env = {"APP_ENV": "prod"}
    if mode is not None:
        env["DB_SSLMODE"] = mode
    with pytest.raises(RuntimeError, match="force TLS"):
        assert_db_tls_policy(env)


def test_prod_verify_full_requires_ca_bundle():
    with pytest.raises(RuntimeError, match="DB_SSLROOTCERT"):
        assert_db_tls_policy({"APP_ENV": "production", "DB_SSLMODE": "verify-full"})


def test_prod_accepts_require_and_verify_full():
    assert_db_tls_policy({"APP_ENV": "prod", "DB_SSLMODE": "require"})
    assert_db_tls_policy({
        "ENVIRONMENT": "production",
        "DB_SSLMODE": "verify-full",
        "DB_SSLROOTCERT": "/etc/ssl/rds-ca.pem",
    })
