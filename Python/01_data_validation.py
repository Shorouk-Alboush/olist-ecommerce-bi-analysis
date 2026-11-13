"""
Olist BI Portfolio
File: 01_data_validation.py

Purpose
-------
Run read-only structural and data-quality checks against the final
configured Olist SQL Server database.

Requirements
------------
pip install pandas pyodbc

Connection
----------
Server   : localhost\\SQLEXPRESS
Database : automatically discovered when unambiguous
Auth     : Windows Authentication (Trusted Connection)

You can override connection settings with environment variables:
OLIST_SQL_SERVER
OLIST_SQL_DATABASE
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pandas as pd
import pyodbc
from sql_connection import SERVER, connect_analytics


@dataclass
class CheckResult:
    check_name: str
    actual: object
    expected: object
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

def scalar(conn: pyodbc.Connection, query: str) -> object:
    """Return the first value from a single-value SQL query."""
    row = conn.cursor().execute(query).fetchone()
    return None if row is None else row[0]


def add_check(
    results: list[CheckResult],
    name: str,
    actual: object,
    expected: object,
    note: str = "",
) -> None:
    status = "PASS" if actual == expected else "FAIL"
    results.append(CheckResult(name, actual, expected, status, note))


def print_results(results: list[CheckResult]) -> None:
    """Print a compact validation table."""
    df = pd.DataFrame([r.__dict__ for r in results])
    print("\n=== OLIST DATA VALIDATION ===\n")
    print(df.to_string(index=False))

    failed = df[df["status"] == "FAIL"]
    print("\nSummary:")
    print(f"PASS: {(df['status'] == 'PASS').sum()}")
    print(f"FAIL: {(df['status'] == 'FAIL').sum()}")

    if not failed.empty:
        print("\nOne or more checks failed. Review the affected rows before publishing.")
        sys.exit(1)

    print("\nAll structural and data-quality checks passed.")


def main() -> None:
    results: list[CheckResult] = []

    with connect() as conn:
        # ------------------------------------------------------------
        # 1. Core row counts
        # ------------------------------------------------------------
        add_check(
            results,
            "clean.orders row count",
            scalar(conn, "SELECT COUNT(*) FROM clean.orders;"),
            99_441,
        )

        add_check(
            results,
            "clean.order_items row count",
            scalar(conn, "SELECT COUNT(*) FROM clean.order_items;"),
            112_650,
        )

        add_check(
            results,
            "analytics.fact_orders row count",
            scalar(conn, "SELECT COUNT(*) FROM analytics.fact_orders;"),
            99_441,
        )

        add_check(
            results,
            "analytics.fact_sales row count",
            scalar(conn, "SELECT COUNT(*) FROM analytics.fact_sales;"),
            112_650,
        )

        add_check(
            results,
            "analytics.dim_date row count",
            scalar(conn, "SELECT COUNT(*) FROM analytics.dim_date;"),
            774,
        )

        # ------------------------------------------------------------
        # 2. Grain validation
        # ------------------------------------------------------------
        add_check(
            results,
            "fact_orders duplicate order_id rows",
            scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT order_id
                    FROM analytics.fact_orders
                    GROUP BY order_id
                    HAVING COUNT(*) > 1
                ) AS d;
                """,
            ),
            0,
            "Expected grain: one row per order_id.",
        )

        add_check(
            results,
            "fact_sales duplicate order-item keys",
            scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT order_id, order_item_id
                    FROM analytics.fact_sales
                    GROUP BY order_id, order_item_id
                    HAVING COUNT(*) > 1
                ) AS d;
                """,
            ),
            0,
            "Expected grain: one row per (order_id, order_item_id).",
        )

        # ------------------------------------------------------------
        # 3. Key coverage
        # ------------------------------------------------------------
        add_check(
            results,
            "fact_orders NULL customer_id rows",
            scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM analytics.fact_orders
                WHERE customer_id IS NULL;
                """,
            ),
            0,
        )

        add_check(
            results,
            "fact_sales NULL product_id rows",
            scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM analytics.fact_sales
                WHERE product_id IS NULL;
                """,
            ),
            0,
        )

        add_check(
            results,
            "fact_sales NULL seller_id rows",
            scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM analytics.fact_sales
                WHERE seller_id IS NULL;
                """,
            ),
            0,
        )

        # ------------------------------------------------------------
        # 4. Financial reconciliation
        # ------------------------------------------------------------
        item_total_mismatches = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM analytics.fact_sales
            WHERE ABS(
                CAST(item_total_value AS decimal(38,2))
                - (
                    CAST(item_price AS decimal(38,2))
                    + CAST(freight_value AS decimal(38,2))
                  )
            ) > 0.01;
            """,
        )
        add_check(
            results,
            "item_total_value arithmetic mismatches",
            item_total_mismatches,
            0,
            "item_total_value should equal item_price + freight_value.",
        )

        fact_total_difference = scalar(
            conn,
            """
            SELECT CAST(
                ABS(
                    (SELECT SUM(item_total_value) FROM analytics.fact_sales)
                    -
                    (SELECT SUM(order_total_value) FROM analytics.fact_orders)
                )
                AS decimal(38,2)
            );
            """,
        )
        add_check(
            results,
            "fact_sales vs fact_orders total difference",
            float(fact_total_difference),
            0.0,
            "Order-level and item-level totals should reconcile.",
        )

        # ------------------------------------------------------------
        # 5. Date dimension coverage
        # ------------------------------------------------------------
        date_row = conn.cursor().execute(
            """
            WITH source_dates AS (
                SELECT
                    MIN(order_purchase_date) AS source_min_date,
                    MAX(order_purchase_date) AS source_max_date
                FROM clean.orders
                WHERE order_purchase_date IS NOT NULL
            ),
            dim_dates AS (
                SELECT
                    MIN(date_value) AS dim_min_date,
                    MAX(date_value) AS dim_max_date,
                    COUNT(*) AS dim_rows,
                    COUNT(DISTINCT date_value) AS distinct_dim_dates
                FROM analytics.dim_date
            )
            SELECT
                source_min_date,
                source_max_date,
                dim_min_date,
                dim_max_date,
                dim_rows,
                distinct_dim_dates,
                DATEDIFF(DAY, source_min_date, source_max_date) + 1
                    AS expected_calendar_days
            FROM source_dates
            CROSS JOIN dim_dates;
            """
        ).fetchone()

        source_min_date = date_row[0]
        source_max_date = date_row[1]
        dim_min_date = date_row[2]
        dim_max_date = date_row[3]
        dim_rows = int(date_row[4])
        distinct_dim_dates = int(date_row[5])
        expected_calendar_days = int(date_row[6])

        add_check(
            results,
            "dim_date minimum date",
            str(dim_min_date),
            str(source_min_date),
        )
        add_check(
            results,
            "dim_date maximum date",
            str(dim_max_date),
            str(source_max_date),
        )
        add_check(
            results,
            "dim_date calendar continuity",
            dim_rows,
            expected_calendar_days,
        )
        add_check(
            results,
            "dim_date duplicate dates",
            dim_rows - distinct_dim_dates,
            0,
        )

    print_results(results)


if __name__ == "__main__":
    main()
