"""Database queries for payment metrics and investigation."""

from decimal import Decimal
from typing import Dict, Any, List
from sqlalchemy import func, select, and_, case
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.models.gateway import Gateway
from app.models.bank import Bank
from app.models.payment_method import PaymentMethod
from app.models.transaction import Transaction


def fetch_overall_metrics(db: Session) -> Dict[str, Any]:
    """Calculate overall transaction counts, success rate, and values.

    Handles empty database scenarios gracefully.
    """
    stmt = select(
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count"),
        func.count(func.nullif(Transaction.status == "FAILED", False)).label("failed_count"),
        func.sum(Transaction.amount).label("attempted_value"),
        func.sum(case((Transaction.status == "SUCCESS", Transaction.amount), else_=0)).label("successful_value"),
        func.sum(case((Transaction.status == "FAILED", Transaction.amount), else_=0)).label("failed_value")
    )
    result = db.execute(stmt).fetchone()

    if not result or result.total_count == 0:
        return {
            "total_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "success_rate": 0.0,
            "attempted_value": Decimal("0.00"),
            "successful_value": Decimal("0.00"),
            "failed_value": Decimal("0.00"),
        }

    total = result.total_count
    successes = result.success_count
    rate = (successes / total * 100) if total > 0 else 0.0

    return {
        "total_count": total,
        "success_count": successes,
        "failed_count": result.failed_count,
        "success_rate": round(rate, 2),
        "attempted_value": result.attempted_value or Decimal("0.00"),
        "successful_value": result.successful_value or Decimal("0.00"),
        "failed_value": result.failed_value or Decimal("0.00"),
    }


def fetch_gateway_performance(db: Session) -> List[Dict[str, Any]]:
    """Fetch base success rate metrics for each gateway, sorted alphabetically by code."""
    stmt = select(
        Gateway.gateway_code,
        Gateway.name,
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count")
    ).join(
        Transaction, Transaction.gateway_id == Gateway.id, isouter=True
    ).group_by(
        Gateway.gateway_code, Gateway.name
    ).order_by(
        Gateway.gateway_code
    )

    results = db.execute(stmt).fetchall()

    performance = []
    for r in results:
        total = r.total_count
        successes = r.success_count
        rate = (successes / total * 100) if total > 0 else 0.0
        performance.append({
            "gateway_code": r.gateway_code,
            "name": r.name,
            "total_count": total,
            "success_count": successes,
            "success_rate": round(rate, 2),
        })
    return performance


def fetch_hourly_segment_metrics(db: Session) -> List[Dict[str, Any]]:
    """Group all transactions by gateway, payment method, bank, date, and hour.

    Returns count of total attempts, successful attempts, and total transaction amount.
    Used for scanning anomalies in Python memory.
    """
    stmt = select(
        Gateway.gateway_code,
        PaymentMethod.method_code,
        Bank.bank_code,
        func.date(Transaction.created_at).label("tx_date"),
        func.extract("hour", Transaction.created_at).label("tx_hour"),
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count"),
        func.sum(Transaction.amount).label("attempted_value"),
        func.sum(case((Transaction.status == "SUCCESS", Transaction.amount), else_=0)).label("successful_value")
    ).join(
        Gateway, Transaction.gateway_id == Gateway.id
    ).join(
        PaymentMethod, Transaction.payment_method_id == PaymentMethod.id
    ).join(
        Bank, Transaction.bank_id == Bank.id
    ).group_by(
        Gateway.gateway_code,
        PaymentMethod.method_code,
        Bank.bank_code,
        func.date(Transaction.created_at),
        func.extract("hour", Transaction.created_at)
    ).order_by(
        Gateway.gateway_code,
        PaymentMethod.method_code,
        Bank.bank_code,
        func.date(Transaction.created_at),
        func.extract("hour", Transaction.created_at)
    )

    results = db.execute(stmt).fetchall()

    metrics = []
    for r in results:
        # tx_date might be returned as date object, convert to string
        date_str = r.tx_date.strftime("%Y-%m-%d") if hasattr(r.tx_date, "strftime") else str(r.tx_date)
        metrics.append({
            "gateway_code": r.gateway_code,
            "payment_method_code": r.method_code,
            "bank_code": r.bank_code,
            "date": date_str,
            "hour": int(r.tx_hour),
            "total_count": r.total_count,
            "success_count": r.success_count,
            "attempted_value": r.attempted_value or Decimal("0.00"),
            "successful_value": r.successful_value or Decimal("0.00"),
        })
    return metrics
