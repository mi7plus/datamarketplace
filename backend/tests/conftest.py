# tests/conftest.py
# Load the backend .env so real-DB tests (test_allocation_race.py,
# test_dedup_real_db.py) can read POSTGRES_* and connect to a live Postgres.
# Pure-unit tests are unaffected — they don't touch these vars.

from pathlib import Path
from dotenv import load_dotenv

# backend/.env lives one level up from tests/
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH, override=False)
