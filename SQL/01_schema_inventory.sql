/*
Olist BI Portfolio
File: 01_schema_inventory.sql
Database: selected prepared Olist analytics database

Purpose:
Provide a read-only inventory of the SQL Server objects and columns used by the
Olist BI project across the raw, clean, and analytics schemas.

Safety:
- Read-only metadata queries only.
- No CREATE, ALTER, DROP, INSERT, UPDATE, DELETE, or TRUNCATE statements.
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
   1. Project Schemas
   ============================================================ */
SELECT
    s.name AS schema_name
FROM sys.schemas AS s
WHERE s.name IN ('raw', 'clean', 'analytics')
ORDER BY
    CASE s.name
        WHEN 'raw' THEN 1
        WHEN 'clean' THEN 2
        WHEN 'analytics' THEN 3
        ELSE 4
    END;
GO

/* ============================================================
   2. Tables and Views Inventory
   ============================================================ */
SELECT
    s.name AS schema_name,
    o.name AS object_name,
    o.type_desc AS object_type,
    o.create_date,
    o.modify_date
FROM sys.objects AS o
INNER JOIN sys.schemas AS s
    ON o.schema_id = s.schema_id
WHERE
    s.name IN ('raw', 'clean', 'analytics')
    AND o.type IN ('U', 'V')  -- U = user table, V = view
ORDER BY
    CASE s.name
        WHEN 'raw' THEN 1
        WHEN 'clean' THEN 2
        WHEN 'analytics' THEN 3
        ELSE 4
    END,
    o.type_desc,
    o.name;
GO

/* ============================================================
   3. Column-Level Schema Inventory
   ============================================================ */
SELECT
    c.TABLE_SCHEMA AS table_schema,
    c.TABLE_NAME AS table_name,
    c.ORDINAL_POSITION AS ordinal_position,
    c.COLUMN_NAME AS column_name,
    c.DATA_TYPE AS data_type,
    c.CHARACTER_MAXIMUM_LENGTH AS character_maximum_length,
    c.NUMERIC_PRECISION AS numeric_precision,
    c.NUMERIC_SCALE AS numeric_scale,
    c.IS_NULLABLE AS is_nullable
FROM INFORMATION_SCHEMA.COLUMNS AS c
WHERE c.TABLE_SCHEMA IN ('raw', 'clean', 'analytics')
ORDER BY
    CASE c.TABLE_SCHEMA
        WHEN 'raw' THEN 1
        WHEN 'clean' THEN 2
        WHEN 'analytics' THEN 3
        ELSE 4
    END,
    c.TABLE_NAME,
    c.ORDINAL_POSITION;
GO

/* ============================================================
   4. Column Counts by Object
   ============================================================ */
SELECT
    c.TABLE_SCHEMA AS table_schema,
    c.TABLE_NAME AS table_name,
    COUNT(*) AS column_count
FROM INFORMATION_SCHEMA.COLUMNS AS c
WHERE c.TABLE_SCHEMA IN ('raw', 'clean', 'analytics')
GROUP BY
    c.TABLE_SCHEMA,
    c.TABLE_NAME
ORDER BY
    CASE c.TABLE_SCHEMA
        WHEN 'raw' THEN 1
        WHEN 'clean' THEN 2
        WHEN 'analytics' THEN 3
        ELSE 4
    END,
    c.TABLE_NAME;
GO

/* ============================================================
   5. Primary Key Inventory
   ============================================================ */
SELECT
    s.name AS schema_name,
    t.name AS table_name,
    kc.name AS primary_key_name,
    c.name AS column_name,
    ic.key_ordinal
FROM sys.key_constraints AS kc
INNER JOIN sys.tables AS t
    ON kc.parent_object_id = t.object_id
INNER JOIN sys.schemas AS s
    ON t.schema_id = s.schema_id
INNER JOIN sys.index_columns AS ic
    ON kc.parent_object_id = ic.object_id
    AND kc.unique_index_id = ic.index_id
INNER JOIN sys.columns AS c
    ON ic.object_id = c.object_id
    AND ic.column_id = c.column_id
WHERE
    kc.type = 'PK'
    AND s.name IN ('raw', 'clean', 'analytics')
ORDER BY
    CASE s.name
        WHEN 'raw' THEN 1
        WHEN 'clean' THEN 2
        WHEN 'analytics' THEN 3
        ELSE 4
    END,
    t.name,
    ic.key_ordinal;
GO

/* ============================================================
   6. Foreign Key Inventory
   ============================================================ */
SELECT
    sch_parent.name AS parent_schema,
    tab_parent.name AS parent_table,
    col_parent.name AS parent_column,
    fk.name AS foreign_key_name,
    sch_ref.name AS referenced_schema,
    tab_ref.name AS referenced_table,
    col_ref.name AS referenced_column
FROM sys.foreign_keys AS fk
INNER JOIN sys.foreign_key_columns AS fkc
    ON fk.object_id = fkc.constraint_object_id
INNER JOIN sys.tables AS tab_parent
    ON fk.parent_object_id = tab_parent.object_id
INNER JOIN sys.schemas AS sch_parent
    ON tab_parent.schema_id = sch_parent.schema_id
INNER JOIN sys.columns AS col_parent
    ON fkc.parent_object_id = col_parent.object_id
    AND fkc.parent_column_id = col_parent.column_id
INNER JOIN sys.tables AS tab_ref
    ON fk.referenced_object_id = tab_ref.object_id
INNER JOIN sys.schemas AS sch_ref
    ON tab_ref.schema_id = sch_ref.schema_id
INNER JOIN sys.columns AS col_ref
    ON fkc.referenced_object_id = col_ref.object_id
    AND fkc.referenced_column_id = col_ref.column_id
WHERE
    sch_parent.name IN ('raw', 'clean', 'analytics')
    OR sch_ref.name IN ('raw', 'clean', 'analytics')
ORDER BY
    sch_parent.name,
    tab_parent.name,
    fk.name,
    fkc.constraint_column_id;
GO
