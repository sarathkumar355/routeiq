"""Deterministic read-only investigation tools for the AI agent."""

from decimal import Decimal
from typing import Dict, Any, List
from sqlalchemy import func, select, case
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.models.gateway import Gateway
from app.models.bank import Bank
from app.models.payment_method import PaymentMethod
from app.models.transaction import Transaction
from app.analytics.metrics import calculate_success_rate, calculate_revenue_at_risk as core_calc_rar


def get_overall_metrics(db: Session) -> Dict[str, Any]:
    """Fetch the overall transaction metrics across all merchants, gateways, and methods.

    Returns:
        A dictionary with overall total count, success count, failed count, success rate,
        and transaction values.
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
            "attempted_value": 0.0,
            "successful_value": 0.0,
            "failed_value": 0.0,
        }

    total = result.total_count
    successes = result.success_count
    rate = calculate_success_rate(successes, total)

    return {
        "total_count": total,
        "success_count": successes,
        "failed_count": result.failed_count,
        "success_rate": rate,
        "attempted_value": float(result.attempted_value or 0.0),
        "successful_value": float(result.successful_value or 0.0),
        "failed_value": float(result.failed_value or 0.0),
    }


def get_gateway_performance(db: Session) -> List[Dict[str, Any]]:
    """Fetch all payment gateways ranked by investigation relevance (lowest success rate first).

    Returns:
        A list of gateway performance records containing gateway_code, total_count,
        success_count, failed_count, success_rate, and attempted_value.
    """
    stmt = select(
        Gateway.gateway_code,
        Gateway.name,
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count"),
        func.count(func.nullif(Transaction.status == "FAILED", False)).label("failed_count"),
        func.sum(Transaction.amount).label("attempted_value")
    ).join(
        Transaction, Transaction.gateway_id == Gateway.id, isouter=True
    ).group_by(
        Gateway.gateway_code, Gateway.name
    )

    results = db.execute(stmt).fetchall()

    performance = []
    for r in results:
        total = r.total_count
        successes = r.success_count
        rate = calculate_success_rate(successes, total)
        performance.append({
            "gateway_code": r.gateway_code,
            "name": r.name,
            "total_count": total,
            "success_count": successes,
            "failed_count": r.failed_count,
            "success_rate": rate,
            "attempted_value": float(r.attempted_value or 0.0),
        })

    # Sort by success rate ascending (lowest success rate / strongest degradation first)
    performance.sort(key=lambda x: x["success_rate"])
    return performance


def investigate_payment_methods(db: Session, gateway_code: str) -> List[Dict[str, Any]]:
    """Investigate performance breakdown by payment method for a specific gateway.

    Args:
        gateway_code: Unique code identifying the gateway (e.g. 'GATEWAY_B').
    """
    stmt = select(
        PaymentMethod.method_code,
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count"),
        func.count(func.nullif(Transaction.status == "FAILED", False)).label("failed_count"),
        func.sum(Transaction.amount).label("attempted_value")
    ).join(
        Gateway, Transaction.gateway_id == Gateway.id
    ).join(
        PaymentMethod, Transaction.payment_method_id == PaymentMethod.id
    ).where(
        Gateway.gateway_code == gateway_code
    ).group_by(
        PaymentMethod.method_code
    )

    results = db.execute(stmt).fetchall()

    performance = []
    for r in results:
        total = r.total_count
        successes = r.success_count
        rate = calculate_success_rate(successes, total)
        performance.append({
            "payment_method_code": r.method_code,
            "total_count": total,
            "success_count": successes,
            "failed_count": r.failed_count,
            "success_rate": rate,
            "attempted_value": float(r.attempted_value or 0.0),
        })

    performance.sort(key=lambda x: x["success_rate"])
    return performance


def investigate_banks(db: Session, gateway_code: str, payment_method_code: str) -> List[Dict[str, Any]]:
    """Investigate performance breakdown by issuing bank for a gateway and payment method.

    Args:
        gateway_code: Gateway identifier (e.g. 'GATEWAY_B').
        payment_method_code: Payment method identifier (e.g. 'UPI').
    """
    stmt = select(
        Bank.bank_code,
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count"),
        func.count(func.nullif(Transaction.status == "FAILED", False)).label("failed_count"),
        func.sum(Transaction.amount).label("attempted_value")
    ).join(
        Gateway, Transaction.gateway_id == Gateway.id
    ).join(
        PaymentMethod, Transaction.payment_method_id == PaymentMethod.id
    ).join(
        Bank, Transaction.bank_id == Bank.id
    ).where(
        Gateway.gateway_code == gateway_code,
        PaymentMethod.method_code == payment_method_code
    ).group_by(
        Bank.bank_code
    )

    results = db.execute(stmt).fetchall()

    performance = []
    for r in results:
        total = r.total_count
        successes = r.success_count
        rate = calculate_success_rate(successes, total)
        performance.append({
            "bank_code": r.bank_code,
            "total_count": total,
            "success_count": successes,
            "failed_count": r.failed_count,
            "success_rate": rate,
            "attempted_value": float(r.attempted_value or 0.0),
        })

    performance.sort(key=lambda x: x["success_rate"])
    return performance


def investigate_gateway_segments(db: Session, gateway_code: str) -> List[Dict[str, Any]]:
    """Get aggregated metrics grouped by payment method and bank for a specific gateway.

    Args:
        gateway_code: Gateway identifier.
    """
    stmt = select(
        PaymentMethod.method_code,
        Bank.bank_code,
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count"),
        func.count(func.nullif(Transaction.status == "FAILED", False)).label("failed_count"),
        func.sum(Transaction.amount).label("attempted_value")
    ).join(
        Gateway, Transaction.gateway_id == Gateway.id
    ).join(
        PaymentMethod, Transaction.payment_method_id == PaymentMethod.id
    ).join(
        Bank, Transaction.bank_id == Bank.id
    ).where(
        Gateway.gateway_code == gateway_code
    ).group_by(
        PaymentMethod.method_code, Bank.bank_code
    )

    results = db.execute(stmt).fetchall()

    performance = []
    for r in results:
        total = r.total_count
        successes = r.success_count
        rate = calculate_success_rate(successes, total)
        performance.append({
            "payment_method_code": r.method_code,
            "bank_code": r.bank_code,
            "total_count": total,
            "success_count": successes,
            "failed_count": r.failed_count,
            "success_rate": rate,
            "attempted_value": float(r.attempted_value or 0.0),
        })

    performance.sort(key=lambda x: x["success_rate"])
    return performance


def investigate_time_patterns(db: Session, gateway_code: str, payment_method_code: str, bank_code: str) -> List[Dict[str, Any]]:
    """Fetch hourly success rates and transaction volumes for a specific segment.

    Used to dynamically discover anomalous dates and hour ranges from data patterns.

    Args:
        gateway_code: Gateway identifier.
        payment_method_code: Payment method identifier.
        bank_code: Bank identifier.
    """
    stmt = select(
        func.date(Transaction.created_at).label("tx_date"),
        func.extract("hour", Transaction.created_at).label("tx_hour"),
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count"),
        func.count(func.nullif(Transaction.status == "FAILED", False)).label("failed_count"),
        func.sum(Transaction.amount).label("attempted_value"),
        func.sum(case((Transaction.status == "SUCCESS", Transaction.amount), else_=0)).label("successful_value")
    ).join(
        Gateway, Transaction.gateway_id == Gateway.id
    ).join(
        PaymentMethod, Transaction.payment_method_id == PaymentMethod.id
    ).join(
        Bank, Transaction.bank_id == Bank.id
    ).where(
        Gateway.gateway_code == gateway_code,
        PaymentMethod.method_code == payment_method_code,
        Bank.bank_code == bank_code
    ).group_by(
        func.date(Transaction.created_at),
        func.extract("hour", Transaction.created_at)
    ).order_by(
        func.date(Transaction.created_at),
        func.extract("hour", Transaction.created_at)
    )

    results = db.execute(stmt).fetchall()

    patterns = []
    for r in results:
        date_str = r.tx_date.strftime("%Y-%m-%d") if hasattr(r.tx_date, "strftime") else str(r.tx_date)
        total = r.total_count
        successes = r.success_count
        rate = calculate_success_rate(successes, total)
        patterns.append({
            "date": date_str,
            "hour": int(r.tx_hour),
            "total_count": total,
            "success_count": successes,
            "failed_count": r.failed_count,
            "success_rate": rate,
            "attempted_value": float(r.attempted_value or 0.0),
            "successful_value": float(r.successful_value or 0.0),
        })

    return patterns


def calculate_revenue_at_risk(
    attempted_value: float, successful_value: float, baseline_success_rate: float
) -> Dict[str, Any]:
    """Calculate the estimated transaction value lost due to degradation.

    Expected successful value = attempted value * baseline success rate.
    Revenue at risk = expected successful value - actual successful value.

    Args:
        attempted_value: Total transaction volume attempted in the window.
        successful_value: Total transaction volume that succeeded in the window.
        baseline_success_rate: Normal success rate percentage outside the window.
    """
    res = core_calc_rar(
        Decimal(str(attempted_value)),
        Decimal(str(successful_value)),
        baseline_success_rate
    )
    return {
        "attempted_value": float(res["attempted_value"]),
        "actual_successful_value": float(res["actual_successful_value"]),
        "baseline_success_rate": float(res["baseline_success_rate"]),
        "expected_successful_value": float(res["expected_successful_value"]),
        "estimated_revenue_at_risk": float(res["estimated_revenue_at_risk"]),
    }
