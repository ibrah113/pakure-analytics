"""Create the pakure database (if missing), build the schema and load the clean CSV.

Run from anywhere:  python scripts/load_db.py
Credentials come from .env (never hard-coded).
"""
import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean" / "orders_clean.csv"
SCHEMA = ROOT / "sql" / "01_schema.sql"
VIEWS = ROOT / "sql" / "02_views.sql"

load_dotenv(ROOT / ".env")
CONN = dict(
    host=os.environ["DB_HOST"],
    port=os.environ["DB_PORT"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
)
DB_NAME = os.environ["DB_NAME"]


def ensure_database() -> None:
    # CREATE DATABASE can't run inside a transaction, hence autocommit, and we
    # must connect to an existing database (the built-in "postgres") to issue it.
    with psycopg.connect(dbname="postgres", autocommit=True, **CONN) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)).fetchone()
        if exists:
            print(f"Database '{DB_NAME}' already exists")
        else:
            # sql.Identifier quotes the name safely; identifiers can't be passed as %s parameters.
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            print(f"Created database '{DB_NAME}'")


def load(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text(encoding="utf-8"))  # drops and recreates tables
    df = pd.read_csv(CLEAN, dtype=str, keep_default_na=False)
    # keep_default_na=False: blank stays "" (not NaN); we turn blanks into SQL NULL below.
    blank_to_none = lambda v: v if v != "" else None

    with conn.cursor() as cur:
        # customers: one row per code; first_order_date = earliest order.
        cust_ids = {}
        for code, g in df.groupby("customer_code"):
            r = g.iloc[0]
            cur.execute(
                "INSERT INTO customers (customer_code, brand, location, first_order_date) "
                "VALUES (%s, %s, %s, %s) RETURNING customer_id",
                (code, r["brand"], blank_to_none(r["location"]), g["order_date"].min()),
            )
            cust_ids[code] = cur.fetchone()[0]

        prod_ids = {}
        for _, r in df.drop_duplicates("product_name").iterrows():
            cur.execute(
                "INSERT INTO products (product_name, category, print_only) "
                "VALUES (%s, %s, %s) RETURNING product_id",
                (r["product_name"], r["category"], r["print_only"] == "True"),
            )
            prod_ids[r["product_name"]] = cur.fetchone()[0]

        # The CSV is already sorted by date, so order_ids come out in date order.
        # Each order has one product line, so the line total equals the order total.
        for _, r in df.iterrows():
            cur.execute(
                "INSERT INTO orders (customer_id, order_date, fulfilment_status, payment_status, "
                "invoice_no, total_eur, is_synthetic) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING order_id",
                (cust_ids[r["customer_code"]], r["order_date"], r["fulfilment_status"],
                 r["payment_status"], blank_to_none(r["invoice_no"]), r["total_eur"],
                 r["is_synthetic"] == "True"),
            )
            order_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO order_items (order_id, product_id, qty, line_total_eur) "
                "VALUES (%s, %s, %s, %s)",
                (order_id, prod_ids[r["product_name"]], int(r["qty"]), r["total_eur"]),
            )


def validate(conn: psycopg.Connection) -> bool:
    """Compare database totals with the figures in PLAN.md."""
    q = lambda s: conn.execute(s).fetchone()[0]
    checks = [
        ("Orders", q("SELECT COUNT(*) FROM orders"), 15),
        ("Customers", q("SELECT COUNT(*) FROM customers"), 8),
        ("Total revenue (EUR)", float(q("SELECT SUM(total_eur) FROM orders")), 2565.99),
        ("Paid (EUR)", float(q("SELECT SUM(total_eur) FROM orders WHERE payment_status='Paid'")), 1511.59),
        ("Unpaid (EUR)", float(q("SELECT SUM(total_eur) FROM orders WHERE payment_status='Unpaid'")), 1054.40),
        ("Orders with an invoice number", q("SELECT COUNT(invoice_no) FROM orders"), 1),
        ("Line totals = order totals (EUR)",
         float(q("SELECT SUM(line_total_eur) FROM order_items")), 2565.99),
    ]
    print("\nValidation against PLAN.md")
    ok = True
    for name, got, want in checks:
        match = abs(got - want) < 0.005
        ok &= match
        print(f"  {'OK  ' if match else 'FAIL'} {name:<34} database={got:<10} expected={want}")
    return ok


def main() -> None:
    ensure_database()
    # `with` on a connection commits on success and rolls back on error, so a
    # failed load never leaves half-loaded tables.
    with psycopg.connect(dbname=DB_NAME, **CONN) as conn:
        load(conn)
        # Views are built after the data so they sit on top of final tables;
        # they're in the same transaction, so a broken view rolls back the load too.
        conn.execute(VIEWS.read_text(encoding="utf-8"))
        print("Created metric views from 02_views.sql")
        ok = validate(conn)
    print("\nAll checks passed" if ok else "\nCHECKS FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
