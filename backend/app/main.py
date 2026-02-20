# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth import router as auth_router
from app.requests import router as requests_router
from app.submissions import router as submissions_router
from app.profile import router as profile_router
from dotenv import load_dotenv
import os

app = FastAPI(title="DataMarketplace API")

load_dotenv()  # load variables from .env
frontend_url = os.getenv("FRONTEND_URL")


# Allow CORS
origins = [
    frontend_url
    # you can add more origins here, or use "*" for any origin (not recommended for production)
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