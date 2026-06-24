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