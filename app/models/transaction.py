"""Transaction database model."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from app.models.base import Base


class Transaction(Base):
    """SQLAlchemy model for Transactions."""

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String(100), unique=True, index=True, nullable=False)

    merchant_id = Column(Integer, ForeignKey("merchants.id"), index=True, nullable=False)
    gateway_id = Column(Integer, ForeignKey("gateways.id"), index=True, nullable=False)
    bank_id = Column(Integer, ForeignKey("banks.id"), index=True, nullable=False)
    payment_method_id = Column(
        Integer, ForeignKey("payment_methods.id"), index=True, nullable=False
    )

    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    status = Column(String(20), index=True, nullable=False)  # 'SUCCESS' or 'FAILED'
    failure_reason = Column(String(100), nullable=True)
    geography = Column(String(100), nullable=False)
    created_at = Column(DateTime, index=True, nullable=False)
