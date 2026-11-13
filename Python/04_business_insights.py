"""Olist BI Portfolio | 04_business_insights.py

Actionable, reproducible BI conclusions from the audited EDA exports.

Input: Python/EDA_Outputs/*.csv created by 03_exploratory_analysis.py.
Output: Python/Business_Insights_Outputs/ (CSV, 4 charts, Markdown report).

Runs offline after 03; does not modify SQL Server or the EDA inputs.
Install: py -m pip install pandas matplotlib
Run:     py 04_business_insights.py

Methodology:
- Regional metrics count distinct orders within each customer state.
- Seller metrics count distinct seller/order pairs; they are not additive
  across sellers as globally unique customer orders.
- Regional 'excess vs benchmark' is hypothetical, NOT preventable orders.
- Descriptive associations alone cannot identify causes or forecast uplift.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:
    print(f"Missing dependency: {exc}")
    print("Install with: py -m pip install pandas matplotlib")
    sys.exit(1)

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "EDA_Outputs"
OUTPUT = BASE / "Business_Insights_Outputs"
PLOTS = OUTPUT / "charts"

INPUT_FILES = {
    "monthly": "monthly_trends.csv",
    "categories": "category_performance.csv",
    "states": "state_performance.csv",
    "qualified_states": "qualified_state_delays.csv",
    "reviews": "delivery_review_analysis.csv",
    "sellers": "qualified_seller_risk.csv",
    "duration": "delivery_days_reviews.csv",
}

# Business definitions agreed with the SQL/Power BI portfolio.
MIN_STATE_DELIVERED_ORDERS = 500
MIN_SELLER_DELIVERED_ORDERS = 100
HIGH_RISK_SELLER_RATE_PCT = 15.0


def fail(message: str) -> None:
    raise ValueError(message)


def approx(a: float, b: float, tolerance: float = 0.02) -> bool:
    return math.isclose(float(a), float(b), abs_tol=tolerance, rel_tol=0)


def load() -> dict[str, pd.DataFrame]:
    if not SOURCE.is_dir():
        fail(f"Input folder not found: {SOURCE}. Run 03_exploratory_analysis.py first.")
    missing = [file for file in INPUT_FILES.values() if not (SOURCE / file).is_file()]
    if missing:
        fail("Missing EDA inputs: " + ", ".join(missing))
    data = {key: pd.read_csv(SOURCE / file, encoding="utf-8-sig") for key, file in INPUT_FILES.items()}
    columns = {
        "monthly": {"purchase_month", "orders", "delivered_orders", "delayed_orders", "sales_value"},
        "categories": {"product_category_name_en", "items_sold", "product_revenue", "freight_value", "total_sales"},
        "states": {"customer_state", "orders", "delivered_orders", "delayed_orders", "sales_value", "delay_rate_pct", "qualifies_for_delay_ranking"},
        "qualified_states": {"customer_state", "delivered_orders", "delayed_orders", "delay_rate_pct"},
        "reviews": {"delivery_status_group", "orders", "orders_with_review", "avg_review_score", "low_review_orders", "low_review_rate_pct"},
        "sellers": {"seller_id", "orders", "delivered_orders", "delayed_orders", "delay_rate_pct", "qualified", "high_risk"},
        "duration": {"delivery_days_group", "delivered_orders", "orders_with_review", "avg_review_score"},
    }
    for key, required in columns.items():
        absent = required - set(data[key].columns)
        if absent:
            fail(f"{INPUT_FILES[key]} missing columns: {sorted(absent)}")
        if data[key].empty:
            fail(f"Input {INPUT_FILES[key]} is empty.")
    return data


def validate(data: dict[str, pd.DataFrame]) -> dict:
    m, c, s, q, r, v = (data[x] for x in ("monthly", "categories", "states", "qualified_states", "reviews", "sellers"))
    order_count = int(m["orders"].sum())
    order_count_states = int(s["orders"].sum())
    order_count_reviews = int(r["orders"].sum())
    if len({order_count, order_count_states, order_count_reviews}) != 1:
        fail("Order counts differ across monthly, state, and review extracts.")
    delivered = int(m["delivered_orders"].sum())
    delayed = int(m["delayed_orders"].sum())
    if delivered != int(s["delivered_orders"].sum()) or delayed != int(s["delayed_orders"].sum()):
        fail("Monthly and regional delivery counts differ.")
    sales_total = float(m["sales_value"].sum())
    if not approx(sales_total, s["sales_value"].sum()) or not approx(sales_total, c["total_sales"].sum()):
        fail("Sales totals fail cross-extract reconciliation.")
    if not approx(c["product_revenue"].sum() + c["freight_value"].sum(), sales_total):
        fail("Product revenue + freight does not equal total sales.")
    if int(c["items_sold"].sum()) != 112_650:
        fail("Order item count no longer matches the audited EDA baseline (112,650). Review data changes.")
    if s["customer_state"].duplicated().any() or q["customer_state"].duplicated().any():
        fail("Duplicate customer states in EDA outputs.")
    if v["seller_id"].duplicated().any():
        fail("Duplicate seller IDs in the qualified seller list.")
    eligible_states = s.loc[s["delivered_orders"] >= MIN_STATE_DELIVERED_ORDERS]
    if set(eligible_states["customer_state"]) != set(q["customer_state"]):
        fail("Qualified states do not match the >=500 delivered-order rule.")
    if not (v["delivered_orders"] >= MIN_SELLER_DELIVERED_ORDERS).all():
        fail("Seller file includes an ineligible seller.")
    observed_seller_rates = 100 * v["delayed_orders"] / v["delivered_orders"]
    if (observed_seller_rates - v["delay_rate_pct"]).abs().max() > 1e-6:
        fail("Seller delay rates do not reconcile to counts.")
    high_risk_computed = observed_seller_rates >= HIGH_RISK_SELLER_RATE_PCT
    high_risk_export = v["high_risk"].astype(str).str.lower() == "true"
    if not high_risk_computed.equals(high_risk_export):
        fail("Seller risk flags differ from the 15% rule.")
    if (r["low_review_orders"] > r["orders"]).any():
        fail("Low-review counts exceed group order counts.")
    if (r["orders_with_review"] > r["orders"]).any():
        fail("Review counts exceed group order counts.")
    if not (r["low_review_rate_pct"] - 100 * r["low_review_orders"] / r["orders"]).abs().max() < 1e-6:
        fail("Low-review rate denominator mismatch.")
    if delivered == 0 or order_count == 0:
        fail("Invalid zero delivered or total order counts.")
    return {
        "orders": order_count,
        "items": int(c["items_sold"].sum()),
        "delivered": delivered,
        "delayed": delayed,
        "sales_total": sales_total,
        "product_revenue": float(c["product_revenue"].sum()),
        "freight": float(c["freight_value"].sum()),
        "baseline_delay_rate_pct": 100 * delayed / delivered,
        "qualified_seller_count": len(v),
        "high_risk_seller_count": int(high_risk_computed.sum()),
        "avg_qualified_seller_delay_pct": float(observed_seller_rates.mean()),
    }


def prepare_outputs(data: dict[str, pd.DataFrame], stats: dict) -> dict[str, pd.DataFrame]:
    baseline = stats["baseline_delay_rate_pct"]
    states = data["qualified_states"].copy()
    states["delay_rate_pct"] = 100 * states["delayed_orders"] / states["delivered_orders"]
    # Gap is hypothetical arithmetic based on an observed comparator. It is NOT
    # a prediction of avoidable delays or a causal impact estimate.
    states["gap_vs_national_avg_pp"] = states["delay_rate_pct"] - baseline
    states["hypothetical_excess_delay_equivalents"] = (
        states["delayed_orders"] - states["delivered_orders"] * baseline / 100
    ).clip(lower=0)
    states["share_of_national_delays_pct"] = 100 * states["delayed_orders"] / stats["delayed"]
    states = states.sort_values(
        ["hypothetical_excess_delay_equivalents", "delay_rate_pct"],
        ascending=[False, False]
    ).reset_index(drop=True)
    states.insert(0, "investigation_priority_rank", range(1, len(states) + 1))
    states["hypothetical_excess_delay_equivalents"] = states["hypothetical_excess_delay_equivalents"].round(1)
    states["gap_vs_national_avg_pp"] = states["gap_vs_national_avg_pp"].round(2)
    states["share_of_national_delays_pct"] = states["share_of_national_delays_pct"].round(2)
    states["delay_rate_pct"] = states["delay_rate_pct"].round(2)

    sellers = data["sellers"].copy()
    sellers = sellers.loc[sellers["high_risk"].astype(str).str.lower() == "true"].copy()
    sellers["delay_rate_pct"] = 100 * sellers["delayed_orders"] / sellers["delivered_orders"]
    sellers = sellers.sort_values(["delayed_orders", "delay_rate_pct"], ascending=False).reset_index(drop=True)
    sellers.insert(0, "investigation_priority_rank", range(1, len(sellers) + 1))
    sellers["delay_rate_pct"] = sellers["delay_rate_pct"].round(2)
    sellers = sellers.rename(columns={
        "orders": "distinct_seller_order_pairs",
        "delivered_orders": "delivered_seller_order_pairs",
        "delayed_orders": "delayed_seller_order_pairs",
    })

    cats = data["categories"].copy().sort_values("product_revenue", ascending=False).reset_index(drop=True)
    cats["share_of_product_revenue_pct"] = cats["product_revenue"] / stats["product_revenue"] * 100
    cats["cumulative_product_revenue_pct"] = cats["share_of_product_revenue_pct"].cumsum()
    cats.insert(0, "revenue_rank", range(1, len(cats) + 1))
    cats["share_of_product_revenue_pct"] = cats["share_of_product_revenue_pct"].round(2)
    cats["cumulative_product_revenue_pct"] = cats["cumulative_product_revenue_pct"].round(2)

    reviews = data["reviews"].copy()
    daygroups = data["duration"].copy()
    return {
        "regional_investigation_priorities": states,
        "high_risk_seller_watchlist": sellers,
        "product_category_concentration": cats,
        "review_status_comparison": reviews,
        "delivery_duration_review_comparison": daygroups,
    }


def make_charts(data: dict[str, pd.DataFrame], outputs: dict[str, pd.DataFrame], stats: dict) -> None:
    PLOTS.mkdir(parents=True, exist_ok=True)
    regions = outputs["regional_investigation_priorities"].copy()
    by_rate = regions.sort_values("delay_rate_pct", ascending=False).head(12).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(by_rate["customer_state"], by_rate["delay_rate_pct"])
    ax.axvline(stats["baseline_delay_rate_pct"], linestyle="--", label="National observed delay rate")
    ax.set_xlabel("Delayed / delivered orders (%)")
    ax.set_title("Highest qualified regional delay rates (min. 500 deliveries)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "01_regional_rates_vs_baseline.png", dpi=180)
    plt.close(fig)

    by_gap = regions.loc[regions["hypothetical_excess_delay_equivalents"] > 0].head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(by_gap["customer_state"], by_gap["hypothetical_excess_delay_equivalents"])
    ax.set_xlabel("Hypothetical delay-order equivalents above national rate")
    ax.set_title("Regional investigation priority: arithmetic gap, NOT predicted impact")
    fig.tight_layout()
    fig.savefig(PLOTS / "02_regional_hypothetical_gaps.png", dpi=180)
    plt.close(fig)

    watch = outputs["high_risk_seller_watchlist"].copy().sort_values("delayed_seller_order_pairs")
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(watch["seller_id"].str.slice(0, 8), watch["delayed_seller_order_pairs"])
    ax.set_xlabel("Delayed seller-order pairs (NOT unique cross-seller orders)")
    ax.set_title("High-risk sellers: review by observed delayed seller-order volume")
    fig.tight_layout()
    fig.savefig(PLOTS / "03_high_risk_seller_volume.png", dpi=180)
    plt.close(fig)

    top = outputs["product_category_concentration"].head(12).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(top["product_category_name_en"], top["product_revenue"])
    ax.set_xlabel("Product revenue (freight excluded; dataset currency)")
    ax.set_title("Top 12 product categories by product revenue")
    fig.tight_layout()
    fig.savefig(PLOTS / "04_category_revenue.png", dpi=180)
    plt.close(fig)


def render_report(data: dict[str, pd.DataFrame], outputs: dict[str, pd.DataFrame], st: dict) -> str:
    regional = outputs["regional_investigation_priorities"]
    by_rate = regional.sort_values("delay_rate_pct", ascending=False)
    by_excess = regional.iloc[0]
    max_rate = by_rate.iloc[0]
    sellers = outputs["high_risk_seller_watchlist"]
    categories = outputs["product_category_concentration"]
    rev = data["reviews"].set_index("delivery_status_group")
    on_time = rev.loc["On Time or Early"]
    delayed = rev.loc["Delayed"]
    score_gap = float(on_time["avg_review_score"] - delayed["avg_review_score"])
    low_review_gap = float(delayed["low_review_rate_pct"] - on_time["low_review_rate_pct"])
    top5_share = float(categories.head(5)["product_revenue"].sum()) / st["product_revenue"] * 100
    high_risk_share = 100 * st["high_risk_seller_count"] / st["qualified_seller_count"]
    benchmark = st["baseline_delay_rate_pct"]
    return f"""# Olist | Business Insights & Prioritized Investigation Plan

Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}

## Evidence base and validation
- Based on read-only aggregates created by `03_exploratory_analysis.py`.
- **{st['orders']:,}** distinct orders, **{st['items']:,}** order items; sales **{st['sales_total']:,.2f}** (dataset currency units), with cross-extract reconciliation confirmed.
- National observed delayed-delivery rate: **{benchmark:.2f}%** ({st['delayed']:,} delayed / {st['delivered']:,} delivered).
- Regional comparisons require **{MIN_STATE_DELIVERED_ORDERS}+** delivered orders. Seller eligibility requires **{MIN_SELLER_DELIVERED_ORDERS}+** delivered seller-order pairs; high risk = delay rate **>= {HIGH_RISK_SELLER_RATE_PCT:.0f}%**.

## Ranked business findings

### 1. Regional delivery performance
- Highest qualifying *delay rate*: **{max_rate['customer_state']} at {float(max_rate['delay_rate_pct']):.2f}%** ({int(max_rate['delayed_orders']):,} delayed / {int(max_rate['delivered_orders']):,} delivered).
- Greatest arithmetic gap versus the observed national benchmark: **{by_excess['customer_state']}**, with **{float(by_excess['hypothetical_excess_delay_equivalents']):,.1f}** hypothetical delayed-order equivalents above that benchmark.
- **Action to investigate:** compare fulfillment and carrier handoffs in higher-rate states; stratify by seller, product category, distance, and month before assigning causes.
- **Caution:** the arithmetic gap is a prioritization aid, NOT an estimate of avoidable delays or the effect of an intervention; the national benchmark includes the state itself.

### 2. Seller risk prioritization
- **{st['high_risk_seller_count']} of {st['qualified_seller_count']}** qualified sellers (**{high_risk_share:.2f}%**) exceed or meet the {HIGH_RISK_SELLER_RATE_PCT:.0f}% high-risk threshold.
- Unweighted mean qualified-seller delay rate: **{st['avg_qualified_seller_delay_pct']:.2f}%**. This is not the national delayed-order percentage.
- **Action to investigate:** review shipping preparation and carrier exceptions for watchlist sellers, starting with higher delayed seller-order volumes. Validate operational context before escalation.
- **Critical grain note:** seller-order pairs can overlap across sellers on the same customer order. DO NOT sum seller counts and describe them as unique customer orders.

### 3. Reviews and delivery experience
- On-time/early average review **{float(on_time['avg_review_score']):.2f}/5**; delayed average review **{float(delayed['avg_review_score']):.2f}/5** (difference **{score_gap:.2f} points**).
- Low-review rates: delayed **{float(delayed['low_review_rate_pct']):.2f}%** versus on-time/early **{float(on_time['low_review_rate_pct']):.2f}%** (difference **{low_review_gap:.2f} percentage points**).
- **Action to investigate:** compare review outcomes among operationally similar orders and test delivery-time improvements with an appropriate control group.
- **Caution:** correlations and comparisons are descriptive, not evidence that late delivery alone caused poor reviews. The third delivery-status group also mixes non-delivery and unknown timing.

### 4. Product-category concentration
- Largest category by product revenue: **{categories.iloc[0]['product_category_name_en']}** (**{float(categories.iloc[0]['product_revenue']):,.2f}**).
- Top five categories account for **{top5_share:.2f}%** of product revenue. Product revenue excludes freight; total sales includes freight.
- **Action to investigate:** check whether service issues concentrate within high-revenue categories while controlling for regional/seller mix.

## Practical next steps (investigations, not guaranteed outcomes)
1. Review the top regional-priority cases with order-level operations data, checking volume and rate together.
2. Audit the **{st['high_risk_seller_count']}** flagged sellers, distinguishing seller-order pairs from unique customer orders.
3. Compare customer-review outcomes across delivery status under comparable conditions; test any operational changes before claiming impact.

## Important limitations
- Data is historical Olist commerce data; no live business intervention or outcome was observed.
- Some end-of-series months are partial, so they must not be treated as representative month-over-month growth or decline.
- Eight delivered orders have unknown delay timing in the validated portfolio. Preserve the unknown category.
- SQL/Python quality checks cover defined rules but cannot prove all real-world source values are error-free.
- No forecast, causal effect, or realized monetary savings is claimed.
- Charts and CSVs are intended as audit-friendly supporting evidence.
"""


def main() -> None:
    print("=== OLIST BUSINESS INSIGHTS ===")
    data = load()
    stats = validate(data)
    outputs = prepare_outputs(data, stats)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        frame.to_csv(OUTPUT / f"{name}.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    make_charts(data, outputs, stats)
    report = render_report(data, outputs, stats)
    (OUTPUT / "BUSINESS_INSIGHTS_REPORT.md").write_text(report, encoding="utf-8")
    print(f"Orders: {stats['orders']:,}; order items: {stats['items']:,}; sales: {stats['sales_total']:,.2f}")
    print(f"Delay rate: {stats['baseline_delay_rate_pct']:.2f}%")
    print(f"Qualified sellers: {stats['qualified_seller_count']}; high-risk sellers: {stats['high_risk_seller_count']}")
    print(f"Average qualified seller delay rate: {stats['avg_qualified_seller_delay_pct']:.4f}%")
    print(f"Wrote {len(outputs)} CSV tables, 4 charts, 1 report in: {OUTPUT}")
    print("Business insights complete.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
