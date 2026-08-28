"""Bank database model."""

from sqlalchemy import Boolean, Column, Integer, String
from app.models.base import Base


class Bank(Base):
    """SQLAlchemy model for Banks."""

    __tablename__ = "banks"

    id = Column(Integer, primary_key=True, index=True)
    bank_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
