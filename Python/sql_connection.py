"""Shared read-only SQL Server connection for the Olist analysis scripts.

No local database name or credentials are stored in this repository.
Set OLIST_SQL_DATABASE when more than one suitable database is accessible.
"""

from __future__ import annotations

import os
import pyodbc

SERVER = os.getenv("OLIST_SQL_SERVER", r"localhost\SQLEXPRESS")
DRIVER = os.getenv("OLIST_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")


def _open(database: str, timeout: int) -> pyodbc.Connection:
    """Connect with Windows authentication and a read-only application intent."""
    if not database or any(character in database for character in ";{}"):
        raise ValueError("Invalid SQL database name.")
    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};DATABASE={{{database}}};"
        "Trusted_Connection=yes;ApplicationIntent=ReadOnly;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(connection_string, timeout=timeout)


def _has_analytics_views(connection: pyodbc.Connection) -> bool:
    row = connection.cursor().execute(
        "SELECT OBJECT_ID(N'analytics.fact_orders', N'V'), "
        "OBJECT_ID(N'analytics.fact_sales', N'V')"
    ).fetchone()
    return row is not None and row[0] is not None and row[1] is not None


def connect_analytics(timeout: int = 10) -> tuple[pyodbc.Connection, str]:
    """Connect to a configured DB, or auto-detect exactly one matching Olist DB.

    Selection deliberately fails when multiple databases qualify, avoiding
    silently analysing the wrong data. No tables are modified by this helper.
    """
    configured = os.getenv("OLIST_SQL_DATABASE", "").strip()
    if configured:
        connection = _open(configured, timeout)
        if not _has_analytics_views(connection):
            connection.close()
            raise RuntimeError(
                "The selected database does not contain both required "
                "analytics views. Verify OLIST_SQL_DATABASE."
            )
        return connection, configured

    master = _open("master", timeout)
    try:
        rows = master.cursor().execute(
            "SELECT name FROM sys.databases "
            "WHERE name LIKE N'Olist%' AND state = 0 "
            "AND HAS_DBACCESS(name) = 1 ORDER BY name"
        ).fetchall()
    finally:
        master.close()
    matches: list[tuple[pyodbc.Connection, str]] = []
    for row in rows:
        name = str(row[0])
        try:
            connection = _open(name, timeout)
        except pyodbc.Error:
            continue
        try:
            if _has_analytics_views(connection):
                matches.append((connection, name))
            else:
                connection.close()
        except pyodbc.Error:
            connection.close()
            continue
    if len(matches) == 1:
        return matches[0]
    for connection, _ in matches:
        connection.close()
    if matches:
        raise RuntimeError(
            "Multiple databases contain the Olist analytical views. "
            "Set OLIST_SQL_DATABASE to choose one explicitly."
        )
    raise RuntimeError(
        "No accessible Olist database contains the required analytical views. "
        "Start SQL Server and check its database or set OLIST_SQL_DATABASE."
    )
