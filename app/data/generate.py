"""Synthetic transaction data generator for RouteIQ.

Generates realistic and reproducible payment transactions with customizable
counts and seeds. Injects a controlled degradation event.
"""

import argparse
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, List

from sqlalchemy import select, func, and_
from app.config import get_settings
from app.db.session import get_engine, get_db_session
from app.db.init_db import init_db
from app.models.merchant import Merchant
from app.models.gateway import Gateway
from app.models.bank import Bank
from app.models.payment_method import PaymentMethod
from app.models.transaction import Transaction

# --- Centralized Incident Configuration ---
INCIDENT_CONFIG = {
    "gateway_code": "GATEWAY_B",
    "payment_method_code": "UPI",
    "bank_code": "SBI",
    "dates": {"2026-08-21", "2026-08-22"},
    "hours": [18, 19, 20, 21],  # 18:00 - 22:00 (exclusive of 22:00)
    "degradation_delta": 0.15,
}

# --- Indian States/Regions ---
GEOGRAPHIES = [
    "Maharashtra",
    "Karnataka",
    "Delhi",
    "Tamil Nadu",
    "Telangana",
    "Uttar Pradesh",
    "West Bengal",
    "Gujarat",
]

# --- Daily Traffic Distribution ---
# Weights for each of the 24 hours of the day (0-23)
# Simulates peak traffic in the afternoon and evening, moderate in morning, low at night.
HOURLY_TRAFFIC_WEIGHTS = [
    10, 8, 5, 4, 6, 12,      # 00:00 - 05:00 (Late Night)
    25, 40, 55, 70, 80, 85,  # 06:00 - 11:00 (Morning)
    90, 85, 80, 75, 85, 100, # 12:00 - 17:00 (Afternoon)
    120, 130, 125, 110, 80, 45 # 18:00 - 23:00 (Evening)
]


def generate_transactions_data(
    count: int,
    seed: int,
    merchant_ids: Dict[str, int],
    gateway_ids: Dict[str, int],
    bank_ids: Dict[str, int],
    payment_method_ids: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Generate in-memory representation of transaction dictionaries."""
    random.seed(seed)
    transactions = []

    # Map codes to IDs for internal generator reference (sorted for absolute determinism)
    merchant_codes = sorted(list(merchant_ids.keys()))
    gateway_codes = sorted(list(gateway_ids.keys()))
    bank_codes = sorted(list(bank_ids.keys()))
    payment_method_codes = sorted(list(payment_method_ids.keys()))

    # Date range: 7 days from August 18, 2026 to August 24, 2026
    start_date = datetime(2026, 8, 18, 0, 0, 0)
    total_days = 7

    # Reference weights for distributions aligned to alphabetical codes
    # FOODFLEET (0.12), NOVARETAIL (0.10), QUICKBITE (0.25), SHOPKART (0.35), URBANMART (0.18)
    merchant_weights = [0.12, 0.10, 0.25, 0.35, 0.18]
    # GATEWAY_A (0.40), GATEWAY_B (0.25), GATEWAY_C (0.20), GATEWAY_D (0.15)
    gateway_weights = [0.40, 0.25, 0.20, 0.15]
    # AXIS (0.12), BOB (0.05), HDFC (0.20), ICICI (0.18), KOTAK (0.10), PNB (0.06), SBI (0.25), YES (0.04)
    bank_weights = [0.12, 0.05, 0.20, 0.18, 0.10, 0.06, 0.25, 0.04]
    # CARD (0.30), NETBANKING (0.15), UPI (0.55)
    method_weights = [0.30, 0.15, 0.55]

    for i in range(count):
        # 1. Timestamp generation using hourly traffic distribution
        day_offset = random.randint(0, total_days - 1)
        tx_day = start_date + timedelta(days=day_offset)
        
        # Pick hour based on defined traffic weights
        hours = list(range(24))
        tx_hour = random.choices(hours, weights=HOURLY_TRAFFIC_WEIGHTS, k=1)[0]
        tx_minute = random.randint(0, 59)
        tx_second = random.randint(0, 59)
        
        tx_time = tx_day.replace(hour=tx_hour, minute=tx_minute, second=tx_second)

        # 2. Select foreign keys
        merchant_code = random.choices(merchant_codes, weights=merchant_weights, k=1)[0]
        gateway_code = random.choices(gateway_codes, weights=gateway_weights, k=1)[0]
        bank_code = random.choices(bank_codes, weights=bank_weights, k=1)[0]
        method_code = random.choices(payment_method_codes, weights=method_weights, k=1)[0]
        geography = random.choice(GEOGRAPHIES)

        # 3. Select amount
        # Amount ranges: 75% small, 20% medium, 5% large
        amt_roll = random.random()
        if amt_roll < 0.75:
            amount = Decimal(f"{random.uniform(10.0, 3000.0):.2f}")
        elif amt_roll < 0.95:
            amount = Decimal(f"{random.uniform(3000.0, 25000.0):.2f}")
        else:
            amount = Decimal(f"{random.uniform(25000.0, 95000.0):.2f}")

        # 4. Probability calculations (Baseline simulated success rates)
        # Base gateway rates
        base_rates = {
            "GATEWAY_A": 0.95,
            "GATEWAY_B": 0.93,
            "GATEWAY_C": 0.91,
            "GATEWAY_D": 0.88,
        }
        success_prob = base_rates[gateway_code]

        # Method adjustments
        if method_code == "UPI":
            success_prob += 0.02
        elif method_code == "NETBANKING":
            success_prob -= 0.02

        # Bank adjustments
        if bank_code in ["HDFC", "ICICI"]:
            success_prob += 0.01
        elif bank_code in ["SBI", "PNB", "BOB"]:
            success_prob -= 0.02

        # Amount adjustment
        if amount > 50000:
            success_prob -= 0.05

        # Time of day adjustment (evening hours network load)
        if 18 <= tx_hour < 22:
            success_prob -= 0.02

        # Ensure probability stays in valid bounds before checking incident override
        success_prob = max(0.10, min(0.99, success_prob))

        # 5. Injected Incident Check
        is_incident_match = (
            gateway_code == INCIDENT_CONFIG["gateway_code"]
            and method_code == INCIDENT_CONFIG["payment_method_code"]
            and bank_code == INCIDENT_CONFIG["bank_code"]
            and tx_time.strftime("%Y-%m-%d") in INCIDENT_CONFIG["dates"]
            and tx_hour in INCIDENT_CONFIG["hours"]
        )

        if is_incident_match:
            success_prob -= INCIDENT_CONFIG["degradation_delta"]
            # Ensure probability stays in valid bounds after applying degradation
            success_prob = max(0.01, success_prob)

        # 6. Status determination
        roll = random.random()
        if roll < success_prob:
            status = "SUCCESS"
            failure_reason = None
        else:
            status = "FAILED"
            # Assign failure reasons based on method
            if method_code == "UPI":
                reasons = ["INSUFFICIENT_FUNDS", "TIMEOUT", "BANK_DECLINED", "NETWORK_ERROR"]
                weights = [0.45, 0.25, 0.20, 0.10]
            elif method_code == "CARD":
                reasons = ["INVALID_DETAILS", "BANK_DECLINED", "LIMIT_EXCEEDED", "GATEWAY_ERROR"]
                weights = [0.35, 0.25, 0.20, 0.20]
            else:  # NETBANKING
                reasons = ["TIMEOUT", "BANK_DECLINED", "NETWORK_ERROR", "INSUFFICIENT_FUNDS"]
                weights = [0.40, 0.30, 0.15, 0.15]
            
            failure_reason = random.choices(reasons, weights=weights, k=1)[0]

        # 7. Construct Transaction ID
        tx_id = f"TXN_{tx_time.strftime('%y%m%d%H%M')}_{i:06d}_{random.randint(100, 999)}"

        transactions.append(
            {
                "transaction_id": tx_id,
                "merchant_id": merchant_ids[merchant_code],
                "gateway_id": gateway_ids[gateway_code],
                "bank_id": bank_ids[bank_code],
                "payment_method_id": payment_method_ids[method_code],
                "amount": amount,
                "currency": "INR",
                "status": status,
                "failure_reason": failure_reason,
                "geography": geography,
                "created_at": tx_time,
            }
        )

    return transactions


def print_incident_report() -> None:
    """Read generated data from the database and print metrics regarding the incident and revenue at risk."""
    with get_db_session() as db:
        # Get Gateway B, UPI, and SBI details
        g_b = db.query(Gateway).filter_by(gateway_code=INCIDENT_CONFIG["gateway_code"]).first()
        pm_upi = db.query(PaymentMethod).filter_by(method_code=INCIDENT_CONFIG["payment_method_code"]).first()
        b_sbi = db.query(Bank).filter_by(bank_code=INCIDENT_CONFIG["bank_code"]).first()

        if not (g_b and pm_upi and b_sbi):
            print("Cannot print report: reference records missing.")
            return

        # 1. Total records
        total_txns = db.query(func.count(Transaction.id)).scalar()
        total_success = db.query(func.count(Transaction.id)).filter(Transaction.status == "SUCCESS").scalar()
        print(f"\n--- DATABASE SUMMARY REPORT ---")
        print(f"Total Transactions Generated: {total_txns}")
        print(f"Overall Success Rate: {((total_success / total_txns) * 100):.2f}%" if total_txns else "0%")

        # 2. Gateway success rates
        gateways = db.query(Gateway).order_by(Gateway.gateway_code).all()
        print("\nGateway Base Performance Metrics:")
        for g in gateways:
            g_total = db.query(func.count(Transaction.id)).filter_by(gateway_id=g.id).scalar()
            g_success = db.query(func.count(Transaction.id)).filter_by(gateway_id=g.id).filter(Transaction.status == "SUCCESS").scalar()
            g_rate = (g_success / g_total * 100) if g_total else 0.0
            print(f"  * {g.name}: {g_rate:.2f}% ({g_success}/{g_total})")

        # 3. Affected segment in incident window
        # Incident window filter
        incident_dates_list = sorted(list(INCIDENT_CONFIG["dates"]))
        start_dt = datetime.strptime(f"{incident_dates_list[0]} 18:00:00", "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(f"{incident_dates_list[-1]} 22:00:00", "%Y-%m-%d %H:%M:%S")
        
        # We need hours between 18:00 and 22:00. Note that we filter by exact timestamps in the evenings.
        # Let's write an OR condition for the two days to be precise
        day_filters = []
        for d_str in INCIDENT_CONFIG["dates"]:
            day_filters.append(
                and_(
                    func.date(Transaction.created_at) == datetime.strptime(d_str, "%Y-%m-%d").date(),
                    func.extract("hour", Transaction.created_at).in_(INCIDENT_CONFIG["hours"])
                )
            )
        incident_time_filter = sqlalchemy_or_helper(day_filters)

        # Normal segment: Gateway B + UPI + SBI OUTSIDE incident hours/dates
        normal_segment_filter = and_(
            Transaction.gateway_id == g_b.id,
            Transaction.payment_method_id == pm_upi.id,
            Transaction.bank_id == b_sbi.id,
            ~incident_time_filter
        )
        
        normal_total = db.query(func.count(Transaction.id)).filter(normal_segment_filter).scalar()
        normal_success = db.query(func.count(Transaction.id)).filter(normal_segment_filter).filter(Transaction.status == "SUCCESS").scalar()
        normal_rate = (normal_success / normal_total * 100) if normal_total else 0.0

        # Affected segment: Gateway B + UPI + SBI INSIDE incident hours/dates
        affected_segment_filter = and_(
            Transaction.gateway_id == g_b.id,
            Transaction.payment_method_id == pm_upi.id,
            Transaction.bank_id == b_sbi.id,
            incident_time_filter
        )
        
        affected_total = db.query(func.count(Transaction.id)).filter(affected_segment_filter).scalar()
        affected_success = db.query(func.count(Transaction.id)).filter(affected_segment_filter).filter(Transaction.status == "SUCCESS").scalar()
        affected_rate = (affected_success / affected_total * 100) if affected_total else 0.0

        diff = normal_rate - affected_rate

        print(f"\n--- CONTROLLED DEGRADATION METRICS ---")
        print(f"Segment: {g_b.name} + {pm_upi.name} + {b_sbi.name}")
        print(f"Normal Segment (Outside Incident Window):")
        print(f"  Success Rate = {normal_rate:.2f}% ({normal_success}/{normal_total})")
        print(f"Affected Segment (Inside Incident Window):")
        print(f"  Success Rate = {affected_rate:.2f}% ({affected_success}/{affected_total})")
        print(f"Difference: {diff:.2f} percentage points")

        # 4. Revenue at Risk calculation
        # Estimated Revenue at Risk = (Expected success rate * Attempted value) - Actual success value
        # Attempted value inside incident window
        attempted_value = db.query(func.sum(Transaction.amount)).filter(affected_segment_filter).scalar() or Decimal("0.0")
        actual_success_value = db.query(func.sum(Transaction.amount)).filter(affected_segment_filter).filter(Transaction.status == "SUCCESS").scalar() or Decimal("0.0")
        
        expected_success_rate_dec = Decimal(str(normal_rate / 100.0))
        expected_success_value = attempted_value * expected_success_rate_dec
        revenue_at_risk = expected_success_value - actual_success_value

        print(f"\n--- REVENUE-AT-RISK ANALYSIS ---")
        print(f"Total Attempted Value in Window: INR {attempted_value:,.2f}")
        print(f"Actual Successful Value in Window: INR {actual_success_value:,.2f}")
        print(f"Expected Successful Value (at {normal_rate:.2f}% rate): INR {expected_success_value:,.2f}")
        print(f"Estimated Revenue at Risk: INR {revenue_at_risk:,.2f}")
        print(f"---------------------------------\n")


def sqlalchemy_or_helper(filters):
    """Clean SQLAlchemy OR combinator helper."""
    from sqlalchemy import or_
    return or_(*filters)


def main() -> None:
    """Main generation script entrypoint."""
    parser = argparse.ArgumentParser(description="Generate synthetic transaction data.")
    parser.add_argument(
        "--transactions",
        type=int,
        default=50000,
        help="Number of transactions to generate.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset database tables and seed references before generation.",
    )
    args = parser.parse_args()

    # Ensure tables are set up (reset drops them first if requested)
    init_db(reset=args.reset)

    with get_db_session() as db:
        # Load maps
        merchant_ids = {m.merchant_code: m.id for m in db.query(Merchant).all()}
        gateway_ids = {g.gateway_code: g.id for g in db.query(Gateway).all()}
        bank_ids = {b.bank_code: b.id for b in db.query(Bank).all()}
        payment_method_ids = {p.method_code: p.id for p in db.query(PaymentMethod).all()}

        if not (merchant_ids and gateway_ids and bank_ids and payment_method_ids):
            print("Error: Reference tables are empty. Please check database seeding.")
            sys.exit(1)

        print(f"Generating {args.transactions} transactions with seed {args.seed}...")
        
        # Clear existing transactions to keep the run clean
        db.query(Transaction).delete()
        db.commit()

        # Generate data
        tx_data = generate_transactions_data(
            count=args.transactions,
            seed=args.seed,
            merchant_ids=merchant_ids,
            gateway_ids=gateway_ids,
            bank_ids=bank_ids,
            payment_method_ids=payment_method_ids,
        )

        print("Inserting records into database...")
        # Insert in chunks of 10000 to keep memory optimized
        chunk_size = 10000
        for offset in range(0, len(tx_data), chunk_size):
            chunk = tx_data[offset:offset+chunk_size]
            db.bulk_insert_mappings(Transaction, chunk)
            db.commit()
            print(f"  Inserted {offset + len(chunk)} / {len(tx_data)}...")

        print("Transactions generation complete.")

    # Calculate and output metrics
    print_incident_report()


if __name__ == "__main__":
    main()
