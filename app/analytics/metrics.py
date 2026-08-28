"""Mathematical and statistical metrics calculations."""

from decimal import Decimal
from typing import Dict, Any


def calculate_success_rate(successes: int, total: int) -> float:
    """Calculate percentage success rate, rounded to 2 decimal places."""
    if total <= 0:
        return 0.0
    return round((successes / total) * 100, 2)


def calculate_revenue_at_risk(
    attempted_value: Decimal,
    successful_value: Decimal,
    baseline_success_rate: float,
) -> Dict[str, Any]:
    """Calculate the estimated transaction value lost due to degradation.

    Expected successful value = attempted value * baseline success rate.
    Revenue at risk = expected successful value - actual successful value.
    """
    # Convert rate to Decimal safely
    rate_dec = Decimal(str(baseline_success_rate)) / Decimal("100.0")
    expected_successful_value = attempted_value * rate_dec
    estimated_revenue_at_risk = expected_successful_value - successful_value

    return {
        "attempted_value": attempted_value,
        "actual_successful_value": successful_value,
        "baseline_success_rate": round(baseline_success_rate, 2),
        "expected_successful_value": round(expected_successful_value, 2),
        "estimated_revenue_at_risk": round(estimated_revenue_at_risk, 2),
    }


def calculate_composite_score(
    sample_size: int,
    rate_drop: float,
    consistency: float,
    revenue_at_risk: float,
) -> float:
    """Calculate a composite ranking score for underperforming candidates.

    Considers success-rate degradation, sample size, consistency, and log-scaled
    revenue at risk to ensure a balanced, robust problem ranking.
    """
    import math

    if sample_size <= 0 or rate_drop <= 0 or consistency <= 0 or revenue_at_risk <= 0:
        return 0.0

    score = (
        sample_size
        * (rate_drop / 100.0)
        * consistency
        * math.log10(max(10.0, revenue_at_risk))
    )
    return round(score, 2)
