"""Deterministic recommendation engine for ranking payment recovery strategies."""

from typing import List, Dict, Any
from app.recovery.schemas import RecoveryStrategy


def rank_strategies(strategies: List[RecoveryStrategy]) -> Dict[str, Any]:
    """Rank strategies using a deterministic composite score heuristic.

    Score = expected_recovered_revenue * ConfidenceHeuristic * RiskHeuristic

    Note: These multipliers are decision-making heuristics to balance reward,
    confidence, and operational risk. They are not statistically validated probabilities.
    """
    confidence_multipliers = {
        "HIGH": 1.0,
        "MEDIUM": 0.8,
        "LOW": 0.5
    }

    risk_multipliers = {
        "LOW": 1.0,
        "MEDIUM": 0.8,
        "HIGH": 0.5
    }

    scored_strategies = []
    for s in strategies:
        rev = s.expected_recovered_revenue
        conf_mult = confidence_multipliers.get(s.confidence, 0.5)
        risk_mult = risk_multipliers.get(s.risk_level, 0.5)
        score = float(rev) * conf_mult * risk_mult
        scored_strategies.append((score, s))

    # Sort by score descending. Tie breaker: lower risk first, then higher confidence.
    def sort_key(item):
        score, s = item
        # We want higher score first, so negative score.
        # Risk level: LOW = 0, MEDIUM = 1, HIGH = 2 (lower is better, so positive int for sorting)
        risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(s.risk_level, 2)
        # Confidence: HIGH = 0, MEDIUM = 1, LOW = 2 (higher is better, so positive int for sorting)
        conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(s.confidence, 2)
        return (-score, risk_order, conf_order, s.strategy_id)

    scored_strategies.sort(key=sort_key)

    best_score, recommended = scored_strategies[0]

    # Generate explanation reason
    reason = (
        f"Strategy '{recommended.name}' is recommended as the optimal path. "
        f"It provides an estimated potential recovery of INR {recommended.expected_recovered_revenue:,.2f} "
        f"with a risk level of {recommended.risk_level} and confidence of {recommended.confidence}. "
        f"This selection is determined by a composite decision heuristic score of {best_score:.2f}, "
        f"which balances projected recovery value against risk and data confidence."
    )

    return {
        "recommended_strategy": recommended.strategy_id,
        "recommendation_reason": reason,
        "confidence": recommended.confidence
    }
