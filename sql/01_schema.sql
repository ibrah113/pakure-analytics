-- Stage 1 schema for Pakure Analytics.
-- Safe to re-run: drops and recreates the tables. CASCADE also drops any views built on them
-- (02_views.sql recreates those), and children are dropped first because of foreign keys.

DROP TABLE IF EXISTS quotes CASCADE;
DROP TABLE IF EXISTS prospects CASCADE;
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

-- One row per customer branch (two branches of the same brand are separate customers).
CREATE TABLE customers (
    customer_id       SERIAL PRIMARY KEY,
    customer_code     TEXT NOT NULL UNIQUE,   -- anonymised, e.g. CUST-01
    brand             TEXT NOT NULL,          -- anonymised brand code in committed data
    location          TEXT,                   -- branch, NULL if the brand has one site
    business_type     TEXT CHECK (business_type IN ('cafe', 'restaurant', 'takeaway')),
                                              -- NULL for real customers (not in the tracker); set for simulated ones
    first_order_date  DATE,
    is_synthetic      BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE = simulated, FALSE = real
    -- customer_id is already unique; this composite key exists only so other tables can
    -- reference (customer_id, is_synthetic) together. See the note above `orders`.
    UNIQUE (customer_id, is_synthetic)
);

CREATE TABLE products (
    product_id    SERIAL PRIMARY KEY,
    product_name  TEXT NOT NULL UNIQUE,
    category      TEXT,
    print_only    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE orders (
    order_id           SERIAL PRIMARY KEY,
    customer_id        INTEGER NOT NULL,
    order_date         DATE NOT NULL,
    fulfilment_status  TEXT NOT NULL CHECK (fulfilment_status IN ('Confirmed', 'Printing', 'Ready', 'Delivered')),
    payment_status     TEXT NOT NULL CHECK (payment_status IN ('Paid', 'Unpaid')),
    invoice_no         TEXT,                  -- optional: only one order has one
    total_eur          NUMERIC(10, 2) NOT NULL CHECK (total_eur >= 0),  -- NUMERIC, not FLOAT, so money adds up exactly
    is_synthetic       BOOLEAN NOT NULL DEFAULT FALSE,
    -- Real and simulated data can never be mixed: the foreign key includes is_synthetic, so the
    -- database itself rejects a simulated order for a real customer (and the reverse).
    FOREIGN KEY (customer_id, is_synthetic) REFERENCES customers (customer_id, is_synthetic)
);

CREATE TABLE order_items (
    order_item_id   SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    qty             INTEGER NOT NULL CHECK (qty > 0),   -- unit still to be confirmed (see PLAN open questions)
    line_total_eur  NUMERIC(10, 2) NOT NULL CHECK (line_total_eur >= 0)
);

-- Stage 3: sales funnel. The tracker has no record of businesses approached, so these tables
-- are filled with simulated data only (is_synthetic = TRUE); see scripts/generate_synthetic.py.
CREATE TABLE prospects (
    prospect_id         SERIAL PRIMARY KEY,
    prospect_code       TEXT NOT NULL UNIQUE,   -- e.g. SIM-PROS-001
    business_type       TEXT NOT NULL CHECK (business_type IN ('cafe', 'restaurant', 'takeaway')),
    area                TEXT NOT NULL,          -- Dublin area
    first_contact_date  DATE NOT NULL,
    channel             TEXT NOT NULL CHECK (channel IN ('walk-in', 'phone', 'email')),
    outcome             TEXT NOT NULL CHECK (outcome IN ('no_interest', 'quoted', 'won')),
    customer_id         INTEGER UNIQUE,         -- set only when the prospect became a customer
    is_synthetic        BOOLEAN NOT NULL DEFAULT FALSE,
    -- A simulated prospect can only become a simulated customer (NULL customer_id skips the check).
    FOREIGN KEY (customer_id, is_synthetic) REFERENCES customers (customer_id, is_synthetic),
    -- "won" and "has a customer" must always agree.
    CHECK ((outcome = 'won') = (customer_id IS NOT NULL)),
    UNIQUE (prospect_id, is_synthetic)
);

CREATE TABLE quotes (
    quote_id      SERIAL PRIMARY KEY,
    prospect_id   INTEGER NOT NULL,
    quote_date    DATE NOT NULL,
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    qty           INTEGER NOT NULL CHECK (qty > 0),
    amount_eur    NUMERIC(10, 2) NOT NULL CHECK (amount_eur >= 0),
    status        TEXT NOT NULL CHECK (status IN ('sent', 'accepted', 'rejected', 'expired')),
    is_synthetic  BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (prospect_id, is_synthetic) REFERENCES prospects (prospect_id, is_synthetic)
);

-- Foreign keys are not indexed automatically in PostgreSQL; the metric views will join on these.
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date     ON orders(order_date);
CREATE INDEX idx_items_order     ON order_items(order_id);
CREATE INDEX idx_items_product   ON order_items(product_id);
CREATE INDEX idx_quotes_prospect ON quotes(prospect_id);
CREATE INDEX idx_quotes_status   ON quotes(status);
