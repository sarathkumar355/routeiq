"""Automated test suite for Phase 5 Recovery Strategy & Revenue Recovery Simulation."""

import os
import json
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db_session
from app.recovery.simulator import (
    calculate_current_revenue_at_risk,
    calculate_expected_recovered_revenue,
    calculate_remaining_revenue_at_risk,
)
from app.recovery.strategies import (
    calculate_alternative_gateway_routing,
    calculate_payment_method_fallback,
    calculate_delayed_retry,
    calculate_no_action,
)
from app.recovery.recommendation import rank_strategies
from app.recovery.schemas import RecoveryStrategy

client = TestClient(app)


# Mock Classes for Gemini SDK Protobuf structures
class MockFunctionCall:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args


class MockPart:
    def __init__(self, text: str = None, function_call=None):
        self.text = text
        self.function_call = function_call


class MockContent:
    def __init__(self, parts: list):
        self.parts = parts


class MockCandidate:
    def __init__(self, content):
        self.content = content


class MockResponse:
    def __init__(self, content, text: str = ""):
        self.candidates = [MockCandidate(content)]
        self.text = text


# 1. Recovery calculations precision, negative capping, and limits
def test_recovery_calculator_integrity():
    """Verify Decimal safety, rounding, lower/upper boundaries for recovery calculators."""
    # Test capping at revenue at risk
    rev_risk = Decimal("1000.00")
    rate = Decimal("1.50")  # Over 100%
    recovered = calculate_expected_recovered_revenue(rev_risk, rate)
    assert recovered == Decimal("1000.00")

    # Test negative capping
    neg_rate = Decimal("-0.50")
    recovered_neg = calculate_expected_recovered_revenue(rev_risk, neg_rate)
    assert recovered_neg == Decimal("0.00")

    # Test precision rounding
    rate_precise = Decimal("0.123456")
    recovered_precise = calculate_expected_recovered_revenue(rev_risk, rate_precise)
    assert recovered_precise == Decimal("123.46")  # 1000 * 0.123456 = 123.456 rounded up to 123.46

    # Test remaining revenue calculation
    remaining = calculate_remaining_revenue_at_risk(rev_risk, recovered_precise)
    assert remaining == Decimal("876.54")


# 2. Alternative Gateway Simulation
def test_alternative_gateway_simulation():
    """Ensure alternative gateway simulation runs and pulls best gateway from database."""
    with get_db_session() as db:
        strategy = calculate_alternative_gateway_routing(
            db,
            gateway_code="GATEWAY_B",
            payment_method_code="UPI",
            bank_code="SBI",
            revenue_at_risk=Decimal("5000.00")
        )
        assert isinstance(strategy, RecoveryStrategy)
        assert strategy.strategy_id == "alternative_gateway"
        assert strategy.is_data_derived is True
        assert strategy.confidence in ["HIGH", "MEDIUM"]
        assert strategy.estimated_recovery_rate > 0.0
        assert "GATEWAY_" in strategy.description
        assert "transactions" in strategy.evidence_source


# 3. Payment Method Fallback Simulation
def test_payment_method_fallback_simulation():
    """Ensure fallback method queries database and applies switch assumptions properly."""
    with get_db_session() as db:
        strategy = calculate_payment_method_fallback(
            db,
            gateway_code="GATEWAY_B",
            payment_method_code="UPI",
            bank_code="SBI",
            revenue_at_risk=Decimal("5000.00")
        )
        assert isinstance(strategy, RecoveryStrategy)
        assert strategy.strategy_id == "payment_method_fallback"
        assert strategy.is_data_derived is True
        assert "30% estimated manual user-switch" in strategy.assumptions
        assert "PostgreSQL table" in strategy.evidence_source


# 4. Delayed Retry Simulation
def test_delayed_retry_simulation():
    """Ensure retry simulation is marked as assumption-based with LOW confidence."""
    strategy = calculate_delayed_retry(Decimal("5000.00"))
    assert strategy.strategy_id == "delayed_retry"
    assert strategy.is_data_derived is False
    assert strategy.confidence == "LOW"
    assert "None - retry outcomes are not tracked" in strategy.evidence_source
    assert "20% potential recovery rate" in strategy.assumptions


# 5. Monitor / No Action Simulation
def test_no_action_simulation():
    """Ensure no action is treated as a baseline with expected recovery of 0."""
    strategy = calculate_no_action(Decimal("5000.00"))
    assert strategy.strategy_id == "no_action"
    assert strategy.is_data_derived is False
    assert strategy.confidence == "HIGH"
    assert strategy.expected_recovered_revenue == 0.0
    assert strategy.remaining_revenue_at_risk == 5000.0


# 6. Heuristic ranking determinism
def test_heuristic_ranking_determinism():
    """Verify composite strategy ranking outputs the optimal selection deterministically."""
    strategies = [
        RecoveryStrategy(
            strategy_id="alt",
            name="Alternative",
            description="",
            evidence_source="",
            assumptions="",
            is_data_derived=True,
            estimated_recovery_rate=0.8,
            expected_recovered_revenue=800.0,
            remaining_revenue_at_risk=200.0,
            confidence="HIGH",
            risk_level="LOW"
        ),
        RecoveryStrategy(
            strategy_id="retry",
            name="Retry",
            description="",
            evidence_source="",
            assumptions="",
            is_data_derived=False,
            estimated_recovery_rate=0.5,
            expected_recovered_revenue=500.0,
            remaining_revenue_at_risk=500.0,
            confidence="LOW",
            risk_level="MEDIUM"
        ),
        RecoveryStrategy(
            strategy_id="fallback",
            name="Fallback",
            description="",
            evidence_source="",
            assumptions="",
            is_data_derived=True,
            estimated_recovery_rate=0.7,
            expected_recovered_revenue=700.0,
            remaining_revenue_at_risk=300.0,
            confidence="MEDIUM",
            risk_level="LOW"
        ),
    ]

    result = rank_strategies(strategies)
    assert result["recommended_strategy"] == "alt"
    assert "heuristic score" in result["recommendation_reason"]
    assert result["confidence"] == "HIGH"


# 7. Endpoint Validation (missing key, schema)
def test_recovery_endpoint_missing_api_key():
    """Ensure recovery endpoint yields 503 HTTP status if API key is missing."""
    with patch.dict(os.environ, {}, clear=True):
        payload = {
            "gateway_code": "GATEWAY_B",
            "payment_method_code": "UPI",
            "bank_code": "SBI",
            "attempted_value": 10000.00,
            "successful_value": 8000.00,
            "baseline_success_rate": 95.0
        }
        response = client.post("/api/agent/recovery", json=payload)
        assert response.status_code == 503
        assert "GEMINI_API_KEY" in response.json()["detail"]


# 8. Stateful Gemini Mock Recovery Loop
@patch("google.generativeai.GenerativeModel")
def test_agent_recovery_loop(mock_model_class):
    """Test stateful recovery loop with Gemini mock conversation, traces, and schema output."""
    mock_model = MagicMock()
    mock_model_class.return_value = mock_model

    turn_counter = 0

    def mock_generate_content(messages, tools=None):
        nonlocal turn_counter
        turn_counter += 1

        if turn_counter == 1:
            # Turn 1: Model calls get_recovery_context
            parts = [MockPart(function_call=MockFunctionCall("get_recovery_context", {}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 2:
            # Turn 2: Model calls simulate_alternative_gateway
            parts = [MockPart(function_call=MockFunctionCall("simulate_alternative_gateway", {"revenue_at_risk": 1500.0}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 3:
            # Turn 3: Model calls simulate_payment_method_fallback
            parts = [MockPart(function_call=MockFunctionCall("simulate_payment_method_fallback", {"revenue_at_risk": 1500.0}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 4:
            # Turn 4: Model calls simulate_delayed_retry
            parts = [MockPart(function_call=MockFunctionCall("simulate_delayed_retry", {"revenue_at_risk": 1500.0}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 5:
            # Turn 5: Model calls simulate_no_action
            parts = [MockPart(function_call=MockFunctionCall("simulate_no_action", {"revenue_at_risk": 1500.0}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 6:
            # Turn 6: Model calls rank_recovery_strategies
            strategies_payload = [
                {
                    "strategy_id": "alternative_gateway",
                    "name": "Alternative Gateway Routing",
                    "description": "Route to GATEWAY_A",
                    "evidence_source": "PostgreSQL transactions",
                    "assumptions": "Assumes historical success",
                    "is_data_derived": True,
                    "estimated_recovery_rate": 0.94,
                    "expected_recovered_revenue": 1410.0,
                    "remaining_revenue_at_risk": 90.0,
                    "confidence": "HIGH",
                    "risk_level": "LOW"
                }
            ]
            parts = [MockPart(function_call=MockFunctionCall("rank_recovery_strategies", {"strategies": strategies_payload}))]
            return MockResponse(MockContent(parts))
        else:
            # Turn 7: Model outputs final JSON recommendation
            report = {
                "current_revenue_at_risk": 1500.0,
                "strategies": [
                    {
                        "strategy_id": "alternative_gateway",
                        "name": "Alternative Gateway Routing",
                        "description": "Route to GATEWAY_A",
                        "evidence_source": "PostgreSQL transactions",
                        "assumptions": "Assumes historical success",
                        "is_data_derived": True,
                        "estimated_recovery_rate": 0.94,
                        "expected_recovered_revenue": 1410.0,
                        "remaining_revenue_at_risk": 90.0,
                        "confidence": "HIGH",
                        "risk_level": "LOW"
                    }
                ],
                "recommended_strategy": "alternative_gateway",
                "recommendation_reason": "Alternative routing offers highest potential recovery.",
                "confidence": "HIGH"
            }
            report_str = json.dumps(report)
            return MockResponse(MockContent([MockPart(text=report_str)]), text=report_str)

    mock_model.generate_content.side_effect = mock_generate_content

    payload = {
        "gateway_code": "GATEWAY_B",
        "payment_method_code": "UPI",
        "bank_code": "SBI",
        "attempted_value": 10000.00,
        "successful_value": 8000.00,
        "baseline_success_rate": 95.0
    }

    with patch.dict(os.environ, {"GEMINI_API_KEY": "mock-api-key"}):
        response = client.post("/api/agent/recovery", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert data["simulation_only"] is True
        assert len(data["tools_used"]) == 6
        assert len(data["trace"]) == 6

        # Check recommendation
        rec = data["recommendation"]
        assert rec["strategy"] == "alternative_gateway"
        assert rec["expected_recovered_revenue"] == 1410.0
        assert rec["remaining_revenue_at_risk"] == 90.0
        assert rec["confidence"] == "HIGH"
