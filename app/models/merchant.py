"""Merchant database model."""

from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, func
from app.models.base import Base


class Merchant(Base):
    """SQLAlchemy model for Merchants."""

    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True, index=True)
    merchant_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
