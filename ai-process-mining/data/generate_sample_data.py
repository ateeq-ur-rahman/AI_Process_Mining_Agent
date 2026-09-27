"""Generate SYNTHETIC Order-to-Cash demonstration data.

This data is fabricated for demonstrating the MVP. It is not real business data.
Deliberately embedded patterns (so the engine has something to find):
  * Payment wait is the main bottleneck (long, heavy-tailed customer payment times),
    with payment-reminder loops for slow payers.
  * Credit checks on high-value orders take much longer; they are routed to a senior
    analyst — so that analyst's averages look "slow" purely because of case mix.
  * Small orders frequently skip Credit Check; urgent orders often skip Quality Check.
  * Order changes after approval cause rework (Credit Check / Order Approved repeated).
  * Delivery failures introduce Delivery Failed / Redelivery Scheduled.
  * A warehouse backlog in March 2026 inflates fulfilment waiting time.
  * Invoice corrections (rework) and some invoices generated before shipping (out of order).
  * Rejections, cancellations and still-open cases (incomplete).
  * A small number of data-quality problems (duplicates, missing ids, bad timestamps,
    malformed rows, inconsistent activity spelling) to exercise validation.

Usage: python generate_sample_data.py [--cases 10000] [--seed 42] [--out sample_order_to_cash.csv]
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta

SALES = ["Alice M.", "Ravi K.", "Sofia L.", "Chen W.", "Meera S.", "Tom B.", "Fatima Z.", "Diego R."]
FINANCE = ["Bob T.", "Anjali P.", "Lukas H.", "Grace O."]
SENIOR_FINANCE = "Priya N."          # handles high-value credit checks
WAREHOUSE = ["John D.", "Kiran V.", "Maria G.", "Samuel A.", "Yuki T.", "Omar F."]
QC = ["Nina Q.", "Arjun C.", "Lena W."]
COURIERS = ["Courier North", "Courier South", "Courier Express"]
AR = ["Hannah J.", "Vikram R."]
REGIONS = ["North", "South", "East", "West"]


def lognorm_hours(rng: random.Random, median: float, sigma: float) -> float:
    import math
    return median * math.exp(rng.gauss(0, sigma))


def business_start(rng: random.Random, day: datetime) -> datetime:
    return day.replace(hour=rng.randint(8, 17), minute=rng.randint(0, 59), second=rng.randint(0, 59))


def simulate_case(rng: random.Random, idx: int, start_day: datetime) -> list[dict]:
    case_id = f"ORD{idx:06d}"
    amount = round(lognorm_hours(rng, 1500, 1.0), 2)
    priority = rng.choices(["High", "Normal", "Low"], [0.15, 0.7, 0.15])[0]
    region = rng.choice(REGIONS)
    customer = f"CUST{rng.randint(1, 2500):05d}"
    events: list[dict] = []
    t = business_start(rng, start_day)

    def emit(activity: str, resource: str, dept: str, hours_after: float | None = None):
        nonlocal t
        if hours_after is not None:
            t = t + timedelta(hours=max(hours_after, 0.02))
        events.append({"case_id": case_id, "activity": activity, "timestamp": t, "resource": resource,
                       "department": dept, "amount": amount, "customer_id": customer,
                       "location": region, "priority": priority})

    emit("Order Created", rng.choice(SALES), "Sales")

    def credit_check():
        if amount > 5000:
            emit("Credit Check", SENIOR_FINANCE, "Finance", lognorm_hours(rng, 16, 0.6))
        else:
            emit("Credit Check", rng.choice(FINANCE), "Finance", lognorm_hours(rng, 1.5, 0.6))

    skip_credit = amount < 500 and rng.random() < 0.7
    if not skip_credit:
        credit_check()
    emit("Order Approved", rng.choice(FINANCE), "Finance", lognorm_hours(rng, 1.5, 0.7))

    if rng.random() < 0.03:
        emit("Order Rejected", rng.choice(FINANCE), "Finance", lognorm_hours(rng, 0.5, 0.5))
        return events
    if rng.random() < 0.07:  # customer changes the order after approval -> rework
        emit("Order Changed", rng.choice(SALES), "Sales", lognorm_hours(rng, 8, 0.8))
        if not skip_credit:
            credit_check()
        emit("Order Approved", rng.choice(FINANCE), "Finance", lognorm_hours(rng, 2, 0.7))
    if rng.random() < 0.02:
        emit("Order Cancelled", rng.choice(SALES), "Sales", lognorm_hours(rng, 6, 0.8))
        return events

    emit("Payment Pending", "System", "Finance", lognorm_hours(rng, 0.1, 0.4))
    open_case = rng.random() < 0.015
    if open_case and rng.random() < 0.5:
        return events

    # Payment wait: the main bottleneck.
    pay_wait = lognorm_hours(rng, 30, 0.8)
    if pay_wait > 48:
        waited = 0.0
        reminders = 0
        while pay_wait - waited > 48 and reminders < 4:
            emit("Payment Reminder Sent", "System", "Finance", 48 if reminders == 0 else 24)
            waited += 48 if reminders == 0 else 24
            reminders += 1
        if reminders >= 3 and rng.random() < 0.35:
            emit("Order Cancelled", rng.choice(SALES), "Sales", lognorm_hours(rng, 12, 0.5))
            return events
        emit("Payment Received", "System", "Finance", max(pay_wait - waited, 1))
    else:
        emit("Payment Received", "System", "Finance", pay_wait)

    invoice_early = rng.random() < 0.05
    if invoice_early:
        emit("Invoice Generated", "System", "Finance", lognorm_hours(rng, 0.5, 0.5))

    backlog = t.month == 3
    emit("Order Fulfilled", rng.choice(WAREHOUSE), "Warehouse",
         lognorm_hours(rng, 30 if backlog else 5, 0.6))
    if open_case:
        return events
    skip_qc = (priority == "High" and rng.random() < 0.6) or rng.random() < 0.03
    if not skip_qc:
        emit("Quality Check", rng.choice(QC), "Warehouse", lognorm_hours(rng, 2, 0.6))
    emit("Shipped", rng.choice(WAREHOUSE), "Warehouse", lognorm_hours(rng, 3, 0.6))
    courier = rng.choice(COURIERS)
    if rng.random() < 0.04:
        emit("Delivery Failed", courier, "Logistics", lognorm_hours(rng, 40, 0.4))
        emit("Redelivery Scheduled", rng.choice(SALES), "Sales", lognorm_hours(rng, 6, 0.6))
        emit("Delivered", courier, "Logistics", lognorm_hours(rng, 24, 0.4))
    else:
        emit("Delivered", courier, "Logistics", lognorm_hours(rng, 28 if courier != "Courier Express" else 14, 0.35))

    if not invoice_early:
        emit("Invoice Generated", "System", "Finance", lognorm_hours(rng, 4, 0.7))
    if rng.random() < 0.05:
        emit("Invoice Corrected", rng.choice(AR), "Finance", lognorm_hours(rng, 20, 0.6))
        emit("Invoice Generated", "System", "Finance", lognorm_hours(rng, 1, 0.5))
    if rng.random() < 0.01:
        return events  # invoice issued, not yet paid (open)
    emit("Invoice Paid", rng.choice(AR), "Finance", lognorm_hours(rng, 18, 0.7))
    return events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="sample_order_to_cash.csv")
    ap.add_argument("--clean", action="store_true", help="Do not inject data-quality issues.")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    base = datetime(2026, 1, 5)
    rows: list[dict] = []
    for i in range(1, args.cases + 1):
        day = base + timedelta(days=rng.randint(0, 170))
        rows.extend(simulate_case(rng, i, day))
    rng.shuffle(rows)  # event logs rarely arrive sorted

    header = ["case_id", "activity", "timestamp", "resource", "department", "amount",
              "customer_id", "location", "priority"]
    out_rows = [[r["case_id"], r["activity"], r["timestamp"].strftime("%Y-%m-%d %H:%M:%S"), r["resource"],
                 r["department"], f"{r['amount']:.2f}", r["customer_id"], r["location"], r["priority"]]
                for r in rows]

    if not args.clean:
        # Inconsistent spellings (normalization should merge them).
        for row in rng.sample(out_rows, 300):
            if row[1] == "Order Approved":
                row[1] = "order approved"
            elif row[1] == "Payment Received":
                row[1] = "Payment  Received "
        # Exact duplicates.
        out_rows.extend([list(r) for r in rng.sample(out_rows, 40)])
        # Missing case ids / activities.
        for row in rng.sample(out_rows, 15):
            row[0] = ""
        for row in rng.sample(out_rows, 8):
            row[1] = ""
        # Invalid and impossible timestamps.
        for row in rng.sample(out_rows, 30):
            row[2] = rng.choice(["2026-13-45 25:00:00", "not recorded", "31/02/2026 xx"])
        for row in rng.sample(out_rows, 6):
            row[2] = rng.choice(["2091-05-01 10:00:00", "1901-01-01 00:00:00"])
        rng.shuffle(out_rows)

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(out_rows)
        if not args.clean:
            fh.write("ORD999999,Shipped,2026-02-01 10:00:00,John D.\n")          # malformed (too few fields)
            fh.write('ORD999998,"Delivered",2026-02-01,x,y,z,1,2,3,4,5\n')      # malformed (too many fields)
    print(f"Wrote {len(out_rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
