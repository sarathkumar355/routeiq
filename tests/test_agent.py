"""Automated test suite for Phase 4 Agentic AI Investigation Layer."""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db_session
from app.agent.tools import (
    get_overall_metrics,
    get_gateway_performance,
    investigate_payment_methods,
    investigate_banks,
    investigate_gateway_segments,
    investigate_time_patterns,
    calculate_revenue_at_risk,
)
from app.agent.agent import run_agent_investigation

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


# 1. Missing Gemini API Key Handling Test
def test_missing_api_key_handling():
    """Ensure endpoint returns 503 if GEMINI_API_KEY env var is missing."""
    with patch.dict(os.environ, {}, clear=True):
        response = client.post("/api/agent/investigate", json={})
        assert response.status_code == 503
        assert "GEMINI_API_KEY" in response.json()["detail"]


# 2. Tool Registration and Type Signatures
def test_tool_registration_signatures():
    """Verify that investigation tools have correct names and parameters."""
    with get_db_session() as db:
        # get_overall_metrics
        res_overall = get_overall_metrics(db)
        assert "total_count" in res_overall
        assert "success_rate" in res_overall

        # get_gateway_performance
        res_gw = get_gateway_performance(db)
        assert isinstance(res_gw, list)
        if res_gw:
            # Check success rate ordering (ascending)
            rates = [g["success_rate"] for g in res_gw]
            assert rates == sorted(rates)
            assert "total_count" in res_gw[0]
            assert "failed_count" in res_gw[0]
            assert "attempted_value" in res_gw[0]


# 3 & 4. Tool Execution & Result Serialization
def test_tool_execution_serialization():
    """Ensure tools execute successfully and return JSON-serializable payloads."""
    with get_db_session() as db:
        # Methods
        res_methods = investigate_payment_methods(db, "GATEWAY_B")
        assert isinstance(res_methods, list)
        
        # Banks
        res_banks = investigate_banks(db, "GATEWAY_B", "UPI")
        assert isinstance(res_banks, list)

        # Segments
        res_segments = investigate_gateway_segments(db, "GATEWAY_B")
        assert isinstance(res_segments, list)

        # Time Patterns
        res_time = investigate_time_patterns(db, "GATEWAY_B", "UPI", "SBI")
        assert isinstance(res_time, list)
        if res_time:
            assert "date" in res_time[0]
            assert "hour" in res_time[0]

        # Revenue calculation
        res_rar = calculate_revenue_at_risk(1000.0, 800.0, 90.0)
        assert res_rar["estimated_revenue_at_risk"] == 100.0
        # Ensure json serialization is clean
        assert json.dumps(res_rar)


# 5, 7, 8 & 10. Stateful Agent Loop, Report, and Live Response Endpoint Validation
@patch("google.generativeai.GenerativeModel")
def test_agent_stateful_loop_and_endpoint(mock_model_class):
    """Test full agent loop with mocked Gemini multi-turn conversation and report validation."""
    mock_model = MagicMock()
    mock_model_class.return_value = mock_model

    # Define a sequence of responses to simulate multi-turn tool calling
    turn_counter = 0

    def mock_generate_content(messages, tools=None):
        nonlocal turn_counter
        turn_counter += 1

        if turn_counter == 1:
            # Turn 1: Model requests get_overall_metrics
            parts = [MockPart(function_call=MockFunctionCall("get_overall_metrics", {}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 2:
            # Turn 2: Model requests get_gateway_performance
            parts = [MockPart(function_call=MockFunctionCall("get_gateway_performance", {}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 3:
            # Turn 3: Model requests investigate_payment_methods
            parts = [MockPart(function_call=MockFunctionCall("investigate_payment_methods", {"gateway_code": "GATEWAY_B"}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 4:
            # Turn 4: Model requests investigate_banks
            parts = [MockPart(function_call=MockFunctionCall("investigate_banks", {"gateway_code": "GATEWAY_B", "payment_method_code": "UPI"}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 5:
            # Turn 5: Model requests investigate_time_patterns
            parts = [MockPart(function_call=MockFunctionCall("investigate_time_patterns", {"gateway_code": "GATEWAY_B", "payment_method_code": "UPI", "bank_code": "SBI"}))]
            return MockResponse(MockContent(parts))
        elif turn_counter == 6:
            # Turn 6: Model requests calculate_revenue_at_risk
            parts = [MockPart(function_call=MockFunctionCall("calculate_revenue_at_risk", {"attempted_value": 713660.48, "successful_value": 655376.40, "baseline_success_rate": 92.89}))]
            return MockResponse(MockContent(parts))
        else:
            # Turn 7: Model outputs the final report
            report = {
                "status": "complete",
                "summary": "Verified degradation in GATEWAY_B UPI SBI transactions between 18:00 and 22:00 on Aug 21-22.",
                "severity": "high",
                "root_cause": {
                    "gateway": "GATEWAY_B",
                    "payment_method": "UPI",
                    "bank": "SBI",
                    "time_window": "18:00-22:00",
                    "dates": ["2026-08-21", "2026-08-22"]
                },
                "evidence": [
                    {"observation": "Success rate dropped inside window", "value": "78.02%", "source_tool": "investigate_time_patterns"},
                    {"observation": "Revenue impact computed", "value": "7542.82", "source_tool": "calculate_revenue_at_risk"}
                ],
                "baseline_success_rate": 92.89,
                "affected_success_rate": 78.02,
                "rate_drop": 14.87,
                "sample_size": 91,
                "estimated_revenue_at_risk": 7542.82,
                "confidence": "HIGH",
                "tools_used": ["get_overall_metrics", "get_gateway_performance", "investigate_payment_methods", "investigate_banks", "investigate_time_patterns", "calculate_revenue_at_risk"]
            }
            report_str = json.dumps(report)
            return MockResponse(MockContent([MockPart(text=report_str)]), text=report_str)

    mock_model.generate_content.side_effect = mock_generate_content

    # Run the test with env variable mocked
    with patch.dict(os.environ, {"GEMINI_API_KEY": "mock-api-key"}):
        response = client.post("/api/agent/investigate", json={"question": "Why are success rates declining?"})
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "complete"
        assert len(data["tools_used"]) == 6
        assert len(data["investigation_trace"]) == 6
        
        # Verify trace structure
        trace_item = data["investigation_trace"][0]
        assert "tool_name" in trace_item
        assert "arguments" in trace_item
        assert "status" in trace_item
        assert "execution_duration_sec" in trace_item
        assert "result_summary" in trace_item

        # Verify report values
        report = data["report"]
        assert report["status"] == "complete"
        assert report["severity"] == "high"
        assert report["confidence"] == "HIGH"
        assert report["root_cause"]["gateway"] == "GATEWAY_B"
        assert report["root_cause"]["payment_method"] == "UPI"
        assert report["root_cause"]["bank"] == "SBI"
        assert report["baseline_success_rate"] == 92.89
        assert report["estimated_revenue_at_risk"] == 7542.82


# 6. Max Tool-Call Limit Verification
@patch("google.generativeai.GenerativeModel")
def test_agent_tool_call_limit(mock_model_class):
    """Test that agent loop halts and does not exceed MAX_TOOL_CALLS = 10."""
    mock_model = MagicMock()
    mock_model_class.return_value = mock_model

    # Infinite loop tool-caller mock (always requests get_overall_metrics)
    def mock_infinite_calls(messages, tools=None):
        last = messages[-1]
        parts_list = []
        if isinstance(last, dict):
            parts_list = last.get("parts", [])
        elif hasattr(last, "parts"):
            parts_list = last.parts
        
        has_limit_msg = False
        for p in parts_list:
            p_text = getattr(p, "text", "") or (p if isinstance(p, str) else "")
            if "maximum tool-call limit" in p_text:
                has_limit_msg = True
                break

        if has_limit_msg:
            # Returns the fallback summary response
            report = {
                "status": "complete",
                "summary": "Tool-call limit was reached during the investigation.",
                "severity": "medium",
                "root_cause": {"gateway": None, "payment_method": None, "bank": None, "time_window": None, "dates": []},
                "evidence": [],
                "confidence": "LOW",
                "tools_used": ["get_overall_metrics"] * 10
            }
            report_str = json.dumps(report)
            return MockResponse(MockContent([MockPart(text=report_str)]), text=report_str)

        parts = [MockPart(function_call=MockFunctionCall("get_overall_metrics", {}))]
        return MockResponse(MockContent(parts))

    mock_model.generate_content.side_effect = mock_infinite_calls

    with patch.dict(os.environ, {"GEMINI_API_KEY": "mock-api-key"}):
        response = client.post("/api/agent/investigate", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "limit_reached"
        # Tool call executions must be exactly 10
        assert len(data["tools_used"]) == 10
        assert len(data["investigation_trace"]) == 10


# 9. Gemini Error Handling Verification
@patch("google.generativeai.GenerativeModel")
def test_gemini_api_error_handling(mock_model_class):
    """Verify that runtime errors from Gemini API are handled gracefully."""
    mock_model = MagicMock()
    mock_model_class.return_value = mock_model
    mock_model.generate_content.side_effect = Exception("API quota exceeded.")

    with patch.dict(os.environ, {"GEMINI_API_KEY": "mock-api-key"}):
        response = client.post("/api/agent/investigate", json={})
        # Graceful internal server error status with description
        assert response.status_code == 500
        assert "Agent failed" in response.json()["detail"]
