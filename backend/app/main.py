# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth import router as auth_router
from app.requests import router as requests_router
from app.submissions import router as submissions_router
from app.profile import router as profile_router
from app.webhooks import router as webhooks_router
from app.reviews import router as reviews_router
from app.disputes import router as disputes_router
from app.listings import router as listings_router, purchases_router
from app.collect import router as collect_router
from app.metrics import router as metrics_router
from app.contact import router as contact_router
from app.internal import router as internal_router
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")  # load variables from .env


def cors_origins(env: dict | None = None) -> list[str]:
    """Allowed CORS origins. FRONTEND_URL may be a comma-separated list; for every
    https origin we also allow its www↔apex counterpart, since the site is reached
    at both rowbound.com and www.rowbound.com. localhost stays allowed for dev.
    Exact origins only — never '*' (required with allow_credentials=True)."""
    env = env if env is not None else os.environ
    raw = env.get("FRONTEND_URL", "http://localhost:3000")
    out: set[str] = set()
    for o in raw.split(","):
        o = o.strip().rstrip("/")
        if not o:
            continue
        out.add(o)
        if o.startswith("https://"):
            host = o[len("https://"):]
            counterpart = host[4:] if host.startswith("www.") else "www." + host
            out.add("https://" + counterpart)
    out.add("http://localhost:3000")
    return sorted(out)


frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

app = FastAPI(title="DataMarketplace API")


# Liveness probe for the ALB target group + Docker HEALTHCHECK. Dependency-free
# (no DB call) so a transient DB blip doesn't flap the load balancer.
@app.get("/health")
def health_check():
    return {"status": "ok"}


# Deep readiness check — NOT wired to the load balancer; diagnostics only.
@app.get("/health/db")
def health_db():
    from sqlalchemy import text
    from app.db import SessionLocal
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "up"}
    except Exception:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"status": "error", "db": "down"})


# Allow CORS — explicit origins (apex + www of FRONTEND_URL, plus localhost) AND a
# regex that matches any https subdomain of the production domain. The regex makes
# CORS robust even if the deployed FRONTEND_URL env is stale/wrong (e.g. www. vs
# apex), which is exactly what bit us. Still never "*" (required with credentials).
origins = cors_origins()
cors_origin_regex = os.getenv(
    "CORS_ALLOW_ORIGIN_REGEX", r"https://([a-z0-9-]+\.)*rowbound\.com"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],  # GET, POST, etc
    allow_headers=["*"],  # all headers
)


@app.middleware("http")
async def security_headers(request, call_next):
    """Baseline security headers on every API response (S6). nosniff matters most
    for an API that hands out files/JSON; HSTS is honoured once served over HTTPS."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(requests_router, prefix="/requests", tags=["requests"])
app.include_router(submissions_router, prefix="/submissions", tags=["submissions"])
app.include_router(profile_router, prefix="/profile", tags=["profile"])
app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(reviews_router, prefix="/reviews", tags=["reviews"])
app.include_router(disputes_router, prefix="/disputes", tags=["disputes"])
app.include_router(listings_router, prefix="/listings", tags=["listings"])
app.include_router(purchases_router, prefix="/purchases", tags=["purchases"])
app.include_router(collect_router, prefix="/collect", tags=["collect"])
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
app.include_router(contact_router, prefix="/contact", tags=["contact"])
# Internal-only: Rust ingest result callback. Not exposed on the public gateway.
app.include_router(internal_router, prefix="/internal", tags=["internal"])


# Background auto-release sweep: pays out ACCEPTED submissions whose acceptance
# window has elapsed with no open dispute, even if the buyer never returns.
_scheduler = None


@app.on_event("startup")
def _start_sweep():
    global _scheduler
    # OFF by default. In prod the auto-release sweep is run by a SINGLE
    # EventBridge-triggered task; an in-process scheduler here would run it on every
    # API container (×2 tasks) concurrently with EventBridge — a double-payout risk.
    # Only enable the in-process sweep for local dev via RUN_INPROCESS_SWEEP=true.
    if os.getenv("RUN_INPROCESS_SWEEP", "false").lower() != "true":
        return
    from app.sweep import start_scheduler
    _scheduler = start_scheduler()


@app.on_event("shutdown")
def _stop_sweep():
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)