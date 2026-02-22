# app/models.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Text,
    Float,
    Boolean,
    DateTime,
    Index
)
import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db import Base
from datetime import datetime
from sqlalchemy import Enum

class BaseModel(Base):
    __abstract__ = True
    id = Column(UUID(as_uuid=True),
                primary_key=True,
                default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    version = Column(Integer, default=1)

class RequestStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    REVIEW = "review"
    COMPLETED = "completed"
    EXPIRED = "expired"

class UserRole(str, Enum):
    REQUESTER = "requester"
    PROVIDER = "provider"
    ADMIN = "admin"

class UserAuth(BaseModel):
    __tablename__ = "user_auth"
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    refresh_token_hash = Column(String)
    role = Column(
        Enum(UserRole, name="user_role_enum"),
        nullable=False
    )
    is_verified = Column(Boolean, default=False)
    account_locked = Column(Boolean, default=False)
    failed_login_attempts = Column(Integer, default=0)
    last_login_at = Column(DateTime)
    profile = relationship(
        "UserProfile",
        uselist=False,
        back_populates="user"
        cascade="all, delete-orphan"
    )
    requests = relationship(
        "DataRequest",
        back_populates="requester",
        cascade="all, delete-orphan"
    )
    submissions = relationship(
        "Submission",
        back_populates="provider",
        cascade="all, delete-orphan"
    )
    analytics = relationship(
        "UserAnalytics",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan"
    )
    __table_args__ = (
        Index("idx_user_auth_email", "email"),
    )

class DataRequest(BaseModel):
    __tablename__ = "data_requests"
    title = Column(String, nullable=False)
    description = Column(Text)
    required_format = Column(String)
    amount_required = Column(Integer)
    budget = Column(Float)
    requester_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"))
    requester = relationship("UserAuth", back_populates="requests")
    submissions = relationship("Submission", back_populates="request")
    status = Column(
        Enum(RequestStatus, name="request_status_enum"),
        default=RequestStatus.DRAFT,
        nullable=False
    )
    __table_args__ = (
        Index("idx_request_status_budget", "status", "budget"),
        Index(
            "idx_marketplace_matching",
            "status",
            "budget",
            "created_at"
        ),
        Index("idx_request_active_records", "is_deleted", "status")
    )

class Submission(BaseModel):
    __tablename__ = "submissions"
    request_id = Column(UUID(as_uuid=True), ForeignKey("data_requests.id"))
    provider_id = Column(UUID(as_uuid=True), ForeignKey("user_auth.id", ondelete="CASCADE"))
    content_link = Column(String)  # could be URL, file path, etc.
    accepted_amount = Column(Integer, default=0)
    request = relationship("DataRequest", back_populates="submissions")
    provider = relationship("UserAuth", back_populates="submissions")
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
    owner_signature = Column(String)
    access_expiry = Column(DateTime)
    __table_args__ = (
        Index("idx_submission_request_status", "request_id", "status"),
        Index("idx_submission_active_records", "is_deleted", "status")
    )

class UserProfile(BaseModel):
    __tablename__ = "user_profile"
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_auth.id", ondelete="CASCADE"),
        unique=True,
        nullable=False
    )
    user_type = Column(String)  # person or company
    first_name = Column(String)
    last_name = Column(String)
    company_name = Column(String)
    phone = Column(String)
    address = Column(String)
    user = relationship(
        "UserAuth",
        back_populates="profile"
    )
    __table_args__ = (
        Index("idx_user_profile_user_id", "user_id"),
    )

class UserAnalytics(BaseModel):
    __tablename__ = "user_analytics"
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_auth.id", ondelete="CASCADE"),
        unique=True
    )
    reputation_score = Column(Float, default=0)
    total_transactions = Column(Integer, default=0)
    successful_transactions = Column(Integer, default=0)
    last_activity_at = Column(DateTime)
    user = relationship(
        "UserAuth",
        back_populates="analytics"
    )
    provider_quality_score = Column(Float, default=0)
    __table_args__ = (
        Index("idx_user_analytics_user_id", "user_id"),
    )
