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
| Client names include branch, e.g. `BrandX(Branch1)` | Split into `brand` + `location`; each branch is its own customer |
| Product names inconsistent (`Bags` / `bags`, `Bags&Box`) | Standardise names and map to a products table |
| Rows not in date order | Sort by date; don't rely on the `#` column for order sequence |
| Only one order has an invoice number | Keep `invoice_no` as an optional column |
| Unit for `Qty` not documented | To confirm (see open questions) |

## Database design
- **customers**: `customer_id`, `customer_code` (anonymised), `brand`, `location`, `business_type` (NULL for real customers), `first_order_date`, `is_synthetic`
- **products**: `product_id`, `product_name`, `category`, `print_only` (boolean)
- **orders**: `order_id`, `customer_id`, `order_date`, `fulfilment_status`, `payment_status`, `invoice_no`, `total_eur`, `is_synthetic`
- **order_items**: `order_item_id`, `order_id`, `product_id`, `qty`, `line_total_eur`

Stage 3 (sales funnel, simulated data only):
- **prospects**: `prospect_id`, `prospect_code`, `business_type`, `area`, `first_contact_date`, `channel` (walk-in / phone / email), `outcome` (no_interest / quoted / won), `customer_id` (set only when won), `is_synthetic`
- **quotes**: `quote_id`, `prospect_id`, `quote_date`, `product_id`, `qty`, `amount_eur`, `status` (sent / accepted / rejected / expired), `is_synthetic`

Real and simulated data cannot be mixed: foreign keys from orders and prospects to customers include `is_synthetic`, so the database rejects a link between a real record and a simulated one.

## Metrics (SQL views)
1. Monthly revenue, order count and average order value
2. Revenue and order count by customer, with first and last order date
3. Repeat-customer rate (customers with 2+ orders)
4. Outstanding balance by customer, and days since order (an ageing view)
5. Revenue and quantity by product
6. Stage 3: sales funnel by month and channel (`v_sales_funnel`), quotes still waiting for a reply (`v_outstanding_quotes`), quote acceptance by channel and business type (`v_quote_conversion`)

Every view carries a `data_source` column (`Real` / `Simulated`) so the dashboard can filter on it.

### Why the dashboard reads CSV exports, not the live database
Tableau Public (the free, publicly shareable version) cannot connect to a PostgreSQL server. It only reads files, and a published workbook can't reach a database running on my laptop anyway. So `scripts/export_views.py` writes each view to `dashboard/data/*.csv` and Tableau reads those. PostgreSQL stays the single source of truth, so all metric logic lives in the SQL views and Tableau only draws charts. The trade-off is that the dashboard is a snapshot: after any data change I re-run `load_db.py` and `export_views.py`, then refresh the Tableau extract. The exports contain only anonymised data, so they are safe to commit.

## Milestones
- [x] **Stage 1: Database.** Schema created, real orders cleaned, anonymised and loaded, totals checked against the spreadsheet.
- [x] **Stage 2: Dashboard.** SQL views built, Tableau Public dashboard published, README updated with screenshots and an "insights and decisions" section.
- [x] **Stage 3: Sales funnel (optional).** Simulated prospects, quotes, customers and orders added and flagged, funnel views built (links the project to sales development). Not yet added to the Tableau dashboard.

## Validation checks (stage 1)
After loading, the database must match the spreadsheet, **filtered to real data only (`is_synthetic = false`)**:
- 15 orders
- 8 customers
- Total revenue €2,565.99
- Paid €1,511.59, unpaid €1,054.40
- 1 invoice number

`load_db.py` also checks the simulated data: row counts match the CSVs, every won prospect links to a customer, every simulated order belongs to a simulated customer, and nothing simulated falls outside 1 Jun – 15 Oct 2026.

## Simulated data: generation rules (stage 3)
`scripts/generate_synthetic.py` writes `data/synthetic/*.csv`. Fixed seed (2026), so output is reproducible. All rows are flagged `is_synthetic = true`.
- **Period:** 1 June to 15 October 2026.
- **Prospects:** about 20 per month (18–22; 9–11 for the half month of October). Channel mix fixed at 60% walk-in, 25% phone, 15% email. Business type 40% café, 25% restaurant, 35% takeaway, random Dublin area.
- **Quotes:** exactly 40% of prospects are quoted; exactly 36% of all quotes are accepted (about 38% of decided quotes). Chosen at random: **no channel or business-type advantage is built in**, so differences in the views are noise.
- **Open quotes:** quotes dated after 30 Sep stay `sent` with 75% probability, giving a few outstanding quotes. Other non-accepted quotes are rejected (55%) or expired (45%).
- **Customers:** each accepted quote becomes `SIM-CUST-nn`; the first order is the quoted product, quantity and amount, dated 0–5 days after the quote.
- **Re-orders:** each customer has their own typical gap (14–42 days, ±30%). After every order there is a 25% chance they stop. 80% of re-orders repeat the same product.
- **Order size and price:** quantity and unit-price ranges per product come from the real orders (widened slightly for products with fewer than 3 real orders). Simulated orders go only to simulated customers.
- **Payment:** 40% of customers are slow payers (85% of their orders unpaid); the fast payers' unpaid rate is set so that the overall share of unpaid *orders* matches the real data (46.7%). Payment behaviour does **not** change over time, so the simulation does not show any recommendation working.
- **Limits:** the funnel rates are assumptions, not measurements. Recent months look weaker because their quotes are still undecided.

## Open questions
- What unit is `Qty` (individual boxes, or packs or cartons)?
- Are there orders after 30 May 2026 that aren't in the tracker yet?
- Is there a record of businesses approached and quotes sent that didn't turn into orders? (Stage 3 simulates this; real records would replace the simulation.)

## Working rules for Claude Code
- Explain each decision briefly; I need to be able to defend this code in an interview.
- Make small changes and suggest a commit message after each working step.
- Never write real credentials or real customer names into committed files.
- Ask before adding new tools or libraries.
