"""Gateway database model."""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from app.models.base import Base


class Gateway(Base):
    """SQLAlchemy model for Gateways."""

    __tablename__ = "gateways"

    id = Column(Integer, primary_key=True, index=True)
    gateway_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
