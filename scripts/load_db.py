"""Create the pakure database (if missing), build the schema, load real then simulated data, build views.

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
SYNTHETIC = ROOT / "data" / "synthetic"
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

# keep_default_na=False: blank stays "" (not NaN); we turn blanks into SQL NULL below.
read_csv = lambda path: pd.read_csv(path, dtype=str, keep_default_na=False)
blank_to_none = lambda v: v if v != "" else None


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


def insert_order(cur, customer_id: int, product_id: int, r, synthetic: bool) -> None:
    """One order plus its single product line (every order has one product)."""
    cur.execute(
        "INSERT INTO orders (customer_id, order_date, fulfilment_status, payment_status, "
        "invoice_no, total_eur, is_synthetic) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING order_id",
        (customer_id, r["order_date"], r["fulfilment_status"], r["payment_status"],
         blank_to_none(r["invoice_no"]), r["total_eur"], synthetic),
    )
    order_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO order_items (order_id, product_id, qty, line_total_eur) VALUES (%s, %s, %s, %s)",
        (order_id, product_id, int(r["qty"]), r["total_eur"]),
    )


def load_real(cur) -> dict:
    """Load the real, anonymised orders. Returns the product ids so simulated data can reuse them."""
    df = read_csv(CLEAN)
    # customers: one row per code; first_order_date = earliest order. is_synthetic defaults to FALSE.
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
    for _, r in df.iterrows():
        insert_order(cur, cust_ids[r["customer_code"]], prod_ids[r["product_name"]], r, r["is_synthetic"] == "True")
    return prod_ids


def load_synthetic(cur, prod_ids: dict) -> dict:
    """Load the simulated customers, prospects, quotes and orders. Returns CSV row counts."""
    customers = read_csv(SYNTHETIC / "customers.csv")
    prospects = read_csv(SYNTHETIC / "prospects.csv")
    quotes = read_csv(SYNTHETIC / "quotes.csv")
    orders = read_csv(SYNTHETIC / "orders.csv")
    # Every row must carry the flag, otherwise it could be mistaken for real data.
    for name, df in [("customers", customers), ("prospects", prospects), ("quotes", quotes), ("orders", orders)]:
        if not (df["is_synthetic"] == "True").all():
            raise ValueError(f"{name}.csv has rows not flagged is_synthetic = True")

    cust_ids = {}
    for _, r in customers.iterrows():
        cur.execute(
            "INSERT INTO customers (customer_code, brand, location, business_type, first_order_date, is_synthetic) "
            "VALUES (%s, %s, %s, %s, %s, TRUE) RETURNING customer_id",
            (r["customer_code"], r["brand"], blank_to_none(r["location"]), r["business_type"], r["first_order_date"]),
        )
        cust_ids[r["customer_code"]] = cur.fetchone()[0]

    prospect_ids = {}
    for _, r in prospects.iterrows():
        cur.execute(
            "INSERT INTO prospects (prospect_code, business_type, area, first_contact_date, channel, outcome, "
            "customer_id, is_synthetic) VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE) RETURNING prospect_id",
            (r["prospect_code"], r["business_type"], r["area"], r["first_contact_date"], r["channel"], r["outcome"],
             cust_ids[r["customer_code"]] if r["customer_code"] else None),
        )
        prospect_ids[r["prospect_code"]] = cur.fetchone()[0]

    for _, r in quotes.iterrows():
        cur.execute(
            "INSERT INTO quotes (prospect_id, quote_date, product_id, qty, amount_eur, status, is_synthetic) "
            "VALUES (%s, %s, %s, %s, %s, %s, TRUE)",
            (prospect_ids[r["prospect_code"]], r["quote_date"], prod_ids[r["product_name"]], int(r["qty"]),
             r["amount_eur"], r["status"]),
        )

    for _, r in orders.iterrows():
        insert_order(cur, cust_ids[r["customer_code"]], prod_ids[r["product_name"]], r, True)
    return {"customers": len(customers), "prospects": len(prospects), "quotes": len(quotes), "orders": len(orders)}


def validate(conn: psycopg.Connection, sim: dict) -> bool:
    """Real-only checks against PLAN.md, then integrity checks on the simulated data."""
    q = lambda s: conn.execute(s).fetchone()[0]
    real = "WHERE NOT is_synthetic"
    real_checks = [
        ("Orders", q(f"SELECT COUNT(*) FROM orders {real}"), 15),
        ("Customers", q(f"SELECT COUNT(*) FROM customers {real}"), 8),
        ("Total revenue (EUR)", float(q(f"SELECT SUM(total_eur) FROM orders {real}")), 2565.99),
        ("Paid (EUR)", float(q(f"SELECT SUM(total_eur) FROM orders {real} AND payment_status='Paid'")), 1511.59),
        ("Unpaid (EUR)", float(q(f"SELECT SUM(total_eur) FROM orders {real} AND payment_status='Unpaid'")), 1054.40),
        ("Orders with an invoice number", q(f"SELECT COUNT(invoice_no) FROM orders {real}"), 1),
        ("Line totals = order totals (EUR)",
         float(q("SELECT SUM(i.line_total_eur) FROM order_items i JOIN orders o USING (order_id) WHERE NOT o.is_synthetic")),
         2565.99),
    ]
    sim_checks = [
        ("Simulated customers loaded", q("SELECT COUNT(*) FROM customers WHERE is_synthetic"), sim["customers"]),
        ("Simulated orders loaded", q("SELECT COUNT(*) FROM orders WHERE is_synthetic"), sim["orders"]),
        ("Prospects loaded", q("SELECT COUNT(*) FROM prospects"), sim["prospects"]),
        ("Quotes loaded", q("SELECT COUNT(*) FROM quotes"), sim["quotes"]),
        ("Won prospects with no customer", q("SELECT COUNT(*) FROM prospects WHERE outcome='won' AND customer_id IS NULL"), 0),
        ("Simulated customers with no won prospect",
         q("SELECT COUNT(*) FROM customers c WHERE c.is_synthetic AND NOT EXISTS "
           "(SELECT 1 FROM prospects p WHERE p.customer_id = c.customer_id AND p.outcome='won')"), 0),
        ("Won prospects without exactly 1 accepted quote",
         q("SELECT COUNT(*) FROM prospects p WHERE (p.outcome='won') <> "
           "((SELECT COUNT(*) FROM quotes x WHERE x.prospect_id = p.prospect_id AND x.status='accepted') = 1)"), 0),
        ("Orders whose flag differs from their customer's",
         q("SELECT COUNT(*) FROM orders o JOIN customers c USING (customer_id) WHERE o.is_synthetic <> c.is_synthetic"), 0),
        ("Prospects/quotes not flagged simulated",
         q("SELECT (SELECT COUNT(*) FROM prospects WHERE NOT is_synthetic) + (SELECT COUNT(*) FROM quotes WHERE NOT is_synthetic)"), 0),
        ("Simulated orders outside 1 Jun - 15 Oct 2026",
         q("SELECT COUNT(*) FROM orders WHERE is_synthetic AND order_date NOT BETWEEN '2026-06-01' AND '2026-10-15'"), 0),
        ("Customers whose first_order_date is wrong",
         q("SELECT COUNT(*) FROM customers c WHERE first_order_date <> "
           "(SELECT MIN(order_date) FROM orders o WHERE o.customer_id = c.customer_id)"), 0),
    ]

    ok = True
    for title, checks in [("Validation: REAL data only (is_synthetic = false), against PLAN.md", real_checks),
                          ("Validation: SIMULATED data integrity", sim_checks)]:
        print(f"\n{title}")
        for name, got, want in checks:
            match = abs(got - want) < 0.005
            ok &= match
            print(f"  {'OK  ' if match else 'FAIL'} {name:<48} database={got:<10} expected={want}")
    return ok


def main() -> None:
    ensure_database()
    # `with` on a connection commits on success and rolls back on error, so a
    # failed load never leaves half-loaded tables.
    with psycopg.connect(dbname=DB_NAME, **CONN) as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))  # drops and recreates tables
        with conn.cursor() as cur:
            prod_ids = load_real(cur)          # real first, so real customers/orders get the lowest ids
            sim = load_synthetic(cur, prod_ids)
        # Views are built after the data so they sit on top of final tables;
        # they're in the same transaction, so a broken view rolls back the load too.
        conn.execute(VIEWS.read_text(encoding="utf-8"))
        print("Created metric views from 02_views.sql")
        ok = validate(conn, sim)
    print("\nAll checks passed" if ok else "\nCHECKS FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
