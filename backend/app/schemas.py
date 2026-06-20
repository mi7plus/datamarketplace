# app/schemas.py
from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator
from typing import Optional, List, Literal
from uuid import UUID


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class RegisterSchema(BaseModel):
    email: EmailStr
    password: str
    role: str  # "requester" or "provider"

class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class TokenSchema(BaseModel):
    access_token: str


# ---------------------------------------------------------------------------
# Request spec — structured schema columns
# ---------------------------------------------------------------------------

ALLOWED_COLUMN_TYPES = {"string", "integer", "float", "boolean", "date", "datetime"}

class SpecColumn(BaseModel):
    name: str
    type: Literal["string", "integer", "float", "boolean", "date", "datetime"]
    required: bool = True

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Column name must not be empty")
        return v.strip()


class RequestSpec(BaseModel):
    columns: List[SpecColumn]
    unique_key: Optional[List[str]] = None   # column name(s) identifying a unique record

    @field_validator("columns")
    @classmethod
    def at_least_one_column(cls, v: List[SpecColumn]) -> List[SpecColumn]:
        if len(v) < 1:
            raise ValueError("Spec must have at least one column")
        return v

    @model_validator(mode="after")
    def unique_key_columns_exist(self) -> "RequestSpec":
        if self.unique_key:
            col_names = {c.name for c in self.columns}
            missing = [k for k in self.unique_key if k not in col_names]
            if missing:
                raise ValueError(f"unique_key references unknown columns: {missing}")
        return self


# ---------------------------------------------------------------------------
# Collection (Mode 3) form spec
# ---------------------------------------------------------------------------

class CollectionField(BaseModel):
    name: str
    type: Literal["string", "integer", "float", "boolean", "date", "datetime"]
    required: bool = True


class CollectionSpec(BaseModel):
    """Form spec for a Collect-mode request: what agents fill in, plus the field
    QA requirements (geo-stamp, photo evidence, consent/lawful-basis)."""
    fields: List[CollectionField]
    unique_key: Optional[List[str]] = None      # dedup key across collected entries
    geo_required: bool = False
    photo_required: bool = False
    consent_required: bool = False
    coverage: Optional[List[str]] = None        # coverage units, e.g. regions / SKUs

    @field_validator("fields")
    @classmethod
    def at_least_one_field(cls, v):
        if len(v) < 1:
            raise ValueError("Collection spec must have at least one field")
        return v

    @model_validator(mode="after")
    def unique_key_fields_exist(self) -> "CollectionSpec":
        if self.unique_key:
            names = {f.name for f in self.fields}
            missing = [k for k in self.unique_key if k not in names]
            if missing:
                raise ValueError(f"unique_key references unknown fields: {missing}")
        return self


# ---------------------------------------------------------------------------
# Data Requests
# ---------------------------------------------------------------------------

class DataRequestCreateSchema(BaseModel):
    title: str
    description: Optional[str] = None
    unit: str                           # e.g. "row", "record", "image"
    amount_required: int
    pricing_mode: Literal["per_unit", "fixed_bounty"] = "per_unit"
    price_per_unit: Optional[float] = None
    budget: Optional[float] = None      # derived for per_unit; required for fixed_bounty
    required_format: Literal["csv", "jsonl"] = "csv"
    spec: Optional[RequestSpec] = None
    mode: Literal["request", "collect"] = "request"
    collection_spec: Optional[CollectionSpec] = None
    deadline: Optional[str] = None      # ISO datetime string; stored as DateTime
    license_id: Optional[UUID] = None

    @model_validator(mode="after")
    def validate_mode(self) -> "DataRequestCreateSchema":
        if self.mode == "collect" and self.collection_spec is None:
            raise ValueError("collection_spec is required for collect-mode requests")
        return self

    @model_validator(mode="after")
    def validate_pricing(self) -> "DataRequestCreateSchema":
        if self.pricing_mode == "per_unit":
            if not self.price_per_unit or self.price_per_unit <= 0:
                raise ValueError("price_per_unit must be a positive number for per_unit requests")
            if not self.amount_required or self.amount_required <= 0:
                raise ValueError("amount_required must be a positive integer for per_unit requests")
            # Derive budget from price × quantity
            self.budget = round(self.price_per_unit * self.amount_required, 2)
        elif self.pricing_mode == "fixed_bounty":
            if not self.budget or self.budget <= 0:
                raise ValueError("budget must be a positive number for fixed_bounty requests")
        return self


class DataRequestResponseSchema(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    unit: Optional[str] = None
    amount_required: Optional[int] = None
    pricing_mode: str
    price_per_unit: Optional[float] = None
    budget: Optional[float] = None
    required_format: Optional[str] = None
    spec: Optional[dict] = None
    mode: Optional[str] = "request"
    collection_spec: Optional[dict] = None
    deadline: Optional[str] = None
    status: str
    accepted_total: Optional[int] = None
    requester_id: Optional[UUID] = None
    license_id: Optional[UUID] = None
    license_name: Optional[str] = None

    class Config:
        from_attributes = True

    @field_validator("deadline", mode="before")
    @classmethod
    def _coerce_deadline(cls, v):
        # The ORM column is a DateTime; the response contract is an ISO string.
        # Coerce so creating/reading a request with a deadline doesn't 500 on
        # response validation.
        if v is None or isinstance(v, str):
            return v
        return v.isoformat()

    @classmethod
    def model_validate(cls, obj, **kw):
        instance = super().model_validate(obj, **kw)
        # Populate license_name from the ORM relationship if available
        if hasattr(obj, "license") and obj.license:
            instance.license_name = obj.license.name
        return instance


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

class SubmissionCreateSchema(BaseModel):
    request_id: UUID
    content_link: str
    offered_amount: int  # what the provider claims; accepted_amount is set by buyer at acceptance


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProfileCreate(BaseModel):
    user_type: str = Field(..., alias="user_type")
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    company_name: Optional[str] = Field(None, alias="companyName")
    email: str
    phone: Optional[str] = None
    address: Optional[str] = None

    model_config = {"validate_by_name": True, "populate_by_name": True}
