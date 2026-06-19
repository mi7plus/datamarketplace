# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth import router as auth_router
from app.requests import router as requests_router
from app.submissions import router as submissions_router
from app.profile import router as profile_router
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")  # load variables from .env
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

app = FastAPI(title="DataMarketplace API")

# Allow CORS
origins = [
    frontend_url,
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # GET, POST, etc
    allow_headers=["*"],  # all headers
)

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(requests_router, prefix="/requests", tags=["requests"])
app.include_router(submissions_router, prefix="/submissions", tags=["submissions"])
app.include_router(profile_router, prefix="/profile", tags=["profile"])