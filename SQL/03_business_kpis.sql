/*
Olist BI Portfolio
File: 03_business_kpis.sql
Database: selected prepared Olist analytics database

Purpose:
Reproduce the core business KPIs and analytical rules used in the Power BI
dashboard directly from the final analytics views.

Safety:
- Read-only SELECT queries only.
- No data or schema changes.

Business rules represented here:
- On-time / early orders are delivered orders with is_delayed = 0.
- Delivered orders with is_delayed IS NULL remain unknown and are not counted
  as on-time / early or delayed.
- Low-review rate uses all orders in each delivery-status group as denominator.
- Regional delay-rate ranking includes only states with 500+ delivered orders.
- Qualified seller = seller with 100+ delivered orders.
- High-risk seller = qualified seller with delay rate >= 15%.
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
   1. Executive Summary KPIs
   ============================================================ */
WITH executive_kpis AS (
    SELECT
        SUM(order_total_value) AS order_value,
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
        AVG(CAST(avg_review_score AS decimal(18,6))) AS average_review_score
    FROM analytics.fact_orders
)
SELECT
    order_value,
    total_orders,
    delivered_orders,
    on_time_orders,
    delayed_orders,
    CAST(
        100.0 * delayed_orders / NULLIF(delivered_orders, 0)
        AS decimal(10,2)
    ) AS delay_rate_pct,
    CAST(average_review_score AS decimal(10,2)) AS average_review_score
FROM executive_kpis;
GO

/* ============================================================
   2. Sales & Category Performance KPIs
   ============================================================ */
WITH order_summary AS (
    SELECT
        SUM(order_total_value) AS total_sales,
        COUNT(DISTINCT order_id) AS total_orders
    FROM analytics.fact_orders
),
sales_summary AS (
    SELECT
        COUNT(*) AS items_sold,
        COUNT(DISTINCT product_id) AS distinct_products,
        SUM(item_price) AS product_revenue,
        SUM(freight_value) AS total_freight,
        SUM(item_total_value) AS sales_value_from_items
    FROM analytics.fact_sales
)
SELECT
    s.sales_value_from_items AS total_sales,
    s.product_revenue,
    s.total_freight,
    s.items_sold,
    s.distinct_products,
    CAST(
        o.total_sales / NULLIF(CAST(o.total_orders AS decimal(18,6)), 0)
        AS decimal(18,2)
    ) AS average_order_value
FROM sales_summary AS s
CROSS JOIN order_summary AS o;
GO

/* Top product categories by product revenue (excluding freight). */
SELECT TOP (10)
    product_category_name_en,
    COUNT(*) AS items_sold,
    COUNT(DISTINCT order_id) AS orders,
    SUM(item_price) AS product_revenue,
    SUM(freight_value) AS freight_value,
    SUM(item_total_value) AS total_value
FROM analytics.fact_sales
WHERE product_category_name_en IS NOT NULL
GROUP BY product_category_name_en
ORDER BY product_revenue DESC, product_category_name_en;
GO

/* ============================================================
   3. Delivery & Customer Satisfaction
   Low-review rate uses all orders in each delivery-status group
   as the denominator, matching the Power BI business definition.
   ============================================================ */
SELECT
    delivery_status_group,
    COUNT(DISTINCT order_id) AS orders,
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
GROUP BY delivery_status_group
ORDER BY
    CASE delivery_status_group
        WHEN 'On Time or Early' THEN 1
        WHEN 'Delayed' THEN 2
        WHEN 'Not Delivered / Unknown' THEN 3
        ELSE 4
    END,
    delivery_status_group;
GO

/* ============================================================
   4. Regional Performance
   Rule: include only states with 500+ delivered orders.
   Ranking uses the unrounded delay rate.
   ============================================================ */
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
),
qualified_states AS (
    SELECT
        customer_state,
        delivered_orders,
        delayed_orders,
        CAST(
            1.0 * delayed_orders / NULLIF(delivered_orders, 0)
            AS decimal(18,8)
        ) AS delay_rate
    FROM state_metrics
    WHERE delivered_orders >= 500
)
SELECT
    customer_state,
    delivered_orders,
    delayed_orders,
    CAST(100.0 * delay_rate AS decimal(10,2)) AS delay_rate_pct,
    DENSE_RANK() OVER (
        ORDER BY delay_rate DESC
    ) AS delay_rate_rank
FROM qualified_states
ORDER BY delay_rate_rank, customer_state;
GO

/* Regional sales value by customer state. */
SELECT
    customer_state,
    COUNT(DISTINCT order_id) AS orders,
    SUM(item_price) AS product_revenue,
    SUM(freight_value) AS freight_value,
    SUM(item_total_value) AS total_sales
FROM analytics.fact_sales
WHERE customer_state IS NOT NULL
GROUP BY customer_state
ORDER BY total_sales DESC, customer_state;
GO

/* ============================================================
   5. Seller Risk Analysis
   Qualified seller = 100+ delivered orders.
   High risk = qualified seller with delay rate >= 15%.
   Ranking and threshold logic use the unrounded delay rate.
   ============================================================ */
WITH seller_metrics AS (
    SELECT
        seller_id,
        seller_city,
        seller_state,
        COUNT(DISTINCT CASE
            WHEN is_delivered = 1 THEN order_id
        END) AS delivered_orders,
        COUNT(DISTINCT CASE
            WHEN is_delayed = 1 THEN order_id
        END) AS delayed_orders
    FROM analytics.fact_sales
    WHERE seller_id IS NOT NULL
    GROUP BY
        seller_id,
        seller_city,
        seller_state
),
seller_rates AS (
    SELECT
        seller_id,
        seller_city,
        seller_state,
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
            THEN 1 ELSE 0
        END
    ) AS high_risk_sellers,
    CAST(
        100.0 * AVG(
            CASE
                WHEN delivered_orders >= 100
                THEN delay_rate
            END
        )
        AS decimal(10,2)
    ) AS avg_qualified_seller_delay_rate_pct
FROM seller_rates;
GO

/* Ranked qualified sellers by delay rate. */
WITH seller_metrics AS (
    SELECT
        seller_id,
        seller_city,
        seller_state,
        COUNT(DISTINCT CASE
            WHEN is_delivered = 1 THEN order_id
        END) AS delivered_orders,
        COUNT(DISTINCT CASE
            WHEN is_delayed = 1 THEN order_id
        END) AS delayed_orders
    FROM analytics.fact_sales
    WHERE seller_id IS NOT NULL
    GROUP BY
        seller_id,
        seller_city,
        seller_state
),
qualified_sellers AS (
    SELECT
        seller_id,
        seller_city,
        seller_state,
        delivered_orders,
        delayed_orders,
        CAST(
            1.0 * delayed_orders / NULLIF(delivered_orders, 0)
            AS decimal(18,8)
        ) AS delay_rate
    FROM seller_metrics
    WHERE delivered_orders >= 100
)
SELECT
    seller_id,
    LEFT(seller_id, 8)
        + ' | '
        + ISNULL(seller_city, '')
        + CASE
            WHEN seller_state IS NOT NULL
            THEN ', ' + seller_state
            ELSE ''
          END AS seller_label,
    seller_city,
    seller_state,
    delivered_orders,
    delayed_orders,
    CAST(100.0 * delay_rate AS decimal(10,2)) AS delay_rate_pct,
    CASE
        WHEN delay_rate >= 0.15 THEN 1
        ELSE 0
    END AS is_high_risk,
    DENSE_RANK() OVER (
        ORDER BY delay_rate DESC
    ) AS seller_delay_rate_rank
FROM qualified_sellers
ORDER BY seller_delay_rate_rank, seller_id;
GO
