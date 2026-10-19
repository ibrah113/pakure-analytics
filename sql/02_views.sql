-- Metric views for the dashboard (Stage 2). Run after 01_schema.sql and the data load.
-- CREATE OR REPLACE makes the file safe to re-run.
-- Revenue = orders.total_eur. Synthetic rows (is_synthetic) are included; every
-- view carries no filter so the dashboard can label them if they are ever added.


-- 1. Monthly revenue, order count and average order value ---------------------
-- generate_series builds every month between the first and last order, so a
-- month with no orders (March 2026) shows as 0 instead of vanishing from the chart.
CREATE OR REPLACE VIEW v_monthly_revenue AS
WITH months AS (
    SELECT generate_series(
               date_trunc('month', MIN(order_date)),
               date_trunc('month', MAX(order_date)),
               interval '1 month')::date AS month_start
    FROM orders
)
SELECT
    m.month_start,
    to_char(m.month_start, 'YYYY-MM')              AS month,
    COUNT(o.order_id)                              AS order_count,
    COALESCE(SUM(o.total_eur), 0)                  AS revenue_eur,
    -- NULLIF avoids a divide-by-zero in empty months; the average is then NULL, not 0.
    ROUND(SUM(o.total_eur) / NULLIF(COUNT(o.order_id), 0), 2) AS avg_order_value_eur
FROM months m
LEFT JOIN orders o ON date_trunc('month', o.order_date) = m.month_start
GROUP BY m.month_start
ORDER BY m.month_start;


-- 2. Revenue and order count by customer, with first and last order date -----
CREATE OR REPLACE VIEW v_customer_revenue AS
SELECT
    c.customer_code,
    c.brand,
    c.location,
    COUNT(o.order_id)    AS order_count,
    SUM(o.total_eur)     AS revenue_eur,
    MIN(o.order_date)    AS first_order_date,
    MAX(o.order_date)    AS last_order_date
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.customer_code, c.brand, c.location
ORDER BY revenue_eur DESC;


-- 3. Repeat-customer rate (customers with 2+ orders) --------------------------
-- One row. Repeat rate is a share of customers, not of orders.
CREATE OR REPLACE VIEW v_repeat_customer_rate AS
WITH per_customer AS (
    SELECT customer_id, COUNT(*) AS orders
    FROM orders
    GROUP BY customer_id
)
SELECT
    COUNT(*)                                          AS total_customers,
    COUNT(*) FILTER (WHERE orders >= 2)               AS repeat_customers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE orders >= 2) / COUNT(*), 1) AS repeat_rate_pct
FROM per_customer;


-- 4. Outstanding balance by customer, with ageing -----------------------------
-- Only unpaid orders count. Days are measured from the order date to today
-- (CURRENT_DATE), so the ageing grows each day the view is queried.
CREATE OR REPLACE VIEW v_outstanding_balance AS
SELECT
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
GROUP BY c.customer_id, c.customer_code, c.brand, c.location
ORDER BY outstanding_eur DESC;


-- 5. Revenue and quantity by product ------------------------------------------
-- Revenue comes from order_items (line totals), so it stays correct if an order
-- ever has several products.
CREATE OR REPLACE VIEW v_product_sales AS
SELECT
    p.product_name,
    p.category,
    p.print_only,
    COUNT(DISTINCT i.order_id)   AS order_count,
    SUM(i.qty)                   AS total_qty,
    SUM(i.line_total_eur)        AS revenue_eur,
    ROUND(SUM(i.line_total_eur) / SUM(i.qty), 2) AS revenue_per_unit_eur
FROM products p
JOIN order_items i ON i.product_id = p.product_id
GROUP BY p.product_id, p.product_name, p.category, p.print_only
ORDER BY revenue_eur DESC;
