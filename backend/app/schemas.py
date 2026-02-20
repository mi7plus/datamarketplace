# app/schemas.py
from pydantic import BaseModel, Field, EmailStr
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

class ProfileCreate(BaseModel):
    user_type: str = Field(..., alias="user_type")      # frontend already sends this correctly
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    company_name: Optional[str] = Field(None, alias="companyName")
    email: str
    phone: Optional[str]
    address: Optional[str]

    class Config:
        allow_population_by_field_name = True