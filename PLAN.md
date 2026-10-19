# Pakure Analytics — Project Plan

## What this is
Pakure Solutions is a custom-branded packaging business (pizza boxes, paper bags) that I founded in April 2025 and run myself, selling to cafés, restaurants and takeaways in Dublin.

This project takes the business's real order data, loads it into a PostgreSQL database, and builds an analytics dashboard that answers practical questions:
- How much revenue are we making each month, and is it growing?
- Which customers matter most, and which ones re-order?
- How much money is owed to us, and by whom?
- Which products sell best, and what is a typical order worth?

The goal is to show that data can be used to make better business decisions, not only to produce charts.

## Data honesty
- **Real data:** the order history comes from my own order tracker (Google Sheets).
- **Anonymised:** customer names are replaced with codes (e.g. `CUST-01`) before anything is committed. The raw file never leaves my computer.
- **Synthetic data:** if extra rows are generated to demonstrate the dashboard at scale, they are stored in a separate file, flagged with `is_synthetic = true` in the database, and labelled in the dashboard.

## Tech stack
| Part | Tool |
|---|---|
| Database | PostgreSQL (local, port 5432) |
| Loading and cleaning | Python 3, pandas, psycopg / SQLAlchemy |
| Metrics | SQL views in PostgreSQL |
| Dashboard | Tableau Public (published, linkable from CV) |
| Version control | Git + GitHub |

Database credentials live in a local `.env` file, which is listed in `.gitignore` and never committed. `.env.example` shows the required variable names without real values.

## Folder structure
```
pakure-analytics/
├── PLAN.md
├── README.md
├── .gitignore
├── .env.example
├── requirements.txt
├── data/
│   ├── raw/            # original export, git-ignored (real customer names)
│   └── clean/          # anonymised, cleaned CSVs, safe to commit
├── sql/
│   ├── 01_schema.sql   # tables
│   └── 02_views.sql    # metric views for the dashboard
├── scripts/
│   ├── clean_orders.py # raw export -> clean, anonymised CSV
│   └── load_db.py      # clean CSV -> PostgreSQL
└── dashboard/          # screenshots + link to Tableau Public
```

## Source data (Google Sheets "Order Tracker" tab)
Columns: `#`, `Client`, `Date` (DD/MM/YYYY), `Product`, `Qty`, `Status`, `Amount (EUR)`, `Paid`.
The first row of the export is a title, the headers are on row 2, and there are empty rows at the bottom.

### Known data problems and how they are cleaned
| Problem | Fix |
|---|---|
| `Status` mixes delivery and payment ("Delivered", "Paid") | Split into `fulfilment_status` and `payment_status`, using the `Paid` column for payment |
| Client names include branch, e.g. `Tuckinn(Tallaght)` | Split into `brand` + `location`; each branch is its own customer |
| Product names inconsistent (`Bags` / `bags`, `Bags&Box`) | Standardise names and map to a products table |
| Rows not in date order | Sort by date; don't rely on the `#` column for order sequence |
| Only one order has an invoice number | Keep `invoice_no` as an optional column |
| Unit for `Qty` not documented | To confirm (see open questions) |

## Database design
- **customers**: `customer_id`, `customer_code` (anonymised), `brand`, `location`, `business_type`, `first_order_date`
- **products**: `product_id`, `product_name`, `category`, `print_only` (boolean)
- **orders**: `order_id`, `customer_id`, `order_date`, `fulfilment_status`, `payment_status`, `invoice_no`, `total_eur`, `is_synthetic`
- **order_items**: `order_item_id`, `order_id`, `product_id`, `qty`, `line_total_eur`

Planned later (stage 3, sales funnel):
- **prospects**: businesses approached, date, channel (walk-in / phone), outcome
- **quotes**: quotes sent, amount, accepted or not

## Metrics (SQL views)
1. Monthly revenue, order count and average order value
2. Revenue and order count by customer, with first and last order date
3. Repeat-customer rate (customers with 2+ orders)
4. Outstanding balance by customer, and days since order (an ageing view)
5. Revenue and quantity by product
6. Stage 3: prospect → quote → customer conversion funnel

### Why the dashboard reads CSV exports, not the live database
Tableau Public (the free, publicly shareable version) cannot connect to a PostgreSQL server. It only reads files, and a published workbook can't reach a database running on my laptop anyway. So `scripts/export_views.py` writes each view to `dashboard/data/*.csv` and Tableau reads those. PostgreSQL stays the single source of truth, so all metric logic lives in the SQL views and Tableau only draws charts. The trade-off is that the dashboard is a snapshot: after any data change I re-run `load_db.py` and `export_views.py`, then refresh the Tableau extract. The exports contain only anonymised data, so they are safe to commit.

## Milestones
- [x] **Stage 1: Database.** Schema created, real orders cleaned, anonymised and loaded, totals checked against the spreadsheet.
- [ ] **Stage 2: Dashboard.** SQL views built, Tableau Public dashboard published, README updated with screenshots and an "insights and decisions" section.
- [ ] **Stage 3: Sales funnel (optional).** Prospects and quotes data added and a conversion funnel built (links the project to sales development).

## Validation checks (stage 1)
After loading, the database must match the spreadsheet:
- 15 orders
- 8 customers
- Total revenue €2,565.99
- Paid €1,511.59, unpaid €1,054.40

## Open questions
- What unit is `Qty` (individual boxes, or packs or cartons)?
- Are there orders after 30 May 2026 that aren't in the tracker yet?
- Is there a record of businesses approached and quotes sent that didn't turn into orders?

## Working rules for Claude Code
- Explain each decision briefly; I need to be able to defend this code in an interview.
- Make small changes and suggest a commit message after each working step.
- Never write real credentials or real customer names into committed files.
- Ask before adding new tools or libraries.
