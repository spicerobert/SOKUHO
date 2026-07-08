#!/usr/bin/env python
from __future__ import annotations

import os

import pyodbc
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['DB_SERVER']};"
        f"DATABASE={os.environ['DB_NAME']};"
        f"UID={os.environ['DB_USER']};"
        f"PWD={os.environ['DB_PASSWORD']};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )
    cur = conn.cursor()

    cur.execute(
        """
        SELECT report_month, COUNT(1)
        FROM fact_kouseihi_category
        WHERE report_year = 2026 AND period_type = 'MONTHLY'
        GROUP BY report_month
        ORDER BY report_month
        """
    )
    print("category_counts", cur.fetchall())

    cur.execute(
        """
        SELECT report_month, COUNT(1)
        FROM fact_kouseihi_kpi
        WHERE report_year = 2026 AND period_type = 'MONTHLY'
        GROUP BY report_month
        ORDER BY report_month
        """
    )
    print("kpi_counts", cur.fetchall())

    cur.execute(
        """
        SELECT report_month, category, sales_result, sales_yoy_pct
        FROM fact_kouseihi_category
        WHERE report_year = 2026 AND period_type = 'MONTHLY'
        ORDER BY report_month, category
        """
    )
    print("category_rows")
    for row in cur.fetchall():
        print(row)

    cur.execute(
        """
        SELECT report_month, customer_count, unit_price, avg_daily_sales
        FROM fact_kouseihi_kpi
        WHERE report_year = 2026 AND period_type = 'MONTHLY'
        ORDER BY report_month
        """
    )
    print("kpi_rows")
    for row in cur.fetchall():
        print(row)

    cur.execute(
        """
        SELECT TOP 5 source_file, report_year, category_rows, kpi_rows, status, run_at
        FROM etl_kouseihi_log
        ORDER BY log_id DESC
        """
    )
    print("etl_log_latest")
    for row in cur.fetchall():
        print(row)

    conn.close()


if __name__ == "__main__":
    main()
