# app/models.py
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Text, Float,
    Boolean, DateTime, Index, JSON, Numeric
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
    locked_until = Column(DateTime, nullable=True)   # time-based lockout window (S3)
    mfa_secret = Column(String, nullable=True)        # TOTP secret (S3 HARDEN)
    mfa_enabled = Column(Boolean, default=False)      # MFA active once enrolled + verified
    last_login_at = Column(DateTime)
    # Stripe Connect account id for providers receiving payouts
    stripe_account_id = Column(String, nullable=True)
    payout_account_changed_at = Column(DateTime, nullable=True)  # cool-down anchor (S3)
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
    budget = Column(Numeric(12, 2))            # total buyer budget (escrowed on OPEN)
    pricing_mode = Column(
        Enum(PricingMode, name="pricing_mode_enum"),
        default=PricingMode.PER_UNIT,
        nullable=False,
    )
    price_per_unit = Column(Numeric(12, 2))   # stored for stability (= budget / amount_required)
    unit = Column(String)                      # e.g. "row", "record", "image"
    deadline = Column(DateTime, nullable=True)
    spec = Column(JSON, nullable=True)         # structured schema (Phase 2)
    category = Column(String, nullable=True)   # vertical/category for beachhead metrics (Phase 7)
    mode = Column(String, default="request")   # "request" (upload) | "collect" (field forms) — Phase 5
    collection_spec = Column(JSON, nullable=True)  # form fields + geo/photo/consent requirements (Collect mode)
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
    amount_due = Column(Numeric(12, 2), nullable=True)  # accepted_amount × price_per_unit (set at acceptance)
    commission_amount = Column(Numeric(12, 2), nullable=True)  # platform take, set at settlement (Phase 7)
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
    accepted_at = Column(DateTime, nullable=True)  # set when ACCEPTED; starts the review window
    key_hashes = Column(JSON, nullable=True)        # per-record SHA-256 hashes for cross-provider dedup (F3)
    quarantined = Column(Boolean, default=False)    # blocks delivery pending review (S4: PII / report)
    pii_report = Column(JSON, nullable=True)        # ingest PII scan result (S4)
    source = Column(String, default="request")      # request | collect | catalog — fill provenance (Phase 6)
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


class AcceptedKey(Base):
    """
    Tracks per-record unique-key hashes that have already been accepted for a request.
    Prevents cross-provider duplicate records from being paid twice.
    Only populated when the request spec declares a unique_key.
    """
    __tablename__ = "accepted_keys"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("data_requests.id"), nullable=False)
    key_hash = Column(String(64), nullable=False)  # SHA-256 hex of the key tuple
    __table_args__ = (
        Index("idx_accepted_keys_request", "request_id"),
        # Unique constraint makes insert-or-ignore the atomic dedup primitive
        __import__("sqlalchemy").UniqueConstraint("request_id", "key_hash", name="uq_accepted_key"),
    )


class ListingStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    SOLD_OUT = "sold_out"
    TAKEN_DOWN = "taken_down"


class Listing(BaseModel):
    """
    A pre-listed dataset a supplier offers for sale, priced per record (Mode 2 —
    Buy existing). Reuses the Request spec + ingest validation + dataset-hash +
    PII/quality machinery; buyers purchase any portion, settled per record through
    the same escrow/ledger.
    """
    __tablename__ = "listings"
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    unit = Column(String)                              # "row", "record", ...
    price_per_unit = Column(Numeric(12, 2), nullable=False)
    available_quantity = Column(Integer, nullable=False, default=0)   # decremented on purchase
    validated_amount = Column(Integer, nullable=False, default=0)     # full count at ingest
    required_format = Column(String)
    spec = Column(JSON, nullable=True)
    license_id = Column(UUID(as_uuid=True), ForeignKey("licenses.id"), nullable=True)
    provenance = Column(Text)                          # where the data came from (compliance moat)
    sample = Column(JSON, nullable=True)               # neutralized preview rows
    dataset_hash = Column(String)
    storage_location = Column(String)
    key_hashes = Column(JSON, nullable=True)           # for cross-mode dedup (Phase 6)
    quality_score = Column(Float, default=0)
    pii_report = Column(JSON, nullable=True)
    quarantined = Column(Boolean, default=False)
    owner_signature = Column(String)                   # supplier warranty
    status = Column(Enum(ListingStatus, name="listing_status_enum"), default=ListingStatus.ACTIVE, nullable=False)
    supplier = relationship("UserAuth")
    license = relationship("License")
    __table_args__ = (
        Index("idx_listing_status", "status", "is_deleted"),
        Index("idx_listing_supplier", "supplier_id"),
    )


class CollectionDispatch(BaseModel):
    """A BYO-workforce org's engagement to fulfil a Collect-mode request. Its agents
    submit structured CollectionEntry rows, which are finalized into a Submission
    that settles through the same engine (Mode 3)."""
    __tablename__ = "collection_dispatches"
    request_id = Column(UUID(as_uuid=True), ForeignKey("data_requests.id"), nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, default="open")     # open | finalized | cancelled
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True)  # set at finalize
    request = relationship("DataRequest")
    org = relationship("UserAuth")
    __table_args__ = (Index("idx_dispatch_request", "request_id"),)


class CollectionEntry(BaseModel):
    """One structured field entry submitted by an agent against a dispatch. Validated
    against the request's collection_spec (fields + geo/photo/consent QA) at submit."""
    __tablename__ = "collection_entries"
    dispatch_id = Column(UUID(as_uuid=True), ForeignKey("collection_dispatches.id"), nullable=False)
    contributor_ref = Column(String)            # agent label / id within the org
    data = Column(JSON, nullable=False)         # field values per collection_spec
    geo_lat = Column(Float, nullable=True)
    geo_lng = Column(Float, nullable=True)
    photo_ref = Column(String, nullable=True)   # photo evidence reference
    consent_basis = Column(String, nullable=True)   # consent captured for personal/location data
    lawful_basis = Column(String, nullable=True)    # GDPR lawful basis
    status = Column(String, default="valid")    # valid | rejected
    validation_errors = Column(JSON, nullable=True)
    __table_args__ = (Index("idx_entry_dispatch", "dispatch_id"),)


class Purchase(BaseModel):
    """A buyer's purchase of a portion of a Listing, priced per record and settled
    through the same escrow/ledger as Request fulfilment (Mode 2)."""
    __tablename__ = "purchases"
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id"), nullable=False)
    buyer_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)     # snapshot at purchase time
    amount = Column(Numeric(12, 2), nullable=False)         # quantity × unit_price
    commission_amount = Column(Numeric(12, 2), nullable=True)   # platform take (Phase 7)
    status = Column(String, default="pending")              # pending | paid | refunded
    storage_location = Column(String)
    listing = relationship("Listing")
    buyer = relationship("UserAuth")
    __table_args__ = (Index("idx_purchase_buyer", "buyer_id"),)


class SubmissionFlag(Base):
    """A report against a submission (illegal / non-consented / infringing data).
    A flag quarantines the dataset pending admin review (S4)."""
    __tablename__ = "submission_flags"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False)
    reporter_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"), nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("idx_submission_flags_submission", "submission_id"),
        __import__("sqlalchemy").UniqueConstraint("submission_id", "reporter_id", name="uq_submission_flag"),
    )


class Ledger(BaseModel):
    """Append-only escrow ledger. Derive balances by summing; never mutate rows."""
    __tablename__ = "ledger"
    # Exactly one settlement context is set: a Request (Mode 1/3) or a Purchase (Mode 2).
    request_id = Column(UUID(as_uuid=True), ForeignKey("data_requests.id"), nullable=True)
    purchase_id = Column(UUID(as_uuid=True), ForeignKey("purchases.id"), nullable=True)
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True)
    entry_type = Column(String, nullable=False)   # "hold" | "release" | "refund"
    amount = Column(Numeric(12, 2), nullable=False)
    external_ref = Column(String, nullable=True, unique=True)  # Stripe payment intent / transfer id; unique prevents double-record
    request = relationship("DataRequest")
    submission = relationship("Submission")
    purchase = relationship("Purchase")
    __table_args__ = (
        Index("idx_ledger_request_id", "request_id"),
        Index("idx_ledger_purchase_id", "purchase_id"),
    )


class AuditLog(Base):
    """Append-only audit trail of money/file events (S6): who did what to which
    object, when, from where. Written, never updated or deleted."""
    __tablename__ = "audit_log"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    ip = Column(String, nullable=True)
    action = Column(String, nullable=False)        # download | release | takedown | payout_change | purchase | fulfil ...
    object_type = Column(String, nullable=True)    # submission | purchase | listing | request | user
    object_id = Column(String, nullable=True)
    meta = Column(JSON, nullable=True)
    __table_args__ = (
        Index("idx_audit_object", "object_type", "object_id"),
        Index("idx_audit_action", "action"),
    )


class ProcessedStripeEvent(Base):
    """Dedup table for Stripe webhook events. Prevents double-processing on redelivery."""
    __tablename__ = "processed_stripe_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String, nullable=False, unique=True)
    event_type = Column(String, nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow)
