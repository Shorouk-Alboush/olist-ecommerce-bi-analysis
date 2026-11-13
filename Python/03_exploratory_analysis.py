"""Olist BI Portfolio | 03_exploratory_analysis.py

Read-only exploratory data analysis (EDA) using SQL Server + pandas + matplotlib.

Source database: prepared Olist analytics database (auto-detected)
Source views:     analytics.fact_orders, analytics.fact_sales

Install once in Windows Command Prompt:
    py -m pip install pyodbc pandas matplotlib

Run from the project's Python folder:
    py 03_exploratory_analysis.py

Outputs are written to Python/EDA_Outputs/ (CSV summaries, PNG charts,
EDA_SUMMARY.md). The script never modifies SQL tables or views.

Connection settings (same defaults as 01/02 validation scripts):
    OLIST_SQL_SERVER   default: localhost\\SQLEXPRESS
    OLIST_SQL_DATABASE optional override for automatic discovery
    OLIST_ODBC_DRIVER  default: ODBC Driver 17 for SQL Server
"""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")  # Save charts to files; no popup windows needed.
    import matplotlib.pyplot as plt
    import pyodbc
    from sql_connection import SERVER, connect_analytics
except ImportError as error:
    print(f"Missing Python package: {error}")
    print("Install dependencies with: py -m pip install pyodbc pandas matplotlib")
    sys.exit(1)

OUTPUT_DIR = Path(__file__).resolve().parent / "EDA_Outputs"

# Explicit columns protect the order-level and item-level grains.
ORDERS_SQL = """
SELECT order_id, order_purchase_date, order_total_value, is_delivered,
       is_delayed, delivery_days, avg_review_score, is_low_review,
       customer_state, delivery_status_group
FROM analytics.fact_orders;
"""
SALES_SQL = """
SELECT order_id, order_item_id, product_category_name_en,
       seller_id, seller_city, seller_state,
       item_price, freight_value, item_total_value,
       is_delivered, is_delayed
FROM analytics.fact_sales;
"""


def fetch_dataframe(connection: pyodbc.Connection, query: str) -> pd.DataFrame:
    """Read an existing analytics view without creating or changing any object."""
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        column_names = [item[0] for item in cursor.description]
        return pd.DataFrame.from_records(
            [tuple(row) for row in cursor.fetchall()], columns=column_names
        )
    finally:
        cursor.close()


def prepare(orders: pd.DataFrame, sales: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    orders = orders.copy()
    sales = sales.copy()
    if orders.empty or sales.empty:
        raise ValueError("The SQL analytics views returned no data.")

    for column in ("order_total_value", "delivery_days", "avg_review_score",
                   "is_delivered", "is_delayed", "is_low_review"):
        orders[column] = pd.to_numeric(orders[column], errors="coerce")
    for column in ("item_price", "freight_value", "item_total_value",
                   "is_delivered", "is_delayed"):
        sales[column] = pd.to_numeric(sales[column], errors="coerce")

    orders["order_purchase_date"] = pd.to_datetime(
        orders["order_purchase_date"], errors="coerce"
    )
    orders["purchase_month"] = orders["order_purchase_date"].dt.to_period("M")
    orders["delivered_flag"] = orders["is_delivered"].eq(1).astype(int)
    orders["delayed_flag"] = orders["is_delayed"].eq(1).astype(int)
    orders["on_time_flag"] = (
        orders["is_delivered"].eq(1) & orders["is_delayed"].eq(0)
    ).astype(int)
    orders["unknown_timing_flag"] = (
        orders["is_delivered"].eq(1) & orders["is_delayed"].isna()
    ).astype(int)
    orders["low_review_flag"] = orders["is_low_review"].eq(1).astype(int)
    sales["delivered_flag"] = sales["is_delivered"].eq(1).astype(int)
    sales["delayed_flag"] = sales["is_delayed"].eq(1).astype(int)

    # Critical checks: abort instead of publishing misleading metrics.
    duplicate_orders = int(orders.duplicated(subset=["order_id"]).sum())
    duplicate_items = int(sales.duplicated(subset=["order_id", "order_item_id"]).sum())
    if duplicate_orders or duplicate_items:
        raise ValueError(
            f"Unexpected duplicate keys: orders={duplicate_orders}, "
            f"order items={duplicate_items}. Resolve before EDA."
        )
    order_total = float(orders["order_total_value"].sum())
    item_total = float(sales["item_total_value"].sum())
    if not math.isclose(order_total, item_total, abs_tol=0.02, rel_tol=0):
        raise ValueError(
            f"Sales totals do not reconcile: orders={order_total:,.2f}, "
            f"items={item_total:,.2f}."
        )
    return orders, sales


def summarize(orders: pd.DataFrame, sales: pd.DataFrame) -> dict:
    """Use pandas groupby at the correct grain for each business question."""
    # 1. Order-level monthly trends. Partial boundary months remain in output.
    monthly = (
        orders.dropna(subset=["purchase_month"])
        .groupby("purchase_month", sort=True)
        .agg(
            orders=("order_id", "nunique"),
            delivered_orders=("delivered_flag", "sum"),
            delayed_orders=("delayed_flag", "sum"),
            sales_value=("order_total_value", "sum"),
        )
        .reset_index()
    )
    monthly["average_order_value"] = monthly["sales_value"] / monthly["orders"]
    monthly["delay_rate_pct"] = (
        100 * monthly["delayed_orders"] / monthly["delivered_orders"].replace(0, float("nan"))
    )
    monthly["purchase_month"] = monthly["purchase_month"].astype(str)

    # 2. Item-level product/category performance: never sum order_total_value
    #    over an item-level table, which would double-count multi-item orders.
    categories = (
        sales.dropna(subset=["product_category_name_en"])
        .groupby("product_category_name_en")
        .agg(
            items_sold=("order_item_id", "size"),
            orders=("order_id", "nunique"),
            product_revenue=("item_price", "sum"),
            freight_value=("freight_value", "sum"),
            total_sales=("item_total_value", "sum"),
        )
        .reset_index()
        .sort_values(["product_revenue", "product_category_name_en"], ascending=[False, True])
    )
    total_product_revenue = float(sales["item_price"].sum())
    categories["share_of_all_product_revenue_pct"] = (
        100 * categories["product_revenue"] / total_product_revenue
        if total_product_revenue else float("nan")
    )

    # 3. State rate is delayed delivered orders / delivered orders.
    states = (
        orders.dropna(subset=["customer_state"])
        .groupby("customer_state")
        .agg(
            orders=("order_id", "nunique"),
            delivered_orders=("delivered_flag", "sum"),
            delayed_orders=("delayed_flag", "sum"),
            sales_value=("order_total_value", "sum"),
        )
        .reset_index()
    )
    states["delay_rate_pct"] = 100 * states["delayed_orders"] / states["delivered_orders"].replace(0, float("nan"))
    states["qualifies_for_delay_ranking"] = states["delivered_orders"] >= 500
    states = states.sort_values(
        ["qualifies_for_delay_ranking", "delay_rate_pct", "customer_state"],
        ascending=[False, False, True],
    )
    qualified_states = states.loc[states["qualifies_for_delay_ranking"]].copy()

    # 4. One review per order. Denominator of low-review percentage is all
    #    orders in the delivery-status group (matches SQL and Power BI).
    reviews = (
        orders.groupby("delivery_status_group", dropna=False)
        .agg(
            orders=("order_id", "nunique"),
            orders_with_review=("avg_review_score", "count"),
            avg_review_score=("avg_review_score", "mean"),
            low_review_orders=("low_review_flag", "sum"),
        )
        .reset_index()
    )
    reviews["low_review_rate_pct"] = 100 * reviews["low_review_orders"] / reviews["orders"]
    review_order = {"On Time or Early": 0, "Delayed": 1, "Not Delivered / Unknown": 2}
    reviews["_sort_order"] = reviews["delivery_status_group"].map(review_order).fillna(3)
    reviews = reviews.sort_values(["_sort_order", "delivery_status_group"]).drop(columns="_sort_order")

    # 5. Seller: DISTINCT (seller_id, order_id) before counting deliveries.
    #    One seller may ship multiple items in the same order.
    seller_orders = sales.dropna(subset=["seller_id"]).drop_duplicates(
        subset=["seller_id", "order_id"]
    )
    sellers = (
        seller_orders.groupby("seller_id")
        .agg(
            orders=("order_id", "nunique"),
            delivered_orders=("delivered_flag", "sum"),
            delayed_orders=("delayed_flag", "sum"),
            seller_city=("seller_city", "first"),
            seller_state=("seller_state", "first"),
        )
        .reset_index()
    )
    sellers["delay_rate_pct"] = 100 * sellers["delayed_orders"] / sellers["delivered_orders"].replace(0, float("nan"))
    sellers["qualified"] = sellers["delivered_orders"] >= 100
    sellers["high_risk"] = sellers["qualified"] & sellers["delay_rate_pct"].ge(15)
    qualified_sellers = (
        sellers.loc[sellers["qualified"]]
        .sort_values(["delay_rate_pct", "delivered_orders", "seller_id"], ascending=[False, False, True])
        .copy()
    )

    # 6. Delivery-time and review-score exploration (descriptive, not causal).
    delivered = orders.loc[orders["is_delivered"].eq(1)].copy()
    delivered = delivered.dropna(subset=["delivery_days"])
    delivery_bins = [-float("inf"), -0.000001, 3, 7, 14, 30, float("inf")]
    delivery_labels = ["Negative", "0-3 days", "4-7 days", "8-14 days", "15-30 days", "31+ days"]
    delivered["delivery_days_group"] = pd.cut(
        delivered["delivery_days"], bins=delivery_bins, labels=delivery_labels,
        include_lowest=True
    )
    delivery_days = (
        delivered.groupby("delivery_days_group", observed=True)
        .agg(
            delivered_orders=("order_id", "nunique"),
            orders_with_review=("avg_review_score", "count"),
            avg_review_score=("avg_review_score", "mean"),
        )
        .reset_index()
    )
    delivery_days["delivery_days_group"] = delivery_days["delivery_days_group"].astype(str)
    review_days_pairs = delivered.dropna(subset=["avg_review_score"])
    correlation = (
        float(review_days_pairs["delivery_days"].corr(review_days_pairs["avg_review_score"]))
        if len(review_days_pairs) >= 2 else float("nan")
    )

    # 7. Distribution of per-order sales value.
    positive_order_values = orders.loc[
        orders["order_total_value"].gt(0), "order_total_value"
    ]
    percentiles = [0.25, 0.50, 0.75, 0.95, 0.99]
    order_value_distribution = pd.DataFrame({
        "percentile": ["P25", "Median/P50", "P75", "P95", "P99"],
        "order_value": [
            float(positive_order_values.quantile(p)) if not positive_order_values.empty else float("nan")
            for p in percentiles
        ],
    })

    diagnostics = {
        "order_rows": len(orders),
        "item_rows": len(sales),
        "delivered_orders": int(orders["delivered_flag"].sum()),
        "delayed_orders": int(orders["delayed_flag"].sum()),
        "on_time_orders": int(orders["on_time_flag"].sum()),
        "unknown_timing_orders": int(orders["unknown_timing_flag"].sum()),
        "null_purchase_dates": int(orders["order_purchase_date"].isna().sum()),
        "null_order_total_values": int(orders["order_total_value"].isna().sum()),
        "items_without_category": int(sales["product_category_name_en"].isna().sum()),
        "order_total": float(orders["order_total_value"].sum()),
        "item_total": float(sales["item_total_value"].sum()),
        "product_revenue": total_product_revenue,
        "total_sellers": len(sellers),
        "qualified_sellers": len(qualified_sellers),
        "high_risk_sellers": int(qualified_sellers["high_risk"].sum()),
        "avg_qualified_seller_delay_rate_pct": float(qualified_sellers["delay_rate_pct"].mean()),
        "review_delivery_days_correlation": correlation,
        "review_delivery_days_pairs": len(review_days_pairs),
    }
    if (
        diagnostics["on_time_orders"] + diagnostics["delayed_orders"]
        + diagnostics["unknown_timing_orders"] != diagnostics["delivered_orders"]
    ):
        raise ValueError("Delivered-order status reconciliation failed.")
    return {
        "monthly_trends": monthly,
        "category_performance": categories,
        "state_performance": states,
        "qualified_state_delays": qualified_states,
        "delivery_review_analysis": reviews,
        "qualified_seller_risk": qualified_sellers,
        "delivery_days_reviews": delivery_days,
        "order_value_distribution": order_value_distribution,
        "diagnostics": diagnostics,
    }


def write_charts(results: dict, charts_dir: Path) -> None:
    charts_dir.mkdir(parents=True, exist_ok=True)

    monthly = results["monthly_trends"]
    # Keep all months in monthly_trends.csv; the display omits sparse boundaries.
    chart_months = monthly.loc[
        monthly["purchase_month"].between("2017-01", "2018-08")
    ].copy()
    if not chart_months.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        positions = list(range(len(chart_months)))
        ax.plot(positions, chart_months["sales_value"].to_numpy(), marker="o", linewidth=1.6)
        step = max(1, len(positions) // 9)
        ticks = positions[::step]
        ax.set_xticks(ticks, chart_months["purchase_month"].iloc[ticks], rotation=35)
        ax.set_title("Monthly sales value (Jan 2017–Aug 2018)")
        ax.set_ylabel("Sales value (dataset currency units)")
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(charts_dir / "01_monthly_sales.png", dpi=180)
        plt.close(fig)

    categories = results["category_performance"].head(12).iloc[::-1]
    if not categories.empty:
        fig, ax = plt.subplots(figsize=(11, 6))
        ax.barh(categories["product_category_name_en"].astype(str), categories["product_revenue"])
        ax.set_title("Top 12 categories by product revenue (excluding freight)")
        ax.set_xlabel("Product revenue (dataset currency units)")
        fig.tight_layout()
        fig.savefig(charts_dir / "02_top_categories.png", dpi=180)
        plt.close(fig)

    states = results["qualified_state_delays"].head(12).iloc[::-1]
    if not states.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.barh(states["customer_state"].astype(str), states["delay_rate_pct"])
        ax.set_title("Highest state delay rates (500+ delivered orders)")
        ax.set_xlabel("Delayed / delivered orders (%)")
        fig.tight_layout()
        fig.savefig(charts_dir / "03_qualified_state_delays.png", dpi=180)
        plt.close(fig)

    reviews = results["delivery_review_analysis"].dropna(subset=["avg_review_score"])
    if not reviews.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.bar(reviews["delivery_status_group"].astype(str), reviews["avg_review_score"])
        ax.set_title("Average review score by delivery status")
        ax.set_ylabel("Average score (1-5)")
        ax.set_ylim(0, 5)
        ax.tick_params(axis="x", rotation=12)
        fig.tight_layout()
        fig.savefig(charts_dir / "04_delivery_reviews.png", dpi=180)
        plt.close(fig)

    sellers = results["qualified_seller_risk"]
    if not sellers.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.scatter(sellers["delivered_orders"], sellers["delay_rate_pct"], alpha=0.65)
        ax.axhline(15, linestyle="--", linewidth=1.3, label="15% high-risk threshold")
        ax.set_title("Qualified seller risk (100+ delivered orders)")
        ax.set_xlabel("Distinct delivered orders per seller")
        ax.set_ylabel("Delay rate (%)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(charts_dir / "05_seller_risk.png", dpi=180)
        plt.close(fig)

    delivery = results["delivery_days_reviews"].dropna(subset=["avg_review_score"])
    if not delivery.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.bar(delivery["delivery_days_group"], delivery["avg_review_score"])
        ax.set_title("Review score by delivery duration (descriptive)")
        ax.set_ylabel("Average score (1-5)")
        ax.set_ylim(0, 5)
        ax.tick_params(axis="x", rotation=12)
        fig.tight_layout()
        fig.savefig(charts_dir / "06_delivery_duration_reviews.png", dpi=180)
        plt.close(fig)


def fmt(value: float, decimals: int = 2) -> str:
    if not math.isfinite(float(value)):
        return "N/A"
    return f"{value:,.{decimals}f}"


def write_report(results: dict, path: Path) -> None:
    d = results["diagnostics"]
    top_category = results["category_performance"].head(1)
    top_state = results["qualified_state_delays"].head(1)
    top_category_text = (
        f"{top_category.iloc[0]['product_category_name_en']} "
        f"({fmt(float(top_category.iloc[0]['product_revenue']))} product revenue)"
        if not top_category.empty else "N/A"
    )
    top_state_text = (
        f"{top_state.iloc[0]['customer_state']} "
        f"({fmt(float(top_state.iloc[0]['delay_rate_pct']))}% delay rate)"
        if not top_state.empty else "N/A"
    )
    report = f"""# Olist | Exploratory Data Analysis Summary

Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}

## Source and scope
- SQL Server database: prepared Olist analytical database on `{SERVER}` (configured or auto-detected).
- Read-only views: `analytics.fact_orders` (one row per order) and
  `analytics.fact_sales` (one row per order item).
- Analyses and charts are descriptive; associations do not prove causation.

## Volume and reconciliation
- Orders: **{d['order_rows']:,}**.
- Order items: **{d['item_rows']:,}**.
- Sales value (order-level): **{fmt(d['order_total'])}**.
- Sales value (item-level): **{fmt(d['item_total'])}**.
- Product revenue excluding freight: **{fmt(d['product_revenue'])}**.
- Delivered: **{d['delivered_orders']:,}**; delayed: **{d['delayed_orders']:,}**;
  on time/early: **{d['on_time_orders']:,}**; delivered with unknown timing:
  **{d['unknown_timing_orders']:,}**.
- Delivered reconciliation: **{d['on_time_orders']:,} + {d['delayed_orders']:,} + {d['unknown_timing_orders']:,} = {d['delivered_orders']:,}**.

## Findings from the grouped extracts
- Leading category by product revenue: **{top_category_text}**.
- Highest delay rate among states with >=500 delivered orders: **{top_state_text}**.
- Sellers: **{d['total_sellers']:,}**; qualified (>=100 delivered orders):
  **{d['qualified_sellers']:,}**; high-risk (delay rate >=15%):
  **{d['high_risk_sellers']:,}**.
- Unweighted average seller delay rate among qualified sellers:
  **{fmt(d['avg_qualified_seller_delay_rate_pct'])}%**.
- Pearson correlation of delivery days vs. order review score for
  delivered orders with both values (n={d['review_delivery_days_pairs']:,}):
  **{fmt(d['review_delivery_days_correlation'], 4)}**. This is descriptive,
  subject to missing data and confounding factors, and is not a causal effect.

## Important data-quality and interpretation notes
- Delivered orders with missing delay status: **{d['unknown_timing_orders']:,}**;
  do NOT classify these as on time or delayed.
- Orders with missing purchase date: **{d['null_purchase_dates']:,}**;
  they are excluded from monthly trends (but included in overall totals).
- Orders with missing order-total value: **{d['null_order_total_values']:,}**;
  pandas `sum` ignores missing values, matching SQL `SUM` behavior here.
- Item rows with missing translated category: **{d['items_without_category']:,}**;
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
"""
    path.write_text(report, encoding="utf-8")


def validate_reference_values(d: dict) -> None:
    """Warnings only: these are known local portfolio benchmarks, not ground truth."""
    benchmarks = {
        "order_rows": 99_441,
        "item_rows": 112_650,
        "delivered_orders": 96_478,
        "delayed_orders": 7_826,
        "unknown_timing_orders": 8,
        "qualified_sellers": 210,
        "high_risk_sellers": 11,
    }
    warnings = []
    for key, expected in benchmarks.items():
        actual = d[key]
        if actual != expected:
            warnings.append(f"{key}: actual={actual}, reference={expected}")
    if abs(d["avg_qualified_seller_delay_rate_pct"] - 7.62) > 0.01:
        warnings.append(
            "avg_qualified_seller_delay_rate_pct: "
            f"actual={d['avg_qualified_seller_delay_rate_pct']:.4f}%, reference≈7.62%"
        )
    if warnings:
        print("\nWARNING: Differences from the locally validated portfolio reference:")
        for warning in warnings:
            print("  - " + warning)
        print("Review these differences before publishing; outputs remain available.")
    else:
        print("Reference check: selected portfolio KPIs match previously validated values.")


def main() -> None:
    print("=== OLIST EXPLORATORY DATA ANALYSIS ===")
    print("Loading two existing read-only analytics views...")
    try:
        conn, selected_database = connect_analytics(timeout=15)
        print(f"SQL Server: {SERVER} | Database: {selected_database}")
    except (pyodbc.Error, RuntimeError, ValueError) as error:
        print("Cannot connect. Start SQL Server and verify the ODBC driver / database settings.")
        print(f"Connection detail: {error}")
        sys.exit(1)

    try:
        orders = fetch_dataframe(conn, ORDERS_SQL)
        print(f"Loaded orders: {len(orders):,}")
        sales = fetch_dataframe(conn, SALES_SQL)
        print(f"Loaded order items: {len(sales):,}")
    except pyodbc.Error as error:
        print(f"Could not read analytics views: {error}")
        print("Confirm that analytics.fact_orders and analytics.fact_sales exist.")
        sys.exit(1)
    finally:
        conn.close()

    orders, sales = prepare(orders, sales)
    results = summarize(orders, sales)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export_count = 0
    for name, dataframe in results.items():
        if isinstance(dataframe, pd.DataFrame):
            dataframe.to_csv(OUTPUT_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")
            export_count += 1
    write_charts(results, OUTPUT_DIR / "charts")
    write_report(results, OUTPUT_DIR / "EDA_SUMMARY.md")
    d = results["diagnostics"]
    print("\n=== SUMMARY ===")
    print(f"Orders: {d['order_rows']:,} | Order items: {d['item_rows']:,}")
    print(f"Order sales value: {d['order_total']:,.2f}")
    print(f"Qualified sellers: {d['qualified_sellers']:,} | High risk: {d['high_risk_sellers']:,}")
    print(f"Qualified seller average delay rate: {d['avg_qualified_seller_delay_rate_pct']:.4f}%")
    print(f"Delivered orders with unknown timing: {d['unknown_timing_orders']:,}")
    validate_reference_values(d)
    print(f"\nCreated {export_count} CSV tables + charts + EDA_SUMMARY.md")
    print(f"Output folder: {OUTPUT_DIR}")
    print("EDA complete.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(f"\nERROR: {error}")
        sys.exit(1)
