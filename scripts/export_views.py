"""Export each metric view to a CSV in dashboard/data/ for Tableau Public.

Run after load_db.py:  python scripts/export_views.py
"""
import csv
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "data"

# Explicit list, not "every view in the database": the export is the dashboard's
# contract, so adding a view shouldn't silently change what gets published.
VIEWS = [
    "v_monthly_revenue",
    "v_customer_revenue",
    "v_repeat_customer_rate",
    "v_outstanding_balance",
    "v_product_sales",
    "v_sales_funnel",
    "v_outstanding_quotes",
    "v_quote_conversion",
]


def main() -> None:
    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(
        host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"], dbname=os.environ["DB_NAME"],
    ) as conn:
        for view in VIEWS:
            # View names come from the fixed list above, never from user input,
            # so building the query string here is safe.
            cur = conn.execute(f"SELECT * FROM {view}")
            headers = [col.name for col in cur.description]
            rows = cur.fetchall()
            path = OUT / f"{view.removeprefix('v_')}.csv"
            # utf-8 with newline="" so csv controls line endings; NULL becomes an empty cell.
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(headers)
                w.writerows(rows)
            print(f"Exported {len(rows):>2} rows -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
