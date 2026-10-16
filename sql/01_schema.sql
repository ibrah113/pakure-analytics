-- Stage 1 schema for Pakure Analytics.
-- Safe to re-run: drops and recreates the tables (children first, because of foreign keys).

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

-- One row per customer branch ("Tuckinn (Tallaght)" and "Tuckinn (Sandyford)" are separate customers).
CREATE TABLE customers (
    customer_id       SERIAL PRIMARY KEY,
    customer_code     TEXT NOT NULL UNIQUE,   -- anonymised, e.g. CUST-01
    brand             TEXT NOT NULL,          -- anonymised brand code in committed data
    location          TEXT,                   -- branch, NULL if the brand has one site
    business_type     TEXT,                   -- cafe / restaurant / takeaway; not in the tracker, filled in later
    first_order_date  DATE
);

CREATE TABLE products (
    product_id    SERIAL PRIMARY KEY,
    product_name  TEXT NOT NULL UNIQUE,
    category      TEXT,
    print_only    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE orders (
    order_id           SERIAL PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date         DATE NOT NULL,
    fulfilment_status  TEXT NOT NULL CHECK (fulfilment_status IN ('Confirmed', 'Printing', 'Ready', 'Delivered')),
    payment_status     TEXT NOT NULL CHECK (payment_status IN ('Paid', 'Unpaid')),
    invoice_no         TEXT,                  -- optional: only one order has one
    total_eur          NUMERIC(10, 2) NOT NULL CHECK (total_eur >= 0),  -- NUMERIC, not FLOAT, so money adds up exactly
    is_synthetic       BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE order_items (
    order_item_id   SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    qty             INTEGER NOT NULL CHECK (qty > 0),   -- unit still to be confirmed (see PLAN open questions)
    line_total_eur  NUMERIC(10, 2) NOT NULL CHECK (line_total_eur >= 0)
);

-- Foreign keys are not indexed automatically in PostgreSQL; the metric views will join on these.
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date     ON orders(order_date);
CREATE INDEX idx_items_order     ON order_items(order_id);
CREATE INDEX idx_items_product   ON order_items(product_id);
