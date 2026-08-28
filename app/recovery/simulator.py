"""Decimal-safe simulator calculations for revenue at risk and strategy outcomes."""

from decimal import Decimal, ROUND_HALF_UP


def round_decimal(val: Decimal) -> Decimal:
    """Round a Decimal value to 2 decimal places (currency precision)."""
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_current_revenue_at_risk(
    attempted_value: Decimal,
    successful_value: Decimal,
    baseline_success_rate: Decimal
) -> Decimal:
    """Calculate the estimated initial revenue at risk inside the incident window.

    Expected Successful Value = Baseline Success Rate (percentage) * Attempted Value / 100
    Revenue at Risk = Expected Successful Value - Actual Successful Value
    """
    expected_successful = (baseline_success_rate / Decimal("100.00")) * attempted_value
    revenue_at_risk = expected_successful - successful_value
    if revenue_at_risk < Decimal("0.00"):
        return Decimal("0.00")
    return round_decimal(revenue_at_risk)


def calculate_expected_recovered_revenue(
    revenue_at_risk: Decimal,
    recovery_rate: Decimal
) -> Decimal:
    """Calculate expected potential recovered revenue from recovery rate.

    Expected Recovered = Revenue at Risk * Recovery Rate
    Constrained to: 0.00 <= Expected Recovered <= Revenue at Risk
    """
    if revenue_at_risk <= Decimal("0.00"):
        return Decimal("0.00")
    
    expected_recovered = revenue_at_risk * recovery_rate
    # Cap to avoid exceeding current revenue at risk or dropping below zero
    expected_recovered = min(max(Decimal("0.00"), expected_recovered), revenue_at_risk)
    return round_decimal(expected_recovered)


def calculate_remaining_revenue_at_risk(
    revenue_at_risk: Decimal,
    expected_recovered_revenue: Decimal
) -> Decimal:
    """Calculate remaining revenue at risk after recovery is applied."""
    remaining = revenue_at_risk - expected_recovered_revenue
    if remaining < Decimal("0.00"):
        return Decimal("0.00")
    return round_decimal(remaining)
