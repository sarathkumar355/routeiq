"""PaymentMethod database model."""

from sqlalchemy import Column, Integer, String
from app.models.base import Base


class PaymentMethod(Base):
    """SQLAlchemy model for Payment Methods."""

    __tablename__ = "payment_methods"

    id = Column(Integer, primary_key=True, index=True)
    method_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
