# Olist | Exploratory Data Analysis Summary

Generated: 2026-11-13T10:06:17+01:00

## Source and scope
- SQL Server database: prepared Olist analytical database on `localhost\SQLEXPRESS` (configured or auto-detected).
- Read-only views: `analytics.fact_orders` (one row per order) and
  `analytics.fact_sales` (one row per order item).
- Analyses and charts are descriptive; associations do not prove causation.

## Volume and reconciliation
- Orders: **99,441**.
- Order items: **112,650**.
- Sales value (order-level): **15,843,553.24**.
- Sales value (item-level): **15,843,553.24**.
- Product revenue excluding freight: **13,591,643.70**.
- Delivered: **96,478**; delayed: **7,826**;
  on time/early: **88,644**; delivered with unknown timing:
  **8**.
- Delivered reconciliation: **88,644 + 7,826 + 8 = 96,478**.

## Findings from the grouped extracts
- Leading category by product revenue: **health_beauty (1,258,681.34 product revenue)**.
- Highest delay rate among states with >=500 delivered orders: **MA (19.67% delay rate)**.
- Sellers: **3,095**; qualified (>=100 delivered orders):
  **210**; high-risk (delay rate >=15%):
  **11**.
- Unweighted average seller delay rate among qualified sellers:
  **7.62%**.
- Pearson correlation of delivery days vs. order review score for
  delivered orders with both values (n=95,824):
  **-0.3341**. This is descriptive,
  subject to missing data and confounding factors, and is not a causal effect.

## Important data-quality and interpretation notes
- Delivered orders with missing delay status: **8**;
  do NOT classify these as on time or delayed.
- Orders with missing purchase date: **0**;
  they are excluded from monthly trends (but included in overall totals).
- Orders with missing order-total value: **775**;
  pandas `sum` ignores missing values, matching SQL `SUM` behavior here.
- Item rows with missing translated category: **0**;
  they are excluded from the category ranking but included in overall sales.
- The monthly CSV retains all available purchase months, including sparse months.
- The monthly PNG chart only displays January 2017–August 2018 to avoid
  presenting sparse boundary months as a sudden business collapse.
- Compare matched time periods when assessing seasonality or growth.
- The regional delay-rate ranking excludes states with fewer than 500
  delivered orders; smaller states remain in `state_performance.csv`.
- Seller delay rates count each `(seller_id, order_id)` combination once,
  even when the seller has multiple line items in an order. The qualified-seller
  average is **unweighted**, not the overall delayed-orders percentage.
- Product revenue **excludes freight**, while total sales **includes freight**.
- Review group low-review percentages use **all orders in each group**
  as the denominator; the average score uses only orders with a score.

## Output files
CSV files contain the underlying aggregates. Six PNG charts are in `charts/`.
