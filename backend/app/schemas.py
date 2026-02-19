# app/schemas.py
from pydantic import BaseModel, EmailStr
from typing import Optional

# Auth
class RegisterSchema(BaseModel):
    email: EmailStr
    password: str
    role: str  # "requester" or "provider"

class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class TokenSchema(BaseModel):
    access_token: str

# Data Requests
class DataRequestCreateSchema(BaseModel):
    title: str
    description: Optional[str]
    required_format: str
    amount_required: int
    budget: float

# Submissions
class SubmissionCreateSchema(BaseModel):
    request_id: int
    content_link: str
    amount_provided: int