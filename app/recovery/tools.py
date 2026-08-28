"""Read-only database tools for simulating payment recovery strategies."""

from typing import List, Dict, Any
from decimal import Decimal
from sqlalchemy.orm import Session

from app.recovery.schemas import RecoveryStrategy
from app.recovery.strategies import (
    calculate_alternative_gateway_routing,
    calculate_payment_method_fallback,
    calculate_delayed_retry,
    calculate_no_action,
)
from app.recovery.recommendation import rank_strategies


def get_recovery_context(
    db: Session,
    gateway_code: str,
    payment_method_code: str,
    bank_code: str
) -> Dict[str, Any]:
    """Fetch database metrics for the incident segment and potential alternatives.

    Provides count/rate summaries to verify database evidence for alternative gateways and methods.
    """
    # Simple check of alternative gateways and methods to give the agent context
    from app.models.gateway import Gateway
    from app.models.payment_method import PaymentMethod
    from app.models.transaction import Transaction
    from sqlalchemy import func, select

    stmt_g = select(
        Gateway.gateway_code,
        func.count(Transaction.id).label("total_count")
    ).join(
        Transaction, Transaction.gateway_id == Gateway.id
    ).filter(
        Gateway.gateway_code != gateway_code
    ).group_by(Gateway.gateway_code)

    g_results = db.execute(stmt_g).fetchall()

    stmt_m = select(
        PaymentMethod.method_code,
        func.count(Transaction.id).label("total_count")
    ).join(
        Transaction, Transaction.payment_method_id == PaymentMethod.id
    ).filter(
        PaymentMethod.method_code != payment_method_code
    ).group_by(PaymentMethod.method_code)

    m_results = db.execute(stmt_m).fetchall()

    return {
        "degraded_segment": {
            "gateway": gateway_code,
            "payment_method": payment_method_code,
            "bank": bank_code
        },
        "available_alternative_gateways": [
            {"gateway_code": r.gateway_code, "total_attempts": r.total_count} for r in g_results
        ],
        "available_alternative_methods": [
            {"method_code": r.method_code, "total_attempts": r.total_count} for r in m_results
        ]
    }


def simulate_alternative_gateway(
    db: Session,
    gateway_code: str,
    payment_method_code: str,
    bank_code: str,
    revenue_at_risk: float
) -> Dict[str, Any]:
    """Simulate routing affected transactions to the best available alternative gateway."""
    strategy = calculate_alternative_gateway_routing(
        db, gateway_code, payment_method_code, bank_code, Decimal(str(revenue_at_risk))
    )
    return strategy.model_dump()


def simulate_payment_method_fallback(
    db: Session,
    gateway_code: str,
    payment_method_code: str,
    bank_code: str,
    revenue_at_risk: float
) -> Dict[str, Any]:
    """Simulate switching transactions to the best alternative payment method on the same gateway."""
    strategy = calculate_payment_method_fallback(
        db, gateway_code, payment_method_code, bank_code, Decimal(str(revenue_at_risk))
    )
    return strategy.model_dump()


def simulate_delayed_retry(revenue_at_risk: float) -> Dict[str, Any]:
    """Simulate retrying failed transactions after the degradation window resolves (assumption-based)."""
    strategy = calculate_delayed_retry(Decimal(str(revenue_at_risk)))
    return strategy.model_dump()


def simulate_no_action(revenue_at_risk: float) -> Dict[str, Any]:
    """Baseline strategy representing the scenario of taking no recovery actions."""
    strategy = calculate_no_action(Decimal(str(revenue_at_risk)))
    return strategy.model_dump()


def rank_recovery_strategies(strategies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rank all simulated strategies and return the recommended option."""
    strategy_objects = [RecoveryStrategy(**s) for s in strategies]
    return rank_strategies(strategy_objects)
