"""Clean the raw Order Tracker export into an anonymised CSV.

raw:   data/raw/orders_raw.csv   (git-ignored, contains real customer names)
clean: data/clean/orders_clean.csv (safe to commit)

Run from anywhere:  python scripts/clean_orders.py
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "orders_raw.csv"
CLEAN = ROOT / "data" / "clean" / "orders_clean.csv"

# Standard product names. Keys are the raw name lower-cased with spaces removed,
# so "Bags", "bags" and " BAGS " all land on the same key.
# value = (product_name, category, print_only)
PRODUCTS = {
    "pizzaboxes": ("Pizza Boxes", "Pizza Box", False),
    "pizzaboxes(printonly)": ("Pizza Boxes (Print Only)", "Pizza Box", True),
    "bags": ("Bags", "Bag", False),
    "bags&box": ("Bags & Box", "Bag & Box", False),
}


def split_client(client: str) -> tuple[str, str | None]:
    """'Tuckinn(Tallaght)' -> ('Tuckinn', 'Tallaght'); 'Kake' -> ('Kake', None)."""
    m = re.fullmatch(r"\s*(.*?)\s*\(\s*(.*?)\s*\)\s*", client)
    return (m.group(1), m.group(2)) if m else (client.strip(), None)


def main() -> None:
    # Row 1 is a title, so headers are on row 2 -> header=1.
    # dtype=str: read everything as text so nothing is silently converted
    # (e.g. money into floats). We convert each column deliberately below.
    df = pd.read_csv(RAW, header=1, dtype=str)

    # The ninth column has no header in the tracker but holds the optional
    # invoice number, so we name it rather than drop it. We also check the
    # column count so a changed export fails loudly instead of mislabelling data.
    if len(df.columns) != 9:
        raise ValueError(f"Expected 9 columns, found {len(df.columns)}: {list(df.columns)}")
    df.columns = ["source_no", "client", "date", "product", "qty", "status",
                  "amount", "paid", "invoice_no"]
    # Drop the empty rows at the bottom (no client = not an order).
    df = df.dropna(subset=["client"]).copy()

    # Fix: dates are DD/MM/YYYY. An explicit format stops pandas guessing
    # month-first, which would turn 10/05/2026 into 5 October.
    df["order_date"] = pd.to_datetime(df["date"], format="%d/%m/%Y")

    # Fix: Status mixes delivery and payment. "Paid" in Status implies the order
    # was delivered, so fulfilment is Delivered for both. Payment comes only
    # from the dedicated Paid column.
    df["status"] = df["status"].str.strip().str.title()
    unknown = set(df["status"]) - {"Confirmed", "Printing", "Ready", "Delivered", "Paid"}
    if unknown:
        raise ValueError(f"Unrecognised status values: {unknown}")
    df["fulfilment_status"] = df["status"].replace({"Paid": "Delivered"})
    df["payment_status"] = df["paid"].str.strip().str.title()
    if not df["payment_status"].isin(["Paid", "Unpaid"]).all():
        raise ValueError("Paid column has values other than Paid/Unpaid")
    # Consistency check: a Status of "Paid" must agree with the Paid column.
    if ((df["status"] == "Paid") & (df["payment_status"] != "Paid")).any():
        raise ValueError("Status says Paid but Paid column disagrees")

    # Fix: standardise product names. Fail loudly on a name we haven't mapped
    # rather than silently creating a new product.
    keys = df["product"].str.lower().str.replace(r"\s+", "", regex=True)
    bad = set(df["product"][~keys.isin(PRODUCTS)])
    if bad:
        raise ValueError(f"Unmapped product names: {bad}")
    df["product_name"] = keys.map(lambda k: PRODUCTS[k][0])
    df["category"] = keys.map(lambda k: PRODUCTS[k][1])
    df["print_only"] = keys.map(lambda k: PRODUCTS[k][2])

    # Fix: split brand and location. Each (brand, location) pair is a customer.
    df[["brand_raw", "location"]] = df["client"].apply(lambda c: pd.Series(split_client(c)))

    # Fix: sort by date (ties broken by the tracker's own # so the result is
    # repeatable). The # column is not used as the order sequence.
    df["source_no"] = df["source_no"].astype(int)
    df = df.sort_values(["order_date", "source_no"]).reset_index(drop=True)

    # Anonymise. Codes are handed out in order of first purchase, not
    # alphabetically, so the code doesn't reveal the name's initial letter.
    # The mapping is never written to disk. Branches of one brand share a
    # BRAND code but get their own CUST code.
    brand_code = {b: f"BRAND-{i:02d}" for i, b in enumerate(df["brand_raw"].drop_duplicates(), 1)}
    cust_keys = df[["brand_raw", "location"]].fillna("").drop_duplicates().itertuples(index=False)
    cust_code = {(b, l): f"CUST-{i:02d}" for i, (b, l) in enumerate(cust_keys, 1)}
    df["brand"] = df["brand_raw"].map(brand_code)
    df["customer_code"] = [cust_code[(b, l)] for b, l in zip(df["brand_raw"], df["location"].fillna(""))]

    # Money and quantity: validated numeric, kept to 2 decimal places as text
    # so the database (NUMERIC) receives the exact figure.
    df["total_eur"] = df["amount"].str.replace(",", "").astype(float).round(2).map("{:.2f}".format)
    df["qty"] = df["qty"].astype(int)

    # Optional invoice number (only one order has one); blank -> empty.
    df["invoice_no"] = df["invoice_no"].str.strip()
    df["is_synthetic"] = False  # real data; synthetic rows would live in their own file
    df["order_date"] = df["order_date"].dt.strftime("%Y-%m-%d")  # ISO format for PostgreSQL

    out = df[["customer_code", "brand", "location", "order_date", "product_name", "category",
              "print_only", "qty", "fulfilment_status", "payment_status", "invoice_no",
              "total_eur", "is_synthetic"]]
    CLEAN.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(CLEAN, index=False)
    print(f"Wrote {len(out)} orders, {out['customer_code'].nunique()} customers -> {CLEAN}")


if __name__ == "__main__":
    main()
