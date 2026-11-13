# Olist | Business Insights & Prioritized Investigation Plan

Generated: 2026-11-13T10:07:12+01:00

## Evidence base and validation
- Based on read-only aggregates created by `03_exploratory_analysis.py`.
- **99,441** distinct orders, **112,650** order items; sales **15,843,553.24** (dataset currency units), with cross-extract reconciliation confirmed.
- National observed delayed-delivery rate: **8.11%** (7,826 delayed / 96,478 delivered).
- Regional comparisons require **500+** delivered orders. Seller eligibility requires **100+** delivered seller-order pairs; high risk = delay rate **>= 15%**.

## Ranked business findings

### 1. Regional delivery performance
- Highest qualifying *delay rate*: **MA at 19.67%** (141 delayed / 717 delivered).
- Greatest arithmetic gap versus the observed national benchmark: **RJ**, with **662.2** hypothetical delayed-order equivalents above that benchmark.
- **Action to investigate:** compare fulfillment and carrier handoffs in higher-rate states; stratify by seller, product category, distance, and month before assigning causes.
- **Caution:** the arithmetic gap is a prioritization aid, NOT an estimate of avoidable delays or the effect of an intervention; the national benchmark includes the state itself.

### 2. Seller risk prioritization
- **11 of 210** qualified sellers (**5.24%**) exceed or meet the 15% high-risk threshold.
- Unweighted mean qualified-seller delay rate: **7.62%**. This is not the national delayed-order percentage.
- **Action to investigate:** review shipping preparation and carrier exceptions for watchlist sellers, starting with higher delayed seller-order volumes. Validate operational context before escalation.
- **Critical grain note:** seller-order pairs can overlap across sellers on the same customer order. DO NOT sum seller counts and describe them as unique customer orders.

### 3. Reviews and delivery experience
- On-time/early average review **4.29/5**; delayed average review **2.57/5** (difference **1.73 points**).
- Low-review rates: delayed **52.85%** versus on-time/early **9.14%** (difference **43.71 percentage points**).
- **Action to investigate:** compare review outcomes among operationally similar orders and test delivery-time improvements with an appropriate control group.
- **Caution:** correlations and comparisons are descriptive, not evidence that late delivery alone caused poor reviews. The third delivery-status group also mixes non-delivery and unknown timing.

### 4. Product-category concentration
- Largest category by product revenue: **health_beauty** (**1,258,681.34**).
- Top five categories account for **39.74%** of product revenue. Product revenue excludes freight; total sales includes freight.
- **Action to investigate:** check whether service issues concentrate within high-revenue categories while controlling for regional/seller mix.

## Practical next steps (investigations, not guaranteed outcomes)
1. Review the top regional-priority cases with order-level operations data, checking volume and rate together.
2. Audit the **11** flagged sellers, distinguishing seller-order pairs from unique customer orders.
3. Compare customer-review outcomes across delivery status under comparable conditions; test any operational changes before claiming impact.

## Important limitations
- Data is historical Olist commerce data; no live business intervention or outcome was observed.
- Some end-of-series months are partial, so they must not be treated as representative month-over-month growth or decline.
- Eight delivered orders have unknown delay timing in the validated portfolio. Preserve the unknown category.
- SQL/Python quality checks cover defined rules but cannot prove all real-world source values are error-free.
- No forecast, causal effect, or realized monetary savings is claimed.
- Charts and CSVs are intended as audit-friendly supporting evidence.
