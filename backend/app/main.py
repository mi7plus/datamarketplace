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
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")  # load variables from .env
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

app = FastAPI(title="DataMarketplace API")


# Liveness probe for the ALB target group + Docker HEALTHCHECK. Dependency-free
# (no DB call) so a transient DB blip doesn't flap the load balancer.
@app.get("/health")
def health_check():
    return {"status": "ok"}


# Deep readiness check — NOT wired to the load balancer. Use for diagnostics only.
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


# Allow CORS
origins = [
    frontend_url,
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,          # explicit origins — never "*" (required with credentials)
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


# Background auto-release sweep: pays out ACCEPTED submissions whose acceptance
# window has elapsed with no open dispute, even if the buyer never returns.
_scheduler = None


@app.on_event("startup")
def _start_sweep():
    global _scheduler
    from app.sweep import start_scheduler
    _scheduler = start_scheduler()


@app.on_event("shutdown")
def _stop_sweep():
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)