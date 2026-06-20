# tests/conftest.py
# Load the backend .env so real-DB tests (test_allocation_race.py,
# test_dedup_real_db.py) can read POSTGRES_* and connect to a live Postgres.
# Pure-unit tests are unaffected — they don't touch these vars.

import os
from pathlib import Path
from dotenv import load_dotenv

# backend/.env lives one level up from tests/
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH, override=False)

# Disable the per-IP auth rate limiter for the suite — all TestClient traffic
# shares one client IP, so the limiter would otherwise throttle unrelated tests.
# The dedicated rate-limit test re-enables it explicitly.
os.environ.setdefault("RATELIMIT_ENABLED", "false")
