from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

DB_USER = os.getenv("POSTGRES_USER")
DB_PASS = os.getenv("POSTGRES_PASSWORD")
DB_NAME = os.getenv("POSTGRES_DB")
DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = os.getenv("POSTGRES_PORT")

SQLALCHEMY_DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --- In-transit encryption: app -> Postgres TLS (E1.3) ------------------------
# The connection is NOT TLS-forced by default, which is the in-transit gap the
# encryption track calls out. DB_SSLMODE controls it; psycopg2 honours these via
# connect_args. For RDS in prod set DB_SSLMODE=verify-full and point
# DB_SSLROOTCERT at the RDS CA bundle so the server cert is actually validated
# (require alone encrypts but does not authenticate the server).
#
# Default is "prefer" so local/dev Postgres and CI (plaintext) keep working;
# production .env MUST raise this to "require" or "verify-full".
DB_SSLMODE = os.getenv("DB_SSLMODE", "prefer")
DB_SSLROOTCERT = os.getenv("DB_SSLROOTCERT")  # path to RDS CA bundle (verify-full)


def assert_db_tls_policy(env: dict | None = None) -> None:
    """Fail closed in production (C3). 'prefer' silently falls back to plaintext and
    never validates the server cert — fine for dev, dangerous in prod. When
    APP_ENV/ENVIRONMENT is prod[uction], refuse to boot unless DB_SSLMODE forces
    TLS ('require' or 'verify-full'), and require the CA bundle for 'verify-full'.
    Any other APP_ENV (dev/CI) is unaffected, so plaintext local Postgres works."""
    env = env if env is not None else os.environ
    app_env = (env.get("APP_ENV") or env.get("ENVIRONMENT") or "").lower()
    if app_env not in ("prod", "production"):
        return
    sslmode = env.get("DB_SSLMODE", "prefer")
    if sslmode not in ("require", "verify-full"):
        raise RuntimeError(
            f"Refusing to start: APP_ENV is production but DB_SSLMODE is {sslmode!r}. "
            "Set DB_SSLMODE=verify-full (preferred) or 'require' to force TLS to Postgres."
        )
    if sslmode == "verify-full" and not env.get("DB_SSLROOTCERT"):
        raise RuntimeError(
            "Refusing to start: DB_SSLMODE=verify-full requires DB_SSLROOTCERT "
            "(the RDS CA bundle path) to validate the server certificate."
        )


assert_db_tls_policy()  # fail closed before opening any connection

_connect_args: dict = {"sslmode": DB_SSLMODE}
if DB_SSLROOTCERT:
    _connect_args["sslrootcert"] = DB_SSLROOTCERT

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency to use in endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()