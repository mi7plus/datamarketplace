# tests/test_cors_origins.py
# CORS must allow both apex and www of FRONTEND_URL (the site is reached at both
# rowbound.com and www.rowbound.com), plus localhost. Never "*".

from app.main import cors_origins


def test_apex_also_allows_www():
    o = cors_origins({"FRONTEND_URL": "https://rowbound.com"})
    assert "https://rowbound.com" in o
    assert "https://www.rowbound.com" in o
    assert "http://localhost:3000" in o
    assert "*" not in o


def test_www_also_allows_apex():
    o = cors_origins({"FRONTEND_URL": "https://www.rowbound.com"})
    assert "https://rowbound.com" in o
    assert "https://www.rowbound.com" in o


def test_comma_separated_list_and_trailing_slash():
    o = cors_origins({"FRONTEND_URL": "https://rowbound.com/, https://staging.rowbound.com"})
    assert "https://rowbound.com" in o          # trailing slash stripped
    assert "https://staging.rowbound.com" in o


def test_unset_is_localhost_only():
    assert cors_origins({}) == ["http://localhost:3000"]
