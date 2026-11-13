/*
Olist BI Portfolio
File: 02_analytics_views.sql
Database: selected prepared Olist analytics database

Purpose:
Recreate the final analytics views used by the Power BI model.

Source:
Definitions recovered directly from the current SQL Server database.

Notes:
- Business logic is unchanged from the recovered definitions.
- CREATE OR ALTER VIEW updates existing view definitions without dropping them
  on SQL Server 2016 SP1+ / SQL Server 2022.
- Each view is guarded in the same SQL batch as its execution.
- View definitions and business calculations are unchanged.
*/

/* Select the prepared Olist database in the SSMS database dropdown.
   Each view definition is guarded within its OWN batch. A THROW in a
   separate GO batch alone does not prevent SSMS from executing later batches.
   Execute the whole script in one prepared database; do not run only a
   selected portion of a view definition. */

/* ============================================================
   1. Date Dimension
   ============================================================ */
IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
   OR SCHEMA_ID(N'analytics') IS NULL
   OR OBJECT_ID(N'clean.orders') IS NULL
   OR OBJECT_ID(N'clean.order_items') IS NULL
   OR OBJECT_ID(N'clean.customers') IS NULL
   OR OBJECT_ID(N'clean.products') IS NULL
   OR OBJECT_ID(N'clean.sellers') IS NULL
   OR OBJECT_ID(N'clean.payments') IS NULL
   OR OBJECT_ID(N'clean.reviews_by_order') IS NULL
BEGIN
    THROW 50001,
          'Choose a prepared Olist database with analytics and clean objects before running this script.', 1;
END;
EXEC sys.sp_executesql N'CREATE OR ALTER VIEW analytics.dim_date
AS
WITH date_range AS (
    SELECT
        MIN(order_purchase_date) AS min_date,
        MAX(order_purchase_date) AS max_date
    FROM clean.orders
    WHERE order_purchase_date IS NOT NULL
),
numbers AS (
    SELECT TOP (
        SELECT DATEDIFF(DAY, min_date, max_date) + 1
        FROM date_range
    )
        ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS n
    FROM sys.objects AS a
    CROSS JOIN sys.objects AS b
),
dates AS (
    SELECT
        DATEADD(DAY, n, dr.min_date) AS date_value
    FROM numbers
    CROSS JOIN date_range AS dr
)
SELECT
    date_value,
    YEAR(date_value) AS year_number,
    MONTH(date_value) AS month_number,
    DATENAME(MONTH, date_value) AS month_name,
    CONCAT(
        YEAR(date_value),
        ''-'',
        RIGHT(''0'' + CAST(MONTH(date_value) AS varchar(2)), 2)
    ) AS year_month,
    DATEFROMPARTS(
        YEAR(date_value),
        MONTH(date_value),
        1
    ) AS month_start_date,
    DATEPART(QUARTER, date_value) AS quarter_number,
    CONCAT(''Q'', DATEPART(QUARTER, date_value)) AS quarter_name,
    DAY(date_value) AS day_number,
    DATENAME(WEEKDAY, date_value) AS day_name
FROM dates;';
GO

/* ============================================================
   2. Order-Level Fact View
   ============================================================ */
IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
   OR SCHEMA_ID(N'analytics') IS NULL
   OR OBJECT_ID(N'clean.orders') IS NULL
   OR OBJECT_ID(N'clean.order_items') IS NULL
   OR OBJECT_ID(N'clean.customers') IS NULL
   OR OBJECT_ID(N'clean.products') IS NULL
   OR OBJECT_ID(N'clean.sellers') IS NULL
   OR OBJECT_ID(N'clean.payments') IS NULL
   OR OBJECT_ID(N'clean.reviews_by_order') IS NULL
BEGIN
    THROW 50001,
          'Choose a prepared Olist database with analytics and clean objects before running this script.', 1;
END;
EXEC sys.sp_executesql N'CREATE OR ALTER VIEW analytics.fact_orders
AS
WITH order_items_summary AS (
    SELECT
        order_id,
        COUNT(*) AS order_item_count,
        COUNT(DISTINCT product_id) AS distinct_products_in_order,
        COUNT(DISTINCT seller_id) AS distinct_sellers_in_order,
        SUM(item_price) AS item_revenue,
        SUM(freight_value) AS freight_value,
        SUM(item_total_value) AS order_total_value
    FROM clean.order_items
    GROUP BY order_id
),
payments_summary AS (
    SELECT
        order_id,
        COUNT(*) AS payment_rows,
        COUNT(DISTINCT payment_type) AS distinct_payment_types,
        SUM(payment_value) AS payment_total_value,
        MAX(payment_installments) AS max_payment_installments,
        MAX(CASE WHEN payment_type = ''credit_card'' THEN 1 ELSE 0 END) AS used_credit_card,
        MAX(CASE WHEN payment_type = ''boleto'' THEN 1 ELSE 0 END) AS used_boleto,
        MAX(CASE WHEN payment_type = ''voucher'' THEN 1 ELSE 0 END) AS used_voucher,
        MAX(is_non_positive_payment) AS has_non_positive_payment
    FROM clean.payments
    GROUP BY order_id
)
SELECT
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_city,
    c.customer_state,

    o.order_status,
    o.order_purchase_date,
    o.order_year,
    o.order_month,

    o.is_delivered,
    o.is_canceled,
    o.is_delayed,
    o.delivery_days,
    o.estimated_delivery_days,
    o.days_after_estimate,
    o.delivered_missing_customer_date,

    oi.order_item_count,
    oi.distinct_products_in_order,
    oi.distinct_sellers_in_order,
    oi.item_revenue,
    oi.freight_value,
    oi.order_total_value,

    p.payment_rows,
    p.distinct_payment_types,
    p.payment_total_value,
    p.max_payment_installments,
    p.used_credit_card,
    p.used_boleto,
    p.used_voucher,
    p.has_non_positive_payment,

    r.review_count,
    r.avg_review_score,
    r.review_sentiment_group,
    r.is_low_review,
    r.has_comment_message,

    CASE
        WHEN o.is_delayed = 1 THEN ''Delayed''
        WHEN o.is_delayed = 0 THEN ''On Time or Early''
        ELSE ''Not Delivered / Unknown''
    END AS delivery_status_group,

    CASE
        WHEN ABS(
            ISNULL(p.payment_total_value, 0)
            - ISNULL(oi.order_total_value, 0)
        ) <= 0.01 THEN 1
        ELSE 0
    END AS is_financially_matched,

    ISNULL(p.payment_total_value, 0)
        - ISNULL(oi.order_total_value, 0)
        AS payment_vs_order_value_difference

FROM clean.orders AS o
LEFT JOIN clean.customers AS c
    ON o.customer_id = c.customer_id
LEFT JOIN order_items_summary AS oi
    ON o.order_id = oi.order_id
LEFT JOIN payments_summary AS p
    ON o.order_id = p.order_id
LEFT JOIN clean.reviews_by_order AS r
    ON o.order_id = r.order_id;';
GO

/* ============================================================
   3. Order-Item / Product / Seller Fact View
   ============================================================ */
IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
   OR SCHEMA_ID(N'analytics') IS NULL
   OR OBJECT_ID(N'clean.orders') IS NULL
   OR OBJECT_ID(N'clean.order_items') IS NULL
   OR OBJECT_ID(N'clean.customers') IS NULL
   OR OBJECT_ID(N'clean.products') IS NULL
   OR OBJECT_ID(N'clean.sellers') IS NULL
   OR OBJECT_ID(N'clean.payments') IS NULL
   OR OBJECT_ID(N'clean.reviews_by_order') IS NULL
BEGIN
    THROW 50001,
          'Choose a prepared Olist database with analytics and clean objects before running this script.', 1;
END;
EXEC sys.sp_executesql N'CREATE OR ALTER VIEW analytics.fact_sales
AS
SELECT
    oi.order_id,
    oi.order_item_id,

    o.customer_id,
    oi.product_id,
    oi.seller_id,

    o.order_status,
    o.order_purchase_date,
    o.order_year,
    o.order_month,

    c.customer_city,
    c.customer_state,

    s.seller_city,
    s.seller_state,

    p.product_category_name_en,
    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm,
    p.is_missing_category,
    p.is_zero_weight,

    oi.item_price,
    oi.freight_value,
    oi.item_total_value,

    o.is_delivered,
    o.is_canceled,
    o.is_delayed,
    o.delivery_days,
    o.estimated_delivery_days,
    o.days_after_estimate,

    r.avg_review_score,
    r.review_sentiment_group,
    r.is_low_review,
    r.has_comment_message,

    CASE
        WHEN o.is_delayed = 1 THEN ''Delayed''
        WHEN o.is_delayed = 0 THEN ''On Time or Early''
        ELSE ''Not Delivered / Unknown''
    END AS delivery_status_group

FROM clean.order_items AS oi
LEFT JOIN clean.orders AS o
    ON oi.order_id = o.order_id
LEFT JOIN clean.customers AS c
    ON o.customer_id = c.customer_id
LEFT JOIN clean.products AS p
    ON oi.product_id = p.product_id
LEFT JOIN clean.sellers AS s
    ON oi.seller_id = s.seller_id
LEFT JOIN clean.reviews_by_order AS r
    ON oi.order_id = r.order_id;';
GO
