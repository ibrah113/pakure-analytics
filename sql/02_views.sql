-- Metric views for the dashboard. Run after 01_schema.sql and the data load.
-- CREATE OR REPLACE makes the file safe to re-run.
--
-- Every view has a data_source column ('Real' or 'Simulated') built from is_synthetic, so a
-- dashboard can filter to real data only. Never add the two together without checking it.


-- Turns the is_synthetic flag into the label shown in the dashboard.
CREATE OR REPLACE FUNCTION data_source_label(is_synthetic BOOLEAN) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$ SELECT CASE WHEN is_synthetic THEN 'Simulated' ELSE 'Real' END $$;


-- 1. Monthly revenue, order count and average order value ---------------------
-- Each data source gets every month between ITS first and last order, so a month with no
-- orders (March 2026, real) shows as 0 instead of vanishing from the chart.
CREATE OR REPLACE VIEW v_monthly_revenue AS
WITH src AS (
    SELECT data_source_label(is_synthetic)               AS data_source,
           date_trunc('month', MIN(order_date))::date    AS first_month,
           date_trunc('month', MAX(order_date))::date    AS last_month
    FROM orders
    GROUP BY is_synthetic
),
months AS (
    SELECT data_source,
           generate_series(first_month, last_month, interval '1 month')::date AS month_start
    FROM src
)
SELECT
    m.data_source,
    m.month_start,
    to_char(m.month_start, 'YYYY-MM')              AS month,
    COUNT(o.order_id)                              AS order_count,
    COALESCE(SUM(o.total_eur), 0)                  AS revenue_eur,
    -- NULLIF avoids a divide-by-zero in empty months; the average is then NULL, not 0.
    ROUND(SUM(o.total_eur) / NULLIF(COUNT(o.order_id), 0), 2) AS avg_order_value_eur
FROM months m
LEFT JOIN orders o
       ON date_trunc('month', o.order_date) = m.month_start
      AND data_source_label(o.is_synthetic) = m.data_source
GROUP BY m.data_source, m.month_start
ORDER BY m.data_source, m.month_start;


-- 2. Revenue and order count by customer, with first and last order date -----
CREATE OR REPLACE VIEW v_customer_revenue AS
SELECT
    data_source_label(c.is_synthetic) AS data_source,
    c.customer_code,
    c.brand,
    c.location,
    c.business_type,
    COUNT(o.order_id)    AS order_count,
    SUM(o.total_eur)     AS revenue_eur,
    MIN(o.order_date)    AS first_order_date,
    MAX(o.order_date)    AS last_order_date
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.is_synthetic, c.customer_code, c.brand, c.location, c.business_type
ORDER BY data_source, revenue_eur DESC;


-- 3. Repeat-customer rate (customers with 2+ orders) --------------------------
-- One row per data source. Repeat rate is a share of customers, not of orders.
CREATE OR REPLACE VIEW v_repeat_customer_rate AS
WITH per_customer AS (
    SELECT customer_id, is_synthetic, COUNT(*) AS orders
    FROM orders
    GROUP BY customer_id, is_synthetic
)
SELECT
    data_source_label(is_synthetic)                   AS data_source,
    COUNT(*)                                          AS total_customers,
    COUNT(*) FILTER (WHERE orders >= 2)               AS repeat_customers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE orders >= 2) / COUNT(*), 1) AS repeat_rate_pct
FROM per_customer
GROUP BY is_synthetic
ORDER BY data_source;


-- 4. Outstanding balance by customer, with ageing -----------------------------
-- Only unpaid orders count. Days are measured from the order date to today
-- (CURRENT_DATE), so the ageing grows each day the view is queried.
CREATE OR REPLACE VIEW v_outstanding_balance AS
SELECT
    data_source_label(o.is_synthetic)          AS data_source,
    c.customer_code,
    c.brand,
    c.location,
    COUNT(*)                                   AS unpaid_orders,
    SUM(o.total_eur)                           AS outstanding_eur,
    MIN(o.order_date)                          AS oldest_unpaid_order_date,
    CURRENT_DATE - MIN(o.order_date)           AS days_since_oldest_unpaid,
    CURRENT_DATE - MAX(o.order_date)           AS days_since_latest_unpaid
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.payment_status = 'Unpaid'
GROUP BY o.is_synthetic, c.customer_id, c.customer_code, c.brand, c.location
ORDER BY data_source, outstanding_eur DESC;


-- 5. Revenue and quantity by product ------------------------------------------
-- Revenue comes from order_items (line totals), so it stays correct if an order
-- ever has several products. The join to orders is what tells us the data source.
CREATE OR REPLACE VIEW v_product_sales AS
SELECT
    data_source_label(o.is_synthetic) AS data_source,
    p.product_name,
    p.category,
    p.print_only,
    COUNT(DISTINCT i.order_id)   AS order_count,
    SUM(i.qty)                   AS total_qty,
    SUM(i.line_total_eur)        AS revenue_eur,
    ROUND(SUM(i.line_total_eur) / SUM(i.qty), 2) AS revenue_per_unit_eur
FROM order_items i
JOIN orders o   ON o.order_id = i.order_id
JOIN products p ON p.product_id = i.product_id
GROUP BY o.is_synthetic, p.product_id, p.product_name, p.category, p.print_only
ORDER BY data_source, revenue_eur DESC;


-- 6. Sales funnel: prospects -> quoted -> won, by month and channel -----------
-- "Quoted" means the prospect received a quote at any point, so it includes the ones
-- that were later won. Months are the month of first contact. Recent months look weaker
-- than they are: their quotes may not have been decided yet.
CREATE OR REPLACE VIEW v_sales_funnel AS
SELECT
    data_source_label(p.is_synthetic)                    AS data_source,
    date_trunc('month', p.first_contact_date)::date      AS month_start,
    to_char(p.first_contact_date, 'YYYY-MM')             AS month,
    p.channel,
    COUNT(*)                                             AS prospects,
    COUNT(*) FILTER (WHERE p.outcome IN ('quoted', 'won')) AS quoted,
    COUNT(*) FILTER (WHERE p.outcome = 'won')            AS won,
    ROUND(100.0 * COUNT(*) FILTER (WHERE p.outcome IN ('quoted', 'won')) / COUNT(*), 1)
                                                         AS quote_rate_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE p.outcome = 'won')
          / NULLIF(COUNT(*) FILTER (WHERE p.outcome IN ('quoted', 'won')), 0), 1)
                                                         AS won_of_quoted_pct
FROM prospects p
GROUP BY p.is_synthetic, date_trunc('month', p.first_contact_date), to_char(p.first_contact_date, 'YYYY-MM'), p.channel
ORDER BY data_source, month_start, p.channel;


-- 7. Outstanding quotes: still "sent", waiting for a reply --------------------
-- Days open runs to today (CURRENT_DATE), the same convention as the balance ageing view.
CREATE OR REPLACE VIEW v_outstanding_quotes AS
SELECT
    data_source_label(q.is_synthetic)  AS data_source,
    q.quote_id,
    p.prospect_code,
    p.business_type,
    p.area,
    p.channel,
    q.quote_date,
    pr.product_name,
    q.qty,
    q.amount_eur,
    CURRENT_DATE - q.quote_date        AS days_open
FROM quotes q
JOIN prospects p ON p.prospect_id = q.prospect_id
JOIN products pr ON pr.product_id = q.product_id
WHERE q.status = 'sent'
ORDER BY days_open DESC;


-- 8. Quote conversion by channel and business type ----------------------------
-- Acceptance rate = accepted / quotes that have been decided. Quotes still "sent" are
-- left out of the rate, because counting them as failures would understate it. The counts
-- are included so you can see how small each group is.
CREATE OR REPLACE VIEW v_quote_conversion AS
SELECT
    data_source_label(q.is_synthetic)                        AS data_source,
    p.channel,
    p.business_type,
    COUNT(*)                                                 AS quotes,
    COUNT(*) FILTER (WHERE q.status = 'accepted')            AS accepted,
    COUNT(*) FILTER (WHERE q.status = 'rejected')            AS rejected,
    COUNT(*) FILTER (WHERE q.status = 'expired')             AS expired,
    COUNT(*) FILTER (WHERE q.status = 'sent')                AS still_open,
    ROUND(100.0 * COUNT(*) FILTER (WHERE q.status = 'accepted')
          / NULLIF(COUNT(*) FILTER (WHERE q.status <> 'sent'), 0), 1) AS acceptance_rate_pct
FROM quotes q
JOIN prospects p ON p.prospect_id = q.prospect_id
GROUP BY q.is_synthetic, p.channel, p.business_type
ORDER BY data_source, p.channel, p.business_type;
