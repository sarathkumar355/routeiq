"""Tests for Phase 2 database schemas and synthetic transaction generation."""

import pytest
from decimal import Decimal
from datetime import datetime
from sqlalchemy import func, and_, or_

from app.db.session import get_db_session, get_engine
from app.db.init_db import init_db
from app.data.generate import (
    generate_transactions_data,
    INCIDENT_CONFIG,
    sqlalchemy_or_helper,
)
from app.models.merchant import Merchant
from app.models.gateway import Gateway
from app.models.bank import Bank
from app.models.payment_method import PaymentMethod
from app.models.transaction import Transaction


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    """Ensure the database is initialized before running tests."""
    init_db(reset=True)


def test_reference_records_exist():
    """Verify that all baseline reference data was seeded correctly."""
    with get_db_session() as db:
        # Check Merchants
        merchants = db.query(Merchant).all()
        assert len(merchants) == 5
        merchant_codes = {m.merchant_code for m in merchants}
        assert merchant_codes == {"SHOPKART", "QUICKBITE", "URBANMART", "FOODFLEET", "NOVARETAIL"}

        # Check Gateways
        gateways = db.query(Gateway).all()
        assert len(gateways) == 4
        gateway_codes = {g.gateway_code for g in gateways}
        assert gateway_codes == {"GATEWAY_A", "GATEWAY_B", "GATEWAY_C", "GATEWAY_D"}

        # Check Banks
        banks = db.query(Bank).all()
        assert len(banks) == 8
        bank_codes = {b.bank_code for b in banks}
        assert bank_codes == {"SBI", "HDFC", "ICICI", "AXIS", "KOTAK", "PNB", "BOB", "YES"}

        # Check Payment Methods
        methods = db.query(PaymentMethod).all()
        assert len(methods) == 3
        method_codes = {m.method_code for m in methods}
        assert method_codes == {"UPI", "CARD", "NETBANKING"}


def test_transaction_generation_integrity():
    """Verify the validity and integrity of generated transaction fields."""
    with get_db_session() as db:
        # Generate 1000 transactions for a quick check
        merchant_ids = {m.merchant_code: m.id for m in db.query(Merchant).all()}
        gateway_ids = {g.gateway_code: g.id for g in db.query(Gateway).all()}
        bank_ids = {b.bank_code: b.id for b in db.query(Bank).all()}
        payment_method_ids = {p.method_code: p.id for p in db.query(PaymentMethod).all()}

        txns_data = generate_transactions_data(
            count=1000,
            seed=101,
            merchant_ids=merchant_ids,
            gateway_ids=gateway_ids,
            bank_ids=bank_ids,
            payment_method_ids=payment_method_ids,
        )

        assert len(txns_data) == 1000

        # Validate structure
        for tx in txns_data:
            assert tx["transaction_id"].startswith("TXN_")
            assert tx["amount"] > 0
            assert tx["currency"] == "INR"
            assert tx["status"] in ["SUCCESS", "FAILED"]
            if tx["status"] == "SUCCESS":
                assert tx["failure_reason"] is None
            else:
                assert tx["failure_reason"] in [
                    "INSUFFICIENT_FUNDS",
                    "TIMEOUT",
                    "BANK_DECLINED",
                    "NETWORK_ERROR",
                    "INVALID_DETAILS",
                    "LIMIT_EXCEEDED",
                    "GATEWAY_ERROR",
                ]
            assert tx["geography"] is not None
            assert isinstance(tx["created_at"], datetime)


def test_generation_reproducibility():
    """Verify that using the same seed produces identical transaction lists."""
    with get_db_session() as db:
        merchant_ids = {m.merchant_code: m.id for m in db.query(Merchant).all()}
        gateway_ids = {g.gateway_code: g.id for g in db.query(Gateway).all()}
        bank_ids = {b.bank_code: b.id for b in db.query(Bank).all()}
        payment_method_ids = {p.method_code: p.id for p in db.query(PaymentMethod).all()}

        # Run 1
        txns_1 = generate_transactions_data(
            count=500,
            seed=42,
            merchant_ids=merchant_ids,
            gateway_ids=gateway_ids,
            bank_ids=bank_ids,
            payment_method_ids=payment_method_ids,
        )

        # Run 2
        txns_2 = generate_transactions_data(
            count=500,
            seed=42,
            merchant_ids=merchant_ids,
            gateway_ids=gateway_ids,
            bank_ids=bank_ids,
            payment_method_ids=payment_method_ids,
        )

        assert len(txns_1) == len(txns_2)
        for t1, t2 in zip(txns_1, txns_2):
            assert t1["transaction_id"] == t2["transaction_id"]
            assert t1["amount"] == t2["amount"]
            assert t1["status"] == t2["status"]
            assert t1["failure_reason"] == t2["failure_reason"]
            assert t1["created_at"] == t2["created_at"]
            assert t1["gateway_id"] == t2["gateway_id"]
            assert t1["bank_id"] == t2["bank_id"]


def test_controlled_degradation():
    """Verify that the degradation scenario is present, Gateway B is not globally degraded, and the segment is significantly worse."""
    with get_db_session() as db:
        # Load mappings
        merchant_ids = {m.merchant_code: m.id for m in db.query(Merchant).all()}
        gateway_ids = {g.gateway_code: g.id for g in db.query(Gateway).all()}
        bank_ids = {b.bank_code: b.id for b in db.query(Bank).all()}
        payment_method_ids = {p.method_code: p.id for p in db.query(PaymentMethod).all()}

        # Generate a large dataset (e.g. 30,000 txns to have enough statistical power)
        txns_data = generate_transactions_data(
            count=30000,
            seed=42,
            merchant_ids=merchant_ids,
            gateway_ids=gateway_ids,
            bank_ids=bank_ids,
            payment_method_ids=payment_method_ids,
        )

        # Drop existing transactions from the test run if any, and bulk insert
        db.query(Transaction).delete()
        db.commit()
        db.bulk_insert_mappings(Transaction, txns_data)
        db.commit()

        # Gateway B codes/IDs
        g_b_id = gateway_ids["GATEWAY_B"]
        pm_upi_id = payment_method_ids["UPI"]
        b_sbi_id = bank_ids["SBI"]

        # 1. Verify Gateway B is NOT globally degraded (overall success rate should be high, e.g. > 88%)
        total_g_b = db.query(func.count(Transaction.id)).filter(Transaction.gateway_id == g_b_id).scalar()
        success_g_b = db.query(func.count(Transaction.id)).filter(
            Transaction.gateway_id == g_b_id, Transaction.status == "SUCCESS"
        ).scalar()
        global_rate = (success_g_b / total_g_b * 100) if total_g_b else 0.0
        assert global_rate > 88.0, f"Gateway B is globally degraded! Success rate: {global_rate:.2f}%"

        # 2. Extract window helper
        day_filters = []
        for d_str in INCIDENT_CONFIG["dates"]:
            day_filters.append(
                and_(
                    func.date(Transaction.created_at) == datetime.strptime(d_str, "%Y-%m-%d").date(),
                    func.extract("hour", Transaction.created_at).in_(INCIDENT_CONFIG["hours"])
                )
            )
        incident_time_filter = or_(*day_filters)

        # 3. Affected segment
        affected_filter = and_(
            Transaction.gateway_id == g_b_id,
            Transaction.payment_method_id == pm_upi_id,
            Transaction.bank_id == b_sbi_id,
            incident_time_filter
        )
        affected_total = db.query(func.count(Transaction.id)).filter(affected_filter).scalar()
        affected_success = db.query(func.count(Transaction.id)).filter(affected_filter).filter(Transaction.status == "SUCCESS").scalar()
        affected_rate = (affected_success / affected_total * 100) if affected_total else 0.0

        # 4. Normal segment
        normal_filter = and_(
            Transaction.gateway_id == g_b_id,
            Transaction.payment_method_id == pm_upi_id,
            Transaction.bank_id == b_sbi_id,
            ~incident_time_filter
        )
        normal_total = db.query(func.count(Transaction.id)).filter(normal_filter).scalar()
        normal_success = db.query(func.count(Transaction.id)).filter(normal_filter).filter(Transaction.status == "SUCCESS").scalar()
        normal_rate = (normal_success / normal_total * 100) if normal_total else 0.0

        # Assertions
        assert affected_total > 50, f"Too few transactions in affected window: {affected_total}"
        assert affected_rate < 85.0, f"Degradation not significant: {affected_rate:.2f}%"
        assert normal_rate > 90.0, f"Normal segment is also degraded: {normal_rate:.2f}%"

        print(f"\n[Test Result] Normal Success Rate: {normal_rate:.2f}%")
        print(f"[Test Result] Affected Success Rate: {affected_rate:.2f}%")
        print(f"[Test Result] Degradation Difference: {normal_rate - affected_rate:.2f} percentage points")
