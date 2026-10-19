# Pakure Analytics

**An end-to-end analytics project built on the real order data of my own packaging business: Python cleaning, a PostgreSQL database, SQL metric views and a published Tableau dashboard that shows where the money is and where it's stuck.**

[**View the live dashboard on Tableau Public**](https://public.tableau.com/app/profile/ibrahim.abushaban/viz/PakureSolutionsDashboard/PakureDashboard)

[![Pakure Solutions dashboard](dashboard/dashboard.png)](https://public.tableau.com/app/profile/ibrahim.abushaban/viz/PakureSolutionsDashboard/PakureDashboard)

## Background
Pakure Solutions is a custom-branded packaging business (pizza boxes, paper bags) that I founded in April 2025 and run myself, selling to cafés, restaurants and takeaways in Dublin. Orders were tracked in a Google Sheet. This project turns that sheet into a database and a dashboard so I can make decisions from it.

## Business questions it answers
- How much revenue are we making each month, and is it growing?
- Which customers matter most, and which ones re-order?
- How much money is owed to us, by whom, and for how long?
- Which products sell best, and what is a typical order worth?

## Key findings
Based on 15 orders from 8 customers, Feb–May 2026 (a small sample, so treat these as signals rather than statistics):

- **Cash is the biggest issue.** 41% of revenue (€1,054 of €2,566) is unpaid, and one customer owes €580 across four orders. The oldest unpaid orders date from April 2026. *Recommendation: ask for payment on delivery.*
- **Bags drive the business.** Bags are 60% of revenue (€1,550). *Recommendation: lead with bags when prospecting.*
- **Customers come back.** 5 of 8 customers (62.5%) have re-ordered, which suggests the product is good enough to earn repeat business.
- **Growth is recent.** Revenue went from €175 in February to €1,936 in May, with no orders in March. The tracker currently ends in May 2026.

## Tech stack
| Part | Tool |
|---|---|
| Cleaning and loading | Python 3, pandas, psycopg 3 |
| Database | PostgreSQL |
| Metrics | SQL views |
| Dashboard | Tableau Public |
| Version control | Git + GitHub |

## How the pipeline works
```
Google Sheets export (raw, local only)
        │  scripts/clean_orders.py   fixes data problems, anonymises customers
        ▼
data/clean/orders_clean.csv
        │  scripts/load_db.py        creates DB, runs sql/01_schema.sql, loads data, runs sql/02_views.sql
        ▼
PostgreSQL  (customers, products, orders, order_items + 5 metric views)
        │  scripts/export_views.py   one CSV per view
        ▼
dashboard/data/*.csv  →  Tableau Public
```

- **Cleaning** (`clean_orders.py`): splits the mixed delivery/payment status into two fields, separates brand from branch, standardises product names, parses DD/MM/YYYY dates explicitly, sorts by date, and stops with an error on unexpected values instead of guessing.
- **Database** (`sql/01_schema.sql`): four tables with foreign keys, `CHECK` constraints and `NUMERIC` money columns so totals are exact to the cent.
- **Metrics** (`sql/02_views.sql`): monthly revenue, revenue by customer, repeat-customer rate, outstanding balance with ageing, and revenue by product. All metric logic lives in SQL, and Tableau only draws it.
- **Validation:** after loading, the script checks the database against the spreadsheet (15 orders, 8 customers, €2,565.99 total, €1,511.59 paid, €1,054.40 unpaid, 1 invoice number).
- **Why CSV exports for Tableau?** Tableau Public can't connect to a PostgreSQL server, so views are exported to files. See [PLAN.md](PLAN.md).

## Data honesty
- The data is **real**: it comes from my own business's order tracker.
- Customers are **anonymised** (`CUST-01`, `BRAND-01`, …) before anything is committed. The raw export, which has real names, stays on my computer and is git-ignored.
- No synthetic data is used. The schema has an `is_synthetic` flag so that any generated rows could be kept separate and labelled.
- Known limitation: the unit of `Qty` (individual boxes vs packs) isn't documented in the tracker, so per-unit figures are indicative only.

## How to run it
Requires Python 3.10+ and a local PostgreSQL server.

```bash
pip install -r requirements.txt
cp .env.example .env            # then fill in DB_PASSWORD
python scripts/load_db.py       # creates the "pakure" database, schema, data and views
python scripts/export_views.py  # writes dashboard/data/*.csv
```

The repo includes the anonymised `data/clean/orders_clean.csv`, so you can run the steps above without the raw file. To rebuild from your own export, put it at `data/raw/orders_raw.csv` (title on row 1, headers on row 2) and run `python scripts/clean_orders.py` first.

## Project structure
```
data/clean/        anonymised, cleaned orders (safe to commit)
sql/               01_schema.sql (tables), 02_views.sql (metric views)
scripts/           clean_orders.py, load_db.py, export_views.py
dashboard/         screenshot, packaged Tableau workbook, exported view CSVs
PLAN.md            project plan and decisions
```

## Author
Ibrahim Abushaban, founder of Pakure Solutions. [LinkedIn](https://www.linkedin.com/in/ibrahim-abushaban)
