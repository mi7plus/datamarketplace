# app/models.py
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Text, Float,
    Boolean, DateTime, Index, JSON
)
import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db import Base
from datetime import datetime
from sqlalchemy import Enum
import enum


class BaseModel(Base):
    __abstract__ = True
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    version = Column(Integer, default=1)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RequestStatus(str, enum.Enum):
    DRAFT = "draft"
    OPEN = "open"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    REVIEW = "review"
    COMPLETED = "completed"
    EXPIRED = "expired"

class PricingMode(str, enum.Enum):
    PER_UNIT = "per_unit"
    FIXED_BOUNTY = "fixed_bounty"

class UserRole(str, enum.Enum):
    REQUESTER = "requester"
    PROVIDER = "provider"
    ADMIN = "admin"

class SubmissionStatus(str, enum.Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED_INVALID = "rejected_invalid"
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"
    PAID = "paid"
    DISPUTED = "disputed"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class License(BaseModel):
    __tablename__ = "licenses"
    name = Column(String, nullable=False, unique=True)
    terms = Column(Text)


class UserAuth(BaseModel):
    __tablename__ = "user_auth"
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    refresh_token_hash = Column(String)
    role = Column(Enum(UserRole, name="user_role_enum"), nullable=False)
    is_verified = Column(Boolean, default=False)
    account_locked = Column(Boolean, default=False)
    failed_login_attempts = Column(Integer, default=0)
    last_login_at = Column(DateTime)
    # Stripe Connect account id for providers receiving payouts
    stripe_account_id = Column(String, nullable=True)
    profile = relationship("UserProfile", uselist=False, back_populates="user", cascade="all, delete-orphan")
    requests = relationship("DataRequest", back_populates="requester", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="provider", cascade="all, delete-orphan")
    analytics = relationship("UserAnalytics", uselist=False, back_populates="user", cascade="all, delete-orphan")
    __table_args__ = (Index("idx_user_auth_email", "email"),)


class DataRequest(BaseModel):
    __tablename__ = "data_requests"
    title = Column(String, nullable=False)
    description = Column(Text)
    required_format = Column(String)           # kept for compatibility; spec JSON supersedes in Phase 2
    amount_required = Column(Integer)          # target quantity
    budget = Column(Float)                     # total buyer budget (escrowed on OPEN)
    pricing_mode = Column(
        Enum(PricingMode, name="pricing_mode_enum"),
        default=PricingMode.PER_UNIT,
        nullable=False,
    )
    price_per_unit = Column(Float)             # stored for stability (= budget / amount_required)
    unit = Column(String)                      # e.g. "row", "record", "image"
    deadline = Column(DateTime, nullable=True)
    spec = Column(JSON, nullable=True)         # structured schema (Phase 2)
    accepted_total = Column(Integer, default=0)  # running sum of accepted units
    license_id = Column(UUID(as_uuid=True), ForeignKey("licenses.id"), nullable=True)
    requester_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"))
    requester = relationship("UserAuth", back_populates="requests")
    submissions = relationship("Submission", back_populates="request")
    license = relationship("License")
    status = Column(
        Enum(RequestStatus, name="request_status_enum"),
        default=RequestStatus.DRAFT,
        nullable=False,
    )
    __table_args__ = (
        Index("idx_request_status_budget", "status", "budget"),
        Index("idx_marketplace_matching", "status", "budget", "created_at"),
        Index("idx_request_active_records", "is_deleted", "status"),
    )


class Submission(BaseModel):
    __tablename__ = "submissions"
    request_id = Column(UUID(as_uuid=True), ForeignKey("data_requests.id"))
    provider_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"))
    content_link = Column(String)
    offered_amount = Column(Integer, default=0)     # declared by provider at submit
    accepted_amount = Column(Integer, default=0)    # set by buyer at acceptance (Phase 4)
    validated_amount = Column(Integer, nullable=True)  # units passing ingest validation (Phase 3)
    amount_due = Column(Float, nullable=True)       # accepted_amount × price_per_unit (set at acceptance)
    validation_report = Column(JSON, nullable=True)
    request = relationship("DataRequest", back_populates="submissions")
    provider = relationship("UserAuth", back_populates="submissions")
    status = Column(
        Enum(SubmissionStatus, name="submission_status_enum"),
        default=SubmissionStatus.PENDING,
        nullable=False,
    )
    quality_score = Column(Float, default=0)
    verified = Column(Boolean, default=False)
    dataset_hash = Column(String)
    access_token_id = Column(String)
    download_limit = Column(Integer, default=0)
    verified_by = Column(UUID(as_uuid=True), nullable=True)
    review_notes = Column(Text)
    file_size_bytes = Column(Integer)
    mime_type = Column(String)
    storage_location = Column(String)
    owner_signature = Column(String)      # provider warranty affirmation (Phase 8)
    access_expiry = Column(DateTime)
    __table_args__ = (
        Index("idx_submission_request_status", "request_id", "status"),
        Index("idx_submission_active_records", "is_deleted", "status"),
    )


class UserProfile(BaseModel):
    __tablename__ = "user_profile"
    user_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_type = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    company_name = Column(String)
    phone = Column(String)
    address = Column(String)
    user = relationship("UserAuth", back_populates="profile")
    __table_args__ = (Index("idx_user_profile_user_id", "user_id"),)


class UserAnalytics(BaseModel):
    __tablename__ = "user_analytics"
    user_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), unique=True)
    reputation_score = Column(Float, default=0)
    total_transactions = Column(Integer, default=0)
    successful_transactions = Column(Integer, default=0)
    last_activity_at = Column(DateTime)
    provider_quality_score = Column(Float, default=0)
    user = relationship("UserAuth", back_populates="analytics")
    __table_args__ = (Index("idx_user_analytics_user_id", "user_id"),)


class Review(BaseModel):
    """1–5 star rating left by either party after a PAID submission."""
    __tablename__ = "reviews"
    request_id = Column(UUID(as_uuid=True), ForeignKey("data_requests.id"), nullable=False)
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False)
    author_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)   # 1–5
    comment = Column(Text)
    author = relationship("UserAuth", foreign_keys=[author_id])
    subject = relationship("UserAuth", foreign_keys=[subject_id])
    __table_args__ = (
        Index("idx_review_subject", "subject_id"),
        Index("idx_review_submission", "submission_id"),
    )


class Dispute(BaseModel):
    """Buyer-opened dispute pausing escrow release for one submission."""
    __tablename__ = "disputes"
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False, unique=True)
    opened_by_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), nullable=False)
    reason = Column(Text, nullable=False)
    notes = Column(Text)          # admin resolution notes
    status = Column(String, default="open")   # "open" | "resolved_paid" | "resolved_rejected"
    submission = relationship("Submission")
    opened_by = relationship("UserAuth")
    __table_args__ = (Index("idx_dispute_submission", "submission_id"),)


class Ledger(BaseModel):
    """Append-only escrow ledger. Derive balances by summing; never mutate rows."""
    __tablename__ = "ledger"
    request_id = Column(UUID(as_uuid=True), ForeignKey("data_requests.id"), nullable=False)
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True)
    entry_type = Column(String, nullable=False)   # "hold" | "release" | "refund"
    amount = Column(Float, nullable=False)
    external_ref = Column(String, nullable=True)  # Stripe payment intent / transfer id
    request = relationship("DataRequest")
    submission = relationship("Submission")
    __table_args__ = (Index("idx_ledger_request_id", "request_id"),)
