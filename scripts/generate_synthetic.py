"""Generate SIMULATED prospects, quotes, customers and orders for June-October 2026.

Everything written here is fake and flagged is_synthetic = TRUE. It exists to model a sales
funnel, because the real tracker has no record of businesses approached or quotes sent.
Output (safe to commit): data/synthetic/{customers,orders,prospects,quotes}.csv

Run (after clean_orders.py):  python scripts/generate_synthetic.py
The fixed seed means the same files are produced every time.
"""
import calendar
import csv
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "data" / "clean" / "orders_clean.csv"
OUT = ROOT / "data" / "synthetic"

SEED = 2026
START, END = date(2026, 6, 1), date(2026, 10, 15)

# --- Funnel settings (taken from the brief) -------------------------------------------------
PROSPECTS_PER_MONTH = (18, 22)                       # "about 20"
CHANNEL_SHARE = {"walk-in": 0.60, "phone": 0.25, "email": 0.15}
QUOTE_SHARE = 0.40                                   # share of prospects who get a quote
ACCEPT_SHARE = 0.36                                  # share of ALL quotes that are accepted
RECENT_CUTOFF = date(2026, 9, 30)                    # quotes after this may still be undecided
P_STILL_SENT = 0.75                                  # chance a recent quote has had no reply yet
BUSINESS_TYPES = {"cafe": 0.40, "restaurant": 0.25, "takeaway": 0.35}
AREAS = ["Dublin 1", "Dublin 2", "Dublin 7", "Dublin 8", "Rathmines", "Drumcondra", "Tallaght",
         "Sandyford", "Dundrum", "Swords", "Blanchardstown", "Clondalkin", "Lucan", "Howth"]

# --- Re-order behaviour ---------------------------------------------------------------------
CHURN_AFTER_ORDER = 0.25        # chance a customer simply stops after any given order
INTERVAL_DAYS = (14, 42)        # each customer has their own typical gap between orders
SAME_PRODUCT_AGAIN = 0.80
SLOW_PAYER_SHARE = 0.40         # share of customers who usually pay late
P_UNPAID_SLOW = 0.85


def month_windows():
    """(first day, last day) of each month in the simulation period, clipped to START/END."""
    for month in range(START.month, END.month + 1):
        first = date(2026, month, 1)
        last = date(2026, month, calendar.monthrange(2026, month)[1])
        yield max(first, START), min(last, END)


def main() -> None:
    rng = random.Random(SEED)

    # ---- Learn ranges from the REAL data (no numbers invented) ----
    real = pd.read_csv(REAL)
    info = real.drop_duplicates("product_name").set_index("product_name")[["category", "print_only"]]
    ranges = {}
    for name, g in real.groupby("product_name"):
        unit = g["total_eur"] / g["qty"]
        qlo, qhi, ulo, uhi = int(g["qty"].min()), int(g["qty"].max()), unit.min(), unit.max()
        if len(g) < 3:   # too few real orders to trust the range: widen it a little
            qlo, qhi, ulo, uhi = max(1, qlo - 1), qhi + 1, ulo * 0.85, uhi * 1.15
        ranges[name] = (qlo, qhi, ulo, uhi)
    mix = real["product_name"].value_counts().sort_index()          # sorted = reproducible
    product_names, product_weights = list(mix.index), list(mix.values)
    unpaid_rate = (real["payment_status"] == "Unpaid").mean()
    # Fast payers' unpaid chance is set so the overall rate matches the real data.
    p_unpaid_fast = max(0.0, (unpaid_rate - SLOW_PAYER_SHARE * P_UNPAID_SLOW) / (1 - SLOW_PAYER_SHARE))

    def sample_line(product: str, base_unit: float | None = None) -> tuple[int, float]:
        qlo, qhi, ulo, uhi = ranges[product]
        qty = rng.randint(qlo, qhi)
        unit = base_unit * rng.uniform(0.95, 1.05) if base_unit else rng.uniform(ulo, uhi)
        return qty, round(qty * unit, 2)

    # ---- Prospects ----
    windows = list(month_windows())
    counts = []
    for first, last in windows:
        full_month = (last - first).days + 1 >= 28
        counts.append(rng.randint(*PROSPECTS_PER_MONTH) if full_month else rng.randint(9, 11))
    total = sum(counts)
    channels = []
    for ch, share in CHANNEL_SHARE.items():
        channels += [ch] * round(total * share)
    channels = (channels + ["email"] * total)[:total]      # pad/trim to exactly `total`
    rng.shuffle(channels)

    prospects = []
    for (first, last), n in zip(windows, counts):
        for _ in range(n):
            prospects.append({
                "first_contact_date": first + timedelta(days=rng.randint(0, (last - first).days)),
                "business_type": rng.choices(list(BUSINESS_TYPES), list(BUSINESS_TYPES.values()))[0],
                "area": rng.choice(AREAS),
                "outcome": "no_interest",
                "customer_code": "",
            })
    prospects.sort(key=lambda p: p["first_contact_date"])
    for i, p in enumerate(prospects, 1):
        p["prospect_code"] = f"SIM-PROS-{i:03d}"
        p["channel"] = channels[i - 1]

    # ---- Quotes ----
    # No channel or business-type advantage is built in: who gets a quote, and who accepts,
    # is random. Any difference between channels in the views is therefore just noise.
    quoted = rng.sample(prospects, round(len(prospects) * QUOTE_SHARE))
    quotes = []
    for p in sorted(quoted, key=lambda p: p["prospect_code"]):
        product = rng.choices(product_names, product_weights)[0]
        qty, amount = sample_line(product)
        quote_date = min(p["first_contact_date"] + timedelta(days=rng.randint(0, 7)), END)
        quotes.append({"prospect": p, "quote_date": quote_date, "product_name": product,
                       "qty": qty, "amount_eur": amount, "status": None})
        p["outcome"] = "quoted"

    # Exactly ACCEPT_SHARE of all quotes are accepted, picked from quotes old enough to be decided.
    old = [q for q in quotes if q["quote_date"] <= RECENT_CUTOFF]
    for q in rng.sample(old, min(len(old), round(len(quotes) * ACCEPT_SHARE))):
        q["status"] = "accepted"
        q["prospect"]["outcome"] = "won"
    for q in quotes:
        if q["status"] is None:
            if q["quote_date"] > RECENT_CUTOFF and rng.random() < P_STILL_SENT:
                q["status"] = "sent"                      # no reply yet: an outstanding quote
            else:
                q["status"] = rng.choices(["rejected", "expired"], [55, 45])[0]

    # ---- New customers (one per accepted quote) and their orders ----
    accepted = sorted((q for q in quotes if q["status"] == "accepted"),
                      key=lambda q: (q["quote_date"], q["prospect"]["prospect_code"]))
    customers, orders = [], []
    for i, q in enumerate(accepted, 1):
        p = q["prospect"]
        code = f"SIM-CUST-{i:02d}"
        p["customer_code"] = code
        first_order = min(q["quote_date"] + timedelta(days=rng.randint(0, 5)), END)
        slow_payer = rng.random() < SLOW_PAYER_SHARE
        p_unpaid = P_UNPAID_SLOW if slow_payer else p_unpaid_fast
        gap = rng.randint(*INTERVAL_DAYS)

        # The first order is exactly what was quoted.
        order_date, product = first_order, q["product_name"]
        qty, amount = q["qty"], q["amount_eur"]
        base_unit = amount / qty
        history = []
        while True:
            history.append((order_date, product, qty, amount, rng.random() < p_unpaid))
            if rng.random() < CHURN_AFTER_ORDER:
                break                                     # this customer stops ordering
            order_date += timedelta(days=max(7, round(gap * rng.uniform(0.7, 1.3))))
            if order_date > END:
                break
            if rng.random() < SAME_PRODUCT_AGAIN:
                qty, amount = sample_line(product, base_unit)
            else:
                product = rng.choices(product_names, product_weights)[0]
                qty, amount = sample_line(product)
                base_unit = amount / qty
        customers.append({"customer_code": code, "brand": f"SIM-BRAND-{i:02d}", "location": p["area"],
                          "business_type": p["business_type"], "first_order_date": first_order,
                          "is_synthetic": True})
        for d, prod, qt, amt, unpaid in history:
            orders.append({"customer_code": code, "order_date": d, "product_name": prod,
                           "category": info.loc[prod, "category"], "print_only": bool(info.loc[prod, "print_only"]),
                           "qty": qt, "fulfilment_status": "Delivered",
                           "payment_status": "Unpaid" if unpaid else "Paid", "invoice_no": "",
                           "total_eur": f"{amt:.2f}", "is_synthetic": True})
    orders.sort(key=lambda o: (o["order_date"], o["customer_code"]))

    # ---- Write CSVs ----
    OUT.mkdir(parents=True, exist_ok=True)

    def write(name: str, rows: list[dict], fields: list[str]) -> None:
        with open(OUT / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {len(rows):>3} rows -> data/synthetic/{name}")

    for p in prospects:
        p["is_synthetic"] = True
    quote_rows = [{"prospect_code": q["prospect"]["prospect_code"], **q, "is_synthetic": True} for q in quotes]
    write("customers.csv", customers, ["customer_code", "brand", "location", "business_type",
                                       "first_order_date", "is_synthetic"])
    write("orders.csv", orders, ["customer_code", "order_date", "product_name", "category", "print_only",
                                 "qty", "fulfilment_status", "payment_status", "invoice_no",
                                 "total_eur", "is_synthetic"])
    write("prospects.csv", prospects, ["prospect_code", "business_type", "area", "first_contact_date",
                                       "channel", "outcome", "customer_code", "is_synthetic"])
    write("quotes.csv", quote_rows, ["prospect_code", "quote_date", "product_name", "qty",
                                     "amount_eur", "status", "is_synthetic"])


if __name__ == "__main__":
    main()
