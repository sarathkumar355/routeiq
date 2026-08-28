"""Database initialization and seeding.

Creates all tables defined in SQLAlchemy models and populates reference data
for merchants, gateways, banks, and payment methods.
"""

import argparse
import sys
from datetime import datetime
from sqlalchemy import text
from app.config import get_settings
from app.db.session import get_engine, get_db_session
from app.models.base import Base
from app.models.merchant import Merchant
from app.models.gateway import Gateway
from app.models.bank import Bank
from app.models.payment_method import PaymentMethod


def seed_reference_data(db) -> None:
    """Seed reference data for merchants, gateways, banks, and payment methods if they do not exist."""
    print("Seeding reference data...")

    # 1. Fictional Merchants
    merchants = [
        {"merchant_code": "SHOPKART", "name": "ShopKart"},
        {"merchant_code": "QUICKBITE", "name": "QuickBite"},
        {"merchant_code": "URBANMART", "name": "UrbanMart"},
        {"merchant_code": "FOODFLEET", "name": "FoodFleet"},
        {"merchant_code": "NOVARETAIL", "name": "NovaRetail"},
    ]
    for m in merchants:
        existing = db.query(Merchant).filter_by(merchant_code=m["merchant_code"]).first()
        if not existing:
            db.add(Merchant(merchant_code=m["merchant_code"], name=m["name"]))
            print(f"Added Merchant: {m['name']}")

    # 2. Simulated Gateways
    gateways = [
        {"gateway_code": "GATEWAY_A", "name": "Gateway A", "active": True},
        {"gateway_code": "GATEWAY_B", "name": "Gateway B", "active": True},
        {"gateway_code": "GATEWAY_C", "name": "Gateway C", "active": True},
        {"gateway_code": "GATEWAY_D", "name": "Gateway D", "active": True},
    ]
    for g in gateways:
        existing = db.query(Gateway).filter_by(gateway_code=g["gateway_code"]).first()
        if not existing:
            db.add(
                Gateway(
                    gateway_code=g["gateway_code"],
                    name=g["name"],
                    active=g["active"],
                )
            )
            print(f"Added Gateway: {g['name']}")

    # 3. Banks
    banks = [
        {"bank_code": "SBI", "name": "State Bank of India", "active": True},
        {"bank_code": "HDFC", "name": "HDFC Bank", "active": True},
        {"bank_code": "ICICI", "name": "ICICI Bank", "active": True},
        {"bank_code": "AXIS", "name": "Axis Bank", "active": True},
        {"bank_code": "KOTAK", "name": "Kotak Mahindra Bank", "active": True},
        {"bank_code": "PNB", "name": "Punjab National Bank", "active": True},
        {"bank_code": "BOB", "name": "Bank of Baroda", "active": True},
        {"bank_code": "YES", "name": "Yes Bank", "active": True},
    ]
    for b in banks:
        existing = db.query(Bank).filter_by(bank_code=b["bank_code"]).first()
        if not existing:
            db.add(Bank(bank_code=b["bank_code"], name=b["name"], active=b["active"]))
            print(f"Added Bank: {b['name']}")

    # 4. Payment Methods
    payment_methods = [
        {"method_code": "UPI", "name": "UPI"},
        {"method_code": "CARD", "name": "CARD"},
        {"method_code": "NETBANKING", "name": "NETBANKING"},
    ]
    for p in payment_methods:
        existing = db.query(PaymentMethod).filter_by(method_code=p["method_code"]).first()
        if not existing:
            db.add(PaymentMethod(method_code=p["method_code"], name=p["name"]))
            print(f"Added Payment Method: {p['name']}")

    db.commit()
    print("Reference data seeding complete.")


def init_db(reset: bool = False) -> None:
    """Initialize database tables and reference data.

    If reset is True, drops all tables before creating them.
    """
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set. Cannot initialize database.")
        sys.exit(1)

    engine = get_engine()

    if reset:
        print("Resetting database (dropping all tables)...")
        # Ensure we are dropping tables associated with Base
        Base.metadata.drop_all(bind=engine)
        print("Tables dropped.")

    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    with get_db_session() as db:
        seed_reference_data(db)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize RouteIQ database tables.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate all tables (WARNING: deletes all data).",
    )
    args = parser.parse_args()
    init_db(reset=args.reset)
