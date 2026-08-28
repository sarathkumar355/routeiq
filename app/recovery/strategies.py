"""Deterministic recovery strategy logic based on historical transaction data and explicit assumptions."""

from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.gateway import Gateway
from app.models.payment_method import PaymentMethod
from app.models.bank import Bank
from app.models.transaction import Transaction
from app.recovery.schemas import RecoveryStrategy
from app.recovery.simulator import (
    calculate_expected_recovered_revenue,
    calculate_remaining_revenue_at_risk,
)


def calculate_alternative_gateway_routing(
    db: Session,
    gateway_code: str,
    payment_method_code: str,
    bank_code: str,
    revenue_at_risk: Decimal
) -> RecoveryStrategy:
    """Simulate routing affected transactions to the best available alternative gateway.

    Queries transaction history for alternative gateways using the same payment method and bank.
    Falls back to payment-method level or global gateway success rates if insufficient data exists.
    """
    # 1. Query segment-specific success rates for alternative gateways
    stmt = select(
        Gateway.gateway_code,
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count")
    ).join(
        Transaction, Transaction.gateway_id == Gateway.id
    ).join(
        PaymentMethod, Transaction.payment_method_id == PaymentMethod.id
    ).join(
        Bank, Transaction.bank_id == Bank.id
    ).filter(
        Gateway.gateway_code != gateway_code,
        PaymentMethod.method_code == payment_method_code,
        Bank.bank_code == bank_code
    ).group_by(
        Gateway.gateway_code
    )

    results = db.execute(stmt).fetchall()

    best_gateway = None
    best_rate = Decimal("0.00")
    confidence = "LOW"
    evidence_source = "None"
    assumptions = ""

    # Look for alternative gateway with Segment N >= 30
    for r in results:
        total = r.total_count
        success = r.success_count
        rate = Decimal(str(success / total)) if total > 0 else Decimal("0.00")
        if total >= 30 and rate > best_rate:
            best_rate = rate
            best_gateway = r.gateway_code
            confidence = "HIGH"

    # Fallback 1: Query payment method level (across all banks)
    if not best_gateway:
        stmt_pm = select(
            Gateway.gateway_code,
            func.count(Transaction.id).label("total_count"),
            func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count")
        ).join(
            Transaction, Transaction.gateway_id == Gateway.id
        ).join(
            PaymentMethod, Transaction.payment_method_id == PaymentMethod.id
        ).filter(
            Gateway.gateway_code != gateway_code,
            PaymentMethod.method_code == payment_method_code
        ).group_by(
            Gateway.gateway_code
        )
        results_pm = db.execute(stmt_pm).fetchall()
        for r in results_pm:
            total = r.total_count
            success = r.success_count
            rate = Decimal(str(success / total)) if total > 0 else Decimal("0.00")
            if total >= 30 and rate > best_rate:
                best_rate = rate
                best_gateway = r.gateway_code
                confidence = "MEDIUM"

    # Fallback 2: Query global gateway level
    if not best_gateway:
        stmt_global = select(
            Gateway.gateway_code,
            func.count(Transaction.id).label("total_count"),
            func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count")
        ).join(
            Transaction, Transaction.gateway_id == Gateway.id
        ).filter(
            Gateway.gateway_code != gateway_code
        ).group_by(
            Gateway.gateway_code
        )
        results_global = db.execute(stmt_global).fetchall()
        for r in results_global:
            total = r.total_count
            success = r.success_count
            rate = Decimal(str(success / total)) if total > 0 else Decimal("0.00")
            if total >= 30 and rate > best_rate:
                best_rate = rate
                best_gateway = r.gateway_code
                confidence = "MEDIUM"

    # Fallback 3: Defaults if no gateway has N >= 30 overall
    if not best_gateway:
        # Default to GATEWAY_A if it exists, otherwise any alternative gateway code
        alt_gw = db.query(Gateway.gateway_code).filter(Gateway.gateway_code != gateway_code).first()
        best_gateway = alt_gw[0] if alt_gw else "ALTERNATIVE_GATEWAY"
        best_rate = Decimal("0.90")  # 90% default assumption
        confidence = "LOW"
        evidence_source = "Defaults - insufficient historical alternative gateway volume"
        assumptions = (
            f"Assumes a default recovery success rate of {best_rate * 100:.1f}% on "
            f"fallback gateway {best_gateway} due to insufficient segment data."
        )
    else:
        evidence_source = f"PostgreSQL table: transactions (alternative gateway: {best_gateway})"
        assumptions = (
            f"Assumes routed transactions will achieve the historical success rate of the best alternative "
            f"gateway ({best_gateway}) for this segment, which is {best_rate * 100:.2f}%."
        )

    expected_recovered = calculate_expected_recovered_revenue(revenue_at_risk, best_rate)
    remaining_at_risk = calculate_remaining_revenue_at_risk(revenue_at_risk, expected_recovered)

    return RecoveryStrategy(
        strategy_id="alternative_gateway",
        name="Alternative Gateway Routing",
        description=f"Route affected transactions from {gateway_code} to alternative gateway {best_gateway}.",
        evidence_source=evidence_source,
        assumptions=assumptions,
        is_data_derived=confidence in ["HIGH", "MEDIUM"],
        estimated_recovery_rate=float(best_rate),
        expected_recovered_revenue=float(expected_recovered),
        remaining_revenue_at_risk=float(remaining_at_risk),
        confidence=confidence,
        risk_level="LOW"
    )


def calculate_payment_method_fallback(
    db: Session,
    gateway_code: str,
    payment_method_code: str,
    bank_code: str,
    revenue_at_risk: Decimal
) -> RecoveryStrategy:
    """Simulate switching transactions to the best alternative payment method on the same gateway.

    Queries historical success rates for alternative payment methods, and discounts it by a
    30% estimated completion rate (switch completion assumption).
    """
    # 1. Query success rate of alternative methods for the gateway and bank
    stmt = select(
        PaymentMethod.method_code,
        func.count(Transaction.id).label("total_count"),
        func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count")
    ).join(
        Transaction, Transaction.payment_method_id == PaymentMethod.id
    ).join(
        Gateway, Transaction.gateway_id == Gateway.id
    ).join(
        Bank, Transaction.bank_id == Bank.id
    ).filter(
        Gateway.gateway_code == gateway_code,
        PaymentMethod.method_code != payment_method_code,
        Bank.bank_code == bank_code
    ).group_by(
        PaymentMethod.method_code
    )

    results = db.execute(stmt).fetchall()

    best_method = None
    best_rate = Decimal("0.00")
    confidence = "LOW"
    evidence_source = "None"

    # Find the best alternative method with N >= 30 attempts
    for r in results:
        total = r.total_count
        success = r.success_count
        rate = Decimal(str(success / total)) if total > 0 else Decimal("0.00")
        if total >= 30 and rate > best_rate:
            best_rate = rate
            best_method = r.method_code
            confidence = "MEDIUM"

    # Fallback 1: Query global success rate of alternative payment methods on this gateway
    if not best_method:
        stmt_pm = select(
            PaymentMethod.method_code,
            func.count(Transaction.id).label("total_count"),
            func.count(func.nullif(Transaction.status == "SUCCESS", False)).label("success_count")
        ).join(
            Transaction, Transaction.payment_method_id == PaymentMethod.id
        ).join(
            Gateway, Transaction.gateway_id == Gateway.id
        ).filter(
            Gateway.gateway_code == gateway_code,
            PaymentMethod.method_code != payment_method_code
        ).group_by(
            PaymentMethod.method_code
        )
        results_pm = db.execute(stmt_pm).fetchall()
        for r in results_pm:
            total = r.total_count
            success = r.success_count
            rate = Decimal(str(success / total)) if total > 0 else Decimal("0.00")
            if total >= 30 and rate > best_rate:
                best_rate = rate
                best_method = r.method_code
                confidence = "MEDIUM"

    # Fallback 2: Default if no alternative method has N >= 30 attempts
    if not best_method:
        # Default fallback payment method
        alt_pm = db.query(PaymentMethod.method_code).filter(PaymentMethod.method_code != payment_method_code).first()
        best_method = alt_pm[0] if alt_pm else "CARD"
        best_rate = Decimal("0.90")
        confidence = "LOW"
        evidence_source = "Defaults - insufficient alternative payment method volume"
        assumptions = (
            f"Assumes default baseline success rate of {best_rate * 100:.1f}% for alternative method {best_method}, "
            f"discounted by a 30% manual user-switch completion rate assumption."
        )
    else:
        evidence_source = f"PostgreSQL table: transactions (alternative method: {best_method} on gateway {gateway_code})"
        assumptions = (
            f"Assumes historical base success rate of {best_rate * 100:.2f}% for payment method {best_method} "
            f"on {gateway_code}, discounted by a 30% estimated manual user-switch completion rate."
        )

    # Recovery Rate = alternative payment method success rate * user switch completion rate (30%)
    switch_rate = Decimal("0.30")
    recovery_rate = best_rate * switch_rate

    expected_recovered = calculate_expected_recovered_revenue(revenue_at_risk, recovery_rate)
    remaining_at_risk = calculate_remaining_revenue_at_risk(revenue_at_risk, expected_recovered)

    return RecoveryStrategy(
        strategy_id="payment_method_fallback",
        name="Payment Method Fallback",
        description=f"Prompt users to switch to alternative payment method {best_method} on {gateway_code}.",
        evidence_source=evidence_source,
        assumptions=assumptions,
        is_data_derived=confidence == "MEDIUM",  # Distinguishes data-derived success rate from the switch rate assumption
        estimated_recovery_rate=float(recovery_rate),
        expected_recovered_revenue=float(expected_recovered),
        remaining_revenue_at_risk=float(remaining_at_risk),
        confidence="MEDIUM",  # Overall strategy confidence is MEDIUM due to the user switch rate assumption
        risk_level="LOW"
    )


def calculate_delayed_retry(revenue_at_risk: Decimal) -> RecoveryStrategy:
    """Simulate retrying failed transactions after the degradation window resolves.

    Since the dataset lacks historical retry tracking records, this strategy is assumption-based.
    It returns LOW confidence with a clear warning explaining schema limitations.
    """
    retry_rate = Decimal("0.20")  # Explicit retry recovery assumption: 20% timeout recovery
    expected_recovered = calculate_expected_recovered_revenue(revenue_at_risk, retry_rate)
    remaining_at_risk = calculate_remaining_revenue_at_risk(revenue_at_risk, expected_recovered)

    return RecoveryStrategy(
        strategy_id="delayed_retry",
        name="Delayed Retry Simulation",
        description="Prompt users or schedule background processes to retry failed transactions after a delay.",
        evidence_source="None - retry outcomes are not tracked in the current database schema.",
        assumptions="Assumes a flat 20% potential recovery rate for timed-out transactions after degradation resolves. Lacks historical retry linking.",
        is_data_derived=False,
        estimated_recovery_rate=float(retry_rate),
        expected_recovered_revenue=float(expected_recovered),
        remaining_revenue_at_risk=float(remaining_at_risk),
        confidence="LOW",
        risk_level="MEDIUM"
    )


def calculate_no_action(revenue_at_risk: Decimal) -> RecoveryStrategy:
    """Baseline strategy representing the scenario of taking no recovery actions."""
    return RecoveryStrategy(
        strategy_id="no_action",
        name="Monitor / No Action",
        description="Take no recovery action and monitor the incident.",
        evidence_source="Baseline strategy with no recovery action",
        assumptions="Take no action, allowing current degradation to persist or recover naturally without intervention.",
        is_data_derived=False,
        estimated_recovery_rate=0.0,
        expected_recovered_revenue=0.0,
        remaining_revenue_at_risk=float(revenue_at_risk),
        confidence="HIGH",
        risk_level="LOW"
    )
