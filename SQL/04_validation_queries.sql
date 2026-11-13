/*
Olist BI Portfolio
File: 04_validation_queries.sql
Database: selected prepared Olist analytics database

Purpose:
Run read-only integrity and reconciliation checks across the clean and analytics
layers used by the Power BI model.

Validation philosophy:
- No expected KPI values are hard-coded.
- Checks compare related objects and business-rule invariants directly.
- PASS means the compared values are internally consistent.
- REVIEW means the query found records that deserve inspection.

Safety:
- Read-only SELECT / CTE queries only.
- No data or schema changes.
*/

/* Select the prepared Olist database in the SSMS database dropdown. */
IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
   OR OBJECT_ID(N'clean.orders') IS NULL
BEGIN
    THROW 50001,
          'Choose the prepared Olist database in SSMS before running this script.', 1;
END;
GO

/* ============================================================
   1. Core Row-Count Reconciliation
   clean.orders should map one-to-one to analytics.fact_orders.
   clean.order_items should map one-to-one to analytics.fact_sales.
   ============================================================ */
WITH counts AS (
    SELECT
        (SELECT COUNT(*) FROM clean.orders) AS clean_orders_rows,
        (SELECT COUNT(*) FROM analytics.fact_orders) AS fact_orders_rows,
        (SELECT COUNT(*) FROM clean.order_items) AS clean_order_items_rows,
        (SELECT COUNT(*) FROM analytics.fact_sales) AS fact_sales_rows
)
SELECT
    clean_orders_rows,
    fact_orders_rows,
    CASE
        WHEN clean_orders_rows = fact_orders_rows THEN 'PASS'
        ELSE 'REVIEW'
    END AS orders_row_count_check,
    clean_order_items_rows,
    fact_sales_rows,
    CASE
        WHEN clean_order_items_rows = fact_sales_rows THEN 'PASS'
        ELSE 'REVIEW'
    END AS sales_row_count_check
FROM counts;
GO

/* ============================================================
   2. Fact Grain / Duplicate Checks
   fact_orders grain: one row per order_id.
   fact_sales grain: one row per (order_id, order_item_id).
   ============================================================ */
SELECT
    COUNT(*) AS fact_orders_rows,
    COUNT(DISTINCT order_id) AS distinct_order_ids,
    COUNT(*) - COUNT(DISTINCT order_id) AS duplicate_order_rows,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT order_id) THEN 'PASS'
        ELSE 'REVIEW'
    END AS fact_orders_grain_check
FROM analytics.fact_orders;
GO

WITH sales_grain AS (
    SELECT
        order_id,
        order_item_id,
        COUNT(*) AS row_count
    FROM analytics.fact_sales
    GROUP BY
        order_id,
        order_item_id
)
SELECT
    COUNT(*) AS distinct_order_item_keys,
    SUM(row_count) AS fact_sales_rows,
    SUM(CASE WHEN row_count > 1 THEN row_count - 1 ELSE 0 END) AS duplicate_rows,
    CASE
        WHEN MAX(row_count) = 1 THEN 'PASS'
        ELSE 'REVIEW'
    END AS fact_sales_grain_check
FROM sales_grain;
GO

/* ============================================================
   3. Sales-Value Reconciliation
   The order-level total should reconcile to the item-level total.
   ============================================================ */
WITH totals AS (
    SELECT
        (SELECT SUM(order_total_value) FROM analytics.fact_orders) AS fact_orders_total,
        (SELECT SUM(item_total_value) FROM analytics.fact_sales) AS fact_sales_total
)
SELECT
    fact_orders_total,
    fact_sales_total,
    fact_sales_total - fact_orders_total AS difference,
    CASE
        WHEN ABS(
            CAST(fact_sales_total AS decimal(38,2))
            - CAST(fact_orders_total AS decimal(38,2))
        ) <= 0.01
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS total_sales_reconciliation
FROM totals;
GO

/* ============================================================
   4. Item-Level Arithmetic Check
   item_total_value should equal item_price + freight_value.
   ============================================================ */
SELECT
    COUNT(*) AS rows_checked,
    SUM(
        CASE
            WHEN ABS(
                CAST(item_total_value AS decimal(38,2))
                - (
                    CAST(item_price AS decimal(38,2))
                    + CAST(freight_value AS decimal(38,2))
                  )
            ) > 0.01
            THEN 1
            ELSE 0
        END
    ) AS arithmetic_mismatch_rows,
    CASE
        WHEN SUM(
            CASE
                WHEN ABS(
                    CAST(item_total_value AS decimal(38,2))
                    - (
                        CAST(item_price AS decimal(38,2))
                        + CAST(freight_value AS decimal(38,2))
                      )
                ) > 0.01
                THEN 1
                ELSE 0
            END
        ) = 0
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS item_total_arithmetic_check
FROM analytics.fact_sales;
GO

/* ============================================================
   5. Delivery-Status Consistency and Completeness
   - Delayed orders must be delivered.
   - Delivered orders must reconcile across on-time, delayed, and
     unknown timing. Unknown timing is NOT counted as on-time.
   - Report missing delivery timing separately as a data-quality REVIEW.
   ============================================================ */
WITH delivery_counts AS (
    SELECT
        COUNT(*) AS total_orders,
        SUM(CASE WHEN is_delivered = 1 THEN 1 ELSE 0 END) AS delivered_orders,
        SUM(CASE WHEN is_delayed = 1 THEN 1 ELSE 0 END) AS delayed_orders,
        SUM(CASE WHEN is_delivered = 1 AND is_delayed = 0 THEN 1 ELSE 0 END)
            AS on_time_or_early_orders,
        SUM(CASE WHEN is_delayed = 1 AND ISNULL(is_delivered, 0) <> 1
                 THEN 1 ELSE 0 END) AS delayed_but_not_delivered_violations,
        SUM(CASE WHEN is_delivered = 1 AND is_delayed IS NULL
                 THEN 1 ELSE 0 END) AS delivered_with_unknown_delay_flag
    FROM analytics.fact_orders
)
SELECT
    total_orders,
    delivered_orders,
    delayed_orders,
    on_time_or_early_orders,
    delayed_but_not_delivered_violations,
    delivered_with_unknown_delay_flag,
    CASE
        WHEN delayed_but_not_delivered_violations = 0
         AND delivered_orders = on_time_or_early_orders
                              + delayed_orders
                              + delivered_with_unknown_delay_flag
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS delivery_logic_check,
    CASE
        WHEN delivered_with_unknown_delay_flag = 0 THEN 'PASS'
        ELSE 'REVIEW'
    END AS delivery_timing_completeness_check
FROM delivery_counts;
GO

/* ============================================================
   6. Delivery Status Group Mapping
   Validate the derived text label against is_delayed.
   ============================================================ */
SELECT
    COUNT(*) AS total_orders,
    SUM(
        CASE
            WHEN is_delayed = 1
             AND delivery_status_group <> 'Delayed'
            THEN 1
            WHEN is_delayed = 0
             AND delivery_status_group <> 'On Time or Early'
            THEN 1
            WHEN is_delayed IS NULL
             AND delivery_status_group <> 'Not Delivered / Unknown'
            THEN 1
            ELSE 0
        END
    ) AS mapping_mismatch_rows,
    CASE
        WHEN SUM(
            CASE
                WHEN is_delayed = 1
                 AND delivery_status_group <> 'Delayed'
                THEN 1
                WHEN is_delayed = 0
                 AND delivery_status_group <> 'On Time or Early'
                THEN 1
                WHEN is_delayed IS NULL
                 AND delivery_status_group <> 'Not Delivered / Unknown'
                THEN 1
                ELSE 0
            END
        ) = 0
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS delivery_status_group_check
FROM analytics.fact_orders;
GO

/* ============================================================
   7. Date-Dimension Coverage and Continuity
   dim_date should span exactly from the minimum to maximum
   non-null clean.orders.order_purchase_date with one row per day.
   ============================================================ */
WITH source_dates AS (
    SELECT
        MIN(order_purchase_date) AS source_min_date,
        MAX(order_purchase_date) AS source_max_date
    FROM clean.orders
    WHERE order_purchase_date IS NOT NULL
),
dim_stats AS (
    SELECT
        MIN(date_value) AS dim_min_date,
        MAX(date_value) AS dim_max_date,
        COUNT(*) AS dim_rows,
        COUNT(DISTINCT date_value) AS distinct_dim_dates
    FROM analytics.dim_date
)
SELECT
    s.source_min_date,
    s.source_max_date,
    d.dim_min_date,
    d.dim_max_date,
    d.dim_rows,
    d.distinct_dim_dates,
    DATEDIFF(DAY, s.source_min_date, s.source_max_date) + 1 AS expected_calendar_days,
    CASE
        WHEN d.dim_min_date = s.source_min_date
         AND d.dim_max_date = s.source_max_date
         AND d.dim_rows = d.distinct_dim_dates
         AND d.dim_rows = DATEDIFF(DAY, s.source_min_date, s.source_max_date) + 1
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS dim_date_coverage_check
FROM source_dates AS s
CROSS JOIN dim_stats AS d;
GO

/* ============================================================
   8. Customer-Key Coverage
   Orders should retain their customer_id in the analytics view.
   ============================================================ */
SELECT
    COUNT(*) AS fact_orders_rows,
    SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) AS null_customer_id_rows,
    CASE
        WHEN SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) = 0
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS customer_id_check
FROM analytics.fact_orders;
GO

/* ============================================================
   9. Product and Seller Key Coverage in fact_sales
   ============================================================ */
SELECT
    COUNT(*) AS fact_sales_rows,
    SUM(CASE WHEN product_id IS NULL THEN 1 ELSE 0 END) AS null_product_id_rows,
    SUM(CASE WHEN seller_id IS NULL THEN 1 ELSE 0 END) AS null_seller_id_rows,
    CASE
        WHEN SUM(CASE WHEN product_id IS NULL THEN 1 ELSE 0 END) = 0
         AND SUM(CASE WHEN seller_id IS NULL THEN 1 ELSE 0 END) = 0
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS product_seller_key_check
FROM analytics.fact_sales;
GO

/* ============================================================
   10. Review-Score Range Check
   Olist review scores should remain within the observed 1-5 scale
   whenever a score is present.
   ============================================================ */
SELECT
    COUNT(*) AS orders_with_review_score,
    MIN(avg_review_score) AS minimum_review_score,
    MAX(avg_review_score) AS maximum_review_score,
    SUM(
        CASE
            WHEN avg_review_score IS NOT NULL
             AND (avg_review_score < 1 OR avg_review_score > 5)
            THEN 1
            ELSE 0
        END
    ) AS out_of_range_rows,
    CASE
        WHEN SUM(
            CASE
                WHEN avg_review_score IS NOT NULL
                 AND (avg_review_score < 1 OR avg_review_score > 5)
                THEN 1
                ELSE 0
            END
        ) = 0
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS review_score_range_check
FROM analytics.fact_orders
WHERE avg_review_score IS NOT NULL;
GO

/* ============================================================
   11. Regional Qualification Rule
   Dashboard rule: only states with 500+ delivered orders qualify
   for the delay-rate ranking.
   ============================================================ */
WITH state_metrics AS (
    SELECT
        customer_state,
        COUNT(DISTINCT CASE WHEN is_delivered = 1 THEN order_id END) AS delivered_orders,
        COUNT(DISTINCT CASE WHEN is_delayed = 1 THEN order_id END) AS delayed_orders
    FROM analytics.fact_orders
    WHERE customer_state IS NOT NULL
    GROUP BY customer_state
)
SELECT
    customer_state,
    delivered_orders,
    delayed_orders,
    CAST(
        100.0 * delayed_orders / NULLIF(delivered_orders, 0)
        AS decimal(10,2)
    ) AS delay_rate_pct,
    CASE
        WHEN delivered_orders >= 500 THEN 'QUALIFIED'
        ELSE 'EXCLUDED'
    END AS ranking_eligibility
FROM state_metrics
ORDER BY
    CASE WHEN delivered_orders >= 500 THEN 0 ELSE 1 END,
    delivered_orders DESC,
    customer_state;
GO

/* ============================================================
   12. Seller-Risk Rule Validation
   Qualified seller = 100+ delivered orders.
   High risk = qualified seller AND delay rate >= 15%.
   ============================================================ */
WITH seller_metrics AS (
    SELECT
        seller_id,
        COUNT(DISTINCT CASE WHEN is_delivered = 1 THEN order_id END) AS delivered_orders,
        COUNT(DISTINCT CASE WHEN is_delayed = 1 THEN order_id END) AS delayed_orders
    FROM analytics.fact_sales
    WHERE seller_id IS NOT NULL
    GROUP BY seller_id
),
seller_rates AS (
    SELECT
        seller_id,
        delivered_orders,
        delayed_orders,
        CAST(
            1.0 * delayed_orders / NULLIF(delivered_orders, 0)
            AS decimal(18,8)
        ) AS delay_rate
    FROM seller_metrics
)
SELECT
    COUNT(*) AS total_sellers,
    SUM(CASE WHEN delayed_orders > 0 THEN 1 ELSE 0 END) AS sellers_with_delays,
    SUM(CASE WHEN delivered_orders >= 100 THEN 1 ELSE 0 END) AS qualified_sellers,
    SUM(
        CASE
            WHEN delivered_orders >= 100
             AND delay_rate >= 0.15
            THEN 1
            ELSE 0
        END
    ) AS high_risk_sellers,
    CAST(
        100.0 * AVG(
            CASE
                WHEN delivered_orders >= 100 THEN delay_rate
            END
        )
        AS decimal(10,2)
    ) AS avg_qualified_seller_delay_rate_pct
FROM seller_rates;
GO

/* ============================================================
   13. Financial-Match Flag Consistency
   Recompute the same <= 0.01 tolerance used by fact_orders.
   ============================================================ */
SELECT
    COUNT(*) AS orders_checked,
    SUM(
        CASE
            WHEN is_financially_matched <>
                 CASE
                     WHEN ABS(
                         ISNULL(payment_total_value, 0)
                         - ISNULL(order_total_value, 0)
                     ) <= 0.01
                     THEN 1
                     ELSE 0
                 END
            THEN 1
            ELSE 0
        END
    ) AS flag_mismatch_rows,
    CASE
        WHEN SUM(
            CASE
                WHEN is_financially_matched <>
                     CASE
                         WHEN ABS(
                             ISNULL(payment_total_value, 0)
                             - ISNULL(order_total_value, 0)
                         ) <= 0.01
                         THEN 1
                         ELSE 0
                     END
                THEN 1
                ELSE 0
            END
        ) = 0
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS financial_match_flag_check
FROM analytics.fact_orders;
GO

/* ============================================================
   14. Compact Validation Summary
   One-row overview of the most important structural checks.
   ============================================================ */
WITH
order_counts AS (
    SELECT
        (SELECT COUNT(*) FROM clean.orders) AS clean_rows,
        (SELECT COUNT(*) FROM analytics.fact_orders) AS fact_rows
),
sales_counts AS (
    SELECT
        (SELECT COUNT(*) FROM clean.order_items) AS clean_rows,
        (SELECT COUNT(*) FROM analytics.fact_sales) AS fact_rows
),
order_grain AS (
    SELECT
        COUNT(*) AS row_count,
        COUNT(DISTINCT order_id) AS distinct_count
    FROM analytics.fact_orders
),
sales_grain AS (
    SELECT
        COUNT(*) AS duplicate_key_groups
    FROM (
        SELECT
            order_id,
            order_item_id
        FROM analytics.fact_sales
        GROUP BY
            order_id,
            order_item_id
        HAVING COUNT(*) > 1
    ) AS d
),
sales_totals AS (
    SELECT
        (SELECT SUM(order_total_value) FROM analytics.fact_orders) AS order_total,
        (SELECT SUM(item_total_value) FROM analytics.fact_sales) AS item_total
)
SELECT
    CASE
        WHEN oc.clean_rows = oc.fact_rows THEN 'PASS'
        ELSE 'REVIEW'
    END AS orders_row_count,
    CASE
        WHEN sc.clean_rows = sc.fact_rows THEN 'PASS'
        ELSE 'REVIEW'
    END AS sales_row_count,
    CASE
        WHEN og.row_count = og.distinct_count THEN 'PASS'
        ELSE 'REVIEW'
    END AS fact_orders_grain,
    CASE
        WHEN sg.duplicate_key_groups = 0 THEN 'PASS'
        ELSE 'REVIEW'
    END AS fact_sales_grain,
    CASE
        WHEN ABS(
            CAST(st.item_total AS decimal(38,2))
            - CAST(st.order_total AS decimal(38,2))
        ) <= 0.01
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS sales_total_reconciliation
FROM order_counts AS oc
CROSS JOIN sales_counts AS sc
CROSS JOIN order_grain AS og
CROSS JOIN sales_grain AS sg
CROSS JOIN sales_totals AS st;
GO
