# app/main.py
from fastapi import FastAPI
from app.auth import router as auth_router
from app.requests import router as requests_router
from app.submissions import router as submissions_router

app = FastAPI(title="DataMarketplace API")

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(requests_router, prefix="/requests", tags=["requests"])
app.include_router(submissions_router, prefix="/submissions", tags=["submissions"])