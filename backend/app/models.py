# app/models.py
from sqlalchemy import Column, Integer, String, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from app.db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "requester" or "provider"
    requests = relationship("DataRequest", back_populates="requester")
    submissions = relationship("Submission", back_populates="provider")

class DataRequest(Base):
    __tablename__ = "data_requests"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    required_format = Column(String)
    amount_required = Column(Integer)
    budget = Column(Float)
    requester_id = Column(Integer, ForeignKey("users.id"))
    requester = relationship("User", back_populates="requests")
    submissions = relationship("Submission", back_populates="request")

class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("data_requests.id"))
    provider_id = Column(Integer, ForeignKey("users.id"))
    content_link = Column(String)  # could be URL, file path, etc.
    accepted_amount = Column(Integer, default=0)
    status = Column(String, default="pending")  # pending / accepted / rejected
    request = relationship("DataRequest", back_populates="submissions")
    provider = relationship("User", back_populates="submissions")