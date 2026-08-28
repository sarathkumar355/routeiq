"""Tests for Phase 3 analytics and root-cause payment investigation engine."""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db.session import get_db_session
from app.db.init_db import init_db
from app.data.generate import generate_transactions_data
from app.analytics.metrics import (
    calculate_success_rate,
    calculate_revenue_at_risk,
    calculate_composite_score,
)
from app.analytics.queries import fetch_overall_metrics, fetch_gateway_performance
from app.analytics.investigation import run_investigation, MIN_SAMPLE_SIZE
from app.models.merchant import Merchant
from app.models.gateway import Gateway
from app.models.bank import Bank
from app.models.payment_method import PaymentMethod
from app.models.transaction import Transaction

client = TestClient(app)


def _repopulate_db():
    """Helper function to reset database and seed the standard 50,000 transaction dataset."""
    init_db(reset=True)
    with get_db_session() as db:
        merchant_ids = {m.merchant_code: m.id for m in db.query(Merchant).all()}
        gateway_ids = {g.gateway_code: g.id for g in db.query(Gateway).all()}
        bank_ids = {b.bank_code: b.id for b in db.query(Bank).all()}
        payment_method_ids = {p.method_code: p.id for p in db.query(PaymentMethod).all()}

        txns_data = generate_transactions_data(
            count=50000,
            seed=42,
            merchant_ids=merchant_ids,
            gateway_ids=gateway_ids,
            bank_ids=bank_ids,
            payment_method_ids=payment_method_ids,
        )
        db.query(Transaction).delete()
        db.commit()
        
        # Insert in chunks
        chunk_size = 10000
        for i in range(0, len(txns_data), chunk_size):
            db.bulk_insert_mappings(Transaction, txns_data[i : i + chunk_size])
            db.commit()


@pytest.fixture(scope="module", autouse=True)
def populate_db_with_standard_set():
    """Ensure database has the standard 50,000 transaction dataset generated with seed 42."""
    _repopulate_db()


def test_metrics_calculations():
    """Test core math functions in metrics.py."""
    # Success rate
    assert calculate_success_rate(0, 100) == 0.0
    assert calculate_success_rate(75, 100) == 75.0
    assert calculate_success_rate(1, 3) == 33.33
    assert calculate_success_rate(10, 0) == 0.0

    # Revenue at Risk
    attempted = Decimal("1000.00")
    successful = Decimal("750.00")
    baseline_rate = 90.0  # 90% expected success rate
    res = calculate_revenue_at_risk(attempted, successful, baseline_rate)
    
    assert res["attempted_value"] == attempted
    assert res["actual_successful_value"] == successful
    assert res["baseline_success_rate"] == 90.0
    assert res["expected_successful_value"] == Decimal("900.00")
    assert res["estimated_revenue_at_risk"] == Decimal("150.00")  # 900 expected - 750 actual

    # Composite Score
    # Normal positive case: sample_size=100, rate_drop=15.0, consistency=0.8, revenue_at_risk=2000.00
    assert calculate_composite_score(100, 15.0, 0.8, 2000.00) == 39.61
    # Negative/Zero conditions -> 0 score
    assert calculate_composite_score(0, 15.0, 0.8, 2000.00) == 0.0
    assert calculate_composite_score(100, 0.0, 0.8, 2000.00) == 0.0
    assert calculate_composite_score(100, 15.0, 0.0, 2000.00) == 0.0
    assert calculate_composite_score(100, 15.0, 0.8, -50.00) == 0.0


def test_queries_and_overall_metrics():
    """Verify that overall metrics aggregates match the database contents."""
    with get_db_session() as db:
        metrics = fetch_overall_metrics(db)
        assert metrics["total_count"] == 50000
        assert metrics["success_rate"] > 90.0
        assert metrics["attempted_value"] > 0
        assert metrics["successful_value"] > 0
        assert metrics["failed_value"] > 0
        assert metrics["success_count"] + metrics["failed_count"] == 50000


def test_gateway_performance_sorting():
    """Check that gateway performance returns all gateways ordered alphabetically by code."""
    with get_db_session() as db:
        perf = fetch_gateway_performance(db)
        assert len(perf) == 4
        # Assert alphabetical ordering
        codes = [g["gateway_code"] for g in perf]
        assert codes == sorted(codes)


def test_empty_database_graceful_handling():
    """Ensure that clean/empty database does not crash and returns a standard empty structured report."""
    with get_db_session() as db:
        # Clear transactions
        db.query(Transaction).delete()
        db.commit()

        # Run investigation
        report = run_investigation(db)
        assert report["overall_metrics"]["total_count"] == 0
        assert report["overall_metrics"]["success_rate"] == 0.0
        assert report["gateway_metrics"] == []
        assert report["top_candidates"] == []
        assert report["investigation_status"] == "no_data"

    # Repopulate so that subsequent tests in this module run on standard data
    _repopulate_db()


def test_incident_discovery_without_hardcoding():
    """Ensure the investigation scanner independently discovers the synthetic UPI-SBI-Gateway B degradation."""
    with get_db_session() as db:
        report = run_investigation(db)
        assert report["investigation_status"] == "complete"
        assert len(report["top_candidates"]) > 0

        # The top-ranked candidate should be Gateway B + UPI + SBI
        top_candidate = report["top_candidates"][0]
        assert top_candidate["gateway_code"] == "GATEWAY_B"
        assert top_candidate["payment_method_code"] == "UPI"
        assert top_candidate["bank_code"] == "SBI"

        # Verify time-window discovery (18:00 - 22:00 -> hours [18, 19, 20, 21])
        assert top_candidate["suspected_hours"] == [18, 19, 20, 21]
        assert top_candidate["suspected_dates"] == ["2026-08-21", "2026-08-22"]

        # Verify other metric qualities
        assert top_candidate["baseline_success_rate"] > 90.0
        assert top_candidate["affected_success_rate"] < 80.0
        assert top_candidate["rate_drop"] > 10.0
        assert top_candidate["sample_size"] >= MIN_SAMPLE_SIZE
        assert top_candidate["revenue_at_risk"] > 0
        assert top_candidate["ranking_score"] > 0
        assert top_candidate["consistency"] >= 0.8  # Consistent degradation for our injected incident


def test_investigation_summary_api_endpoint():
    """Test the GET /api/investigation/summary API endpoint return format and data integrity."""
    response = client.get("/api/investigation/summary")
    assert response.status_code == 200
    
    data = response.json()
    assert "overall_metrics" in data
    assert "gateway_metrics" in data
    assert "top_candidates" in data
    assert "time_analysis" in data
    assert "revenue_at_risk_summary" in data
    
    overall = data["overall_metrics"]
    assert overall["total_count"] == 50000
    assert overall["success_rate"] == 92.08
    
    candidates = data["top_candidates"]
    assert len(candidates) > 0
    top = candidates[0]
    assert top["gateway_code"] == "GATEWAY_B"
    assert top["payment_method_code"] == "UPI"
    assert top["bank_code"] == "SBI"
    assert top["suspected_dates"] == ["2026-08-21", "2026-08-22"]
    assert top["suspected_hours"] == [18, 19, 20, 21]
    
    # Assert time analysis exists
    assert len(data["time_analysis"]["hourly"]) == 24
    assert len(data["time_analysis"]["daily"]) == 7
