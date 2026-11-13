"""
Olist BI Portfolio
File: 02_kpi_validation.py

Purpose
-------
Validate the final portfolio KPIs directly against the
configured Olist SQL Server analytics layer.

Requirements
------------
pip install pyodbc

Connection
----------
Server   : localhost\\SQLEXPRESS
Database : automatically discovered when unambiguous
Auth     : Windows Authentication (Trusted Connection)

Environment-variable overrides:
OLIST_SQL_SERVER
OLIST_SQL_DATABASE
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

import pyodbc
from sql_connection import SERVER, connect_analytics


@dataclass
class CheckResult:
    check_name: str
    actual: Any
    expected: Any
    status: str
    note: str = ""


def connect() -> pyodbc.Connection:
    """Connect to the prepared Olist analytics database without changing it."""
    try:
        connection, selected_database = connect_analytics(timeout=10)
        print(f"Connected to SQL Server: {SERVER} | database: {selected_database}")
        return connection
    except (pyodbc.Error, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            "Could not open the Olist analytics database. "
            "Confirm SQL Server and the ODBC driver are installed, or "
            "set OLIST_SQL_DATABASE explicitly."
        ) from exc

def fetch_one(conn: pyodbc.Connection, query: str) -> tuple:
    row = conn.cursor().execute(query).fetchone()
    if row is None:
        raise RuntimeError("The KPI query returned no rows.")
    return tuple(row)


def add_exact(
    results: list[CheckResult],
    name: str,
    actual: Any,
    expected: Any,
    note: str = "",
) -> None:
    status = "PASS" if actual == expected else "FAIL"
    results.append(CheckResult(name, actual, expected, status, note))


def add_close(
    results: list[CheckResult],
    name: str,
    actual: float,
    expected: float,
    tolerance: float = 0.01,
    note: str = "",
) -> None:
    actual_value = round(float(actual), 4)
    status = "PASS" if abs(actual_value - expected) <= tolerance else "FAIL"
    results.append(
        CheckResult(name, actual_value, expected, status, note)
    )


def print_results(results: list[CheckResult]) -> None:
    print("\n=== OLIST KPI VALIDATION ===\n")

    name_width = max(len(r.check_name) for r in results)
    actual_width = max(len(str(r.actual)) for r in results)
    expected_width = max(len(str(r.expected)) for r in results)

    header = (
        f"{'check_name':<{name_width}}  "
        f"{'actual':>{actual_width}}  "
        f"{'expected':>{expected_width}}  status"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        print(
            f"{r.check_name:<{name_width}}  "
            f"{str(r.actual):>{actual_width}}  "
            f"{str(r.expected):>{expected_width}}  "
            f"{r.status}"
        )
        if r.note:
            print(f"  note: {r.note}")

    passed = sum(r.status == "PASS" for r in results)
    failed = sum(r.status == "FAIL" for r in results)

    print("\nSummary:")
    print(f"PASS: {passed}")
    print(f"FAIL: {failed}")

    if failed:
        print("\nOne or more KPI checks failed. Review before publishing.")
        sys.exit(1)

    print("\nAll KPI checks passed.")


def main() -> None:
    results: list[CheckResult] = []

    with connect() as conn:
        # ------------------------------------------------------------
        # 1. Executive KPIs
        # ------------------------------------------------------------
        executive = fetch_one(
            conn,
            """
            SELECT
                CAST(SUM(order_total_value) AS decimal(38,2)) AS order_value,
                COUNT(DISTINCT order_id) AS total_orders,
                COUNT(DISTINCT CASE
                    WHEN is_delivered = 1 THEN order_id
                END) AS delivered_orders,
                COUNT(DISTINCT CASE
                    WHEN is_delivered = 1
                     AND is_delayed = 0 THEN order_id
                END) AS on_time_orders,
                COUNT(DISTINCT CASE
                    WHEN is_delayed = 1 THEN order_id
                END) AS delayed_orders,
                COUNT(DISTINCT CASE
                    WHEN is_delivered = 1
                     AND is_delayed IS NULL THEN order_id
                END) AS unknown_delivery_timing,
                CAST(
                    100.0
                    * COUNT(DISTINCT CASE
                        WHEN is_delayed = 1 THEN order_id
                      END)
                    / NULLIF(
                        COUNT(DISTINCT CASE
                            WHEN is_delivered = 1 THEN order_id
                        END),
                        0
                    )
                    AS decimal(10,2)
                ) AS delay_rate_pct,
                CAST(
                    AVG(CAST(avg_review_score AS decimal(18,6)))
                    AS decimal(10,2)
                ) AS average_review_score
            FROM analytics.fact_orders;
            """,
        )

        order_value, total_orders, delivered, on_time, delayed, unknown, delay_rate, avg_review = executive

        add_close(results, "Order Value", float(order_value), 15_843_553.24)
        add_exact(results, "Total Orders", int(total_orders), 99_441)
        add_exact(results, "Delivered Orders", int(delivered), 96_478)
        add_exact(results, "On-Time / Early Orders", int(on_time), 88_644)
        add_exact(results, "Delayed Orders", int(delayed), 7_826)
        add_exact(results, "Unknown Delivery Timing", int(unknown), 8)
        add_close(results, "Delay Rate %", float(delay_rate), 8.11)
        add_close(results, "Average Review Score", float(avg_review), 4.09)

        add_exact(
            results,
            "Delivered reconciliation",
            int(on_time) + int(delayed) + int(unknown),
            int(delivered),
            "Delivered = On-Time + Delayed + Unknown Timing.",
        )

        # ------------------------------------------------------------
        # 2. Sales KPIs
        # ------------------------------------------------------------
        sales = fetch_one(
            conn,
            """
            SELECT
                CAST(SUM(item_total_value) AS decimal(38,2)) AS total_sales,
                CAST(SUM(item_price) AS decimal(38,2)) AS product_revenue,
                CAST(SUM(freight_value) AS decimal(38,2)) AS total_freight,
                COUNT(*) AS items_sold,
                COUNT(DISTINCT product_id) AS distinct_products
            FROM analytics.fact_sales;
            """,
        )

        total_sales, product_revenue, total_freight, items_sold, distinct_products = sales

        add_close(results, "Total Sales", float(total_sales), 15_843_553.24)
        add_close(results, "Product Revenue", float(product_revenue), 13_591_643.70)
        add_close(results, "Total Freight", float(total_freight), 2_251_909.54)
        add_exact(results, "Items Sold", int(items_sold), 112_650)
        add_exact(results, "Distinct Products", int(distinct_products), 32_951)

        average_order_value = float(order_value) / int(total_orders)
        add_close(results, "Average Order Value", average_order_value, 159.33)

        # ------------------------------------------------------------
        # 3. Delivery & Customer Satisfaction
        # ------------------------------------------------------------
        cursor = conn.cursor()
        delivery_rows = cursor.execute(
            """
            SELECT
                delivery_status_group,
                CAST(
                    AVG(CAST(avg_review_score AS decimal(18,6)))
                    AS decimal(10,2)
                ) AS average_review_score,
                CAST(
                    100.0
                    * COUNT(DISTINCT CASE
                        WHEN is_low_review = 1 THEN order_id
                      END)
                    / NULLIF(COUNT(DISTINCT order_id), 0)
                    AS decimal(10,2)
                ) AS low_review_rate_pct
            FROM analytics.fact_orders
            GROUP BY delivery_status_group;
            """
        ).fetchall()

        delivery_expected = {
            "On Time or Early": (4.29, 9.14),
            "Delayed": (2.57, 52.85),
            "Not Delivered / Unknown": (1.75, 74.49),
        }

        delivery_actual = {
            row[0]: (float(row[1]), float(row[2]))
            for row in delivery_rows
        }

        for group, (expected_review, expected_low_review) in delivery_expected.items():
            if group not in delivery_actual:
                results.append(
                    CheckResult(
                        f"{group} group exists",
                        "MISSING",
                        "PRESENT",
                        "FAIL",
                    )
                )
                continue

            actual_review, actual_low_review = delivery_actual[group]

            add_close(
                results,
                f"{group} Avg Review",
                actual_review,
                expected_review,
            )
            add_close(
                results,
                f"{group} Low Review %",
                actual_low_review,
                expected_low_review,
            )

        # ------------------------------------------------------------
        # 4. Regional delay-rate validation
        #    Only states with 500+ delivered orders qualify.
        # ------------------------------------------------------------
        regional_rows = cursor.execute(
            """
            WITH state_metrics AS (
                SELECT
                    customer_state,
                    COUNT(DISTINCT CASE
                        WHEN is_delivered = 1 THEN order_id
                    END) AS delivered_orders,
                    COUNT(DISTINCT CASE
                        WHEN is_delayed = 1 THEN order_id
                    END) AS delayed_orders
                FROM analytics.fact_orders
                WHERE customer_state IS NOT NULL
                GROUP BY customer_state
            )
            SELECT TOP (5)
                customer_state,
                CAST(
                    100.0 * delayed_orders
                    / NULLIF(delivered_orders, 0)
                    AS decimal(10,2)
                ) AS delay_rate_pct
            FROM state_metrics
            WHERE delivered_orders >= 500
            ORDER BY
                1.0 * delayed_orders / NULLIF(delivered_orders, 0) DESC,
                customer_state;
            """
        ).fetchall()

        expected_top_states = [
            ("MA", 19.67),
            ("CE", 15.32),
            ("BA", 14.04),
            ("RJ", 13.47),
            ("PA", 12.37),
        ]

        actual_top_states = [(row[0], float(row[1])) for row in regional_rows]

        add_exact(
            results,
            "Top 5 regional states order",
            [state for state, _ in actual_top_states],
            [state for state, _ in expected_top_states],
        )

        for (actual_state, actual_rate), (expected_state, expected_rate) in zip(
            actual_top_states,
            expected_top_states,
        ):
            if actual_state == expected_state:
                add_close(
                    results,
                    f"{actual_state} Delay Rate %",
                    actual_rate,
                    expected_rate,
                )

        # ------------------------------------------------------------
        # 5. Seller Risk KPIs
        # ------------------------------------------------------------
        seller = fetch_one(
            conn,
            """
            WITH seller_metrics AS (
                SELECT
                    seller_id,
                    COUNT(DISTINCT CASE
                        WHEN is_delivered = 1 THEN order_id
                    END) AS delivered_orders,
                    COUNT(DISTINCT CASE
                        WHEN is_delayed = 1 THEN order_id
                    END) AS delayed_orders
                FROM analytics.fact_sales
                WHERE seller_id IS NOT NULL
                GROUP BY seller_id
            ),
            seller_rates AS (
                SELECT
                    seller_id,
                    delivered_orders,
                    delayed_orders,
                    1.0 * delayed_orders
                        / NULLIF(delivered_orders, 0) AS delay_rate
                FROM seller_metrics
            )
            SELECT
                COUNT(*) AS total_sellers,
                SUM(CASE
                    WHEN delayed_orders > 0 THEN 1 ELSE 0
                END) AS sellers_with_delays,
                SUM(CASE
                    WHEN delivered_orders >= 100 THEN 1 ELSE 0
                END) AS qualified_sellers,
                SUM(CASE
                    WHEN delivered_orders >= 100
                     AND delay_rate >= 0.15 THEN 1 ELSE 0
                END) AS high_risk_sellers,
                CAST(
                    100.0 * AVG(
                        CASE
                            WHEN delivered_orders >= 100
                            THEN delay_rate
                        END
                    )
                    AS decimal(10,2)
                ) AS avg_qualified_delay_rate_pct
            FROM seller_rates;
            """,
        )

        total_sellers, sellers_with_delays, qualified_sellers, high_risk_sellers, avg_qualified_rate = seller

        add_exact(results, "Total Sellers", int(total_sellers), 3_095)
        add_exact(results, "Sellers with Delays", int(sellers_with_delays), 1_390)
        add_exact(results, "Qualified Sellers", int(qualified_sellers), 210)
        add_exact(results, "High-Risk Sellers", int(high_risk_sellers), 11)
        add_close(
            results,
            "Qualified Avg Delay Rate %",
            float(avg_qualified_rate),
            7.62,
        )

    print_results(results)


if __name__ == "__main__":
    main()
