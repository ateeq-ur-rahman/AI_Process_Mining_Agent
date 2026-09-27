# Sample data

`sample_order_to_cash.csv` is **synthetic**. `generate_sample_data.py` (seed 42) made it
to give the engine something realistic to chew on. It is not real business data, the
names are invented, and the numbers it produces say nothing about any real process.

- 10,000 Order-to-Cash cases, about 110,000 events, 18 activities, 9 columns
- Timestamps have no offset, so they're read as UTC
- Rows are shuffled, since real exports rarely arrive sorted

Regenerate with `python generate_sample_data.py --cases 10000 --seed 42`
(`--clean` leaves out the broken rows).

## What's planted, and what the engine reports

These are checks that the engine finds patterns put there on purpose. They are not
findings about a business.

| Planted in the generator | What the engine reports on the sample |
|---|---|
| 40 duplicates, 15 missing case ids, 8 missing activities, 30 unreadable and 6 impossible timestamps, 2 malformed rows | 101 rows excluded, each counted under the right issue |
| Spelling variants (`order approved`, `Payment  Received `) | Merged into `Order Approved` and `Payment Received`; the originals are kept |
| Long, heavy-tailed customer payment times, with reminders for slow payers | `Payment Received` and `Payment Reminder Sent` rank 2nd and 3rd as bottleneck candidates; reminder self-loops in 677 cases |
| Carrier transit time | `Delivered` ranks 1st. That wait may be inherent to shipping, which is why the report doesn't call it a problem |
| High-value orders get slow credit checks | 98.7% of slow Credit Check transitions are on orders above 5,000 |
| Warehouse backlog in March 2026 | 91.7% of slow Order Fulfilled transitions fall in March |
| Small orders often skip Credit Check; urgent orders often skip Quality Check | Skipped Credit Check in 980 cases (99.7% under 500); skipped Quality Check in 1,108 |
| Order changes and invoice corrections | Rework in 10.8% of cases, around Order Approved, Credit Check and Invoice Generated |
| Failed deliveries | `Delivery Failed` and `Redelivery Scheduled` show up as unexpected activities |
| About 5% of invoices raised before fulfilment | Reported as out of order |
| Rejections, cancellations, open cases | Alternative outcomes and incomplete cases |
| One analyst gets all the high-value credit checks | Their median wait is about 10× their colleagues'. It's shown with the case-mix note, because it reflects which cases they're given |
