#!/usr/bin/env python
"""
Export KOUSEIHI data to CSV files, one pair per year.

Outputs
-------
outputs/kouseihi_category_YYYY.csv  -- fact_kouseihi_category rows for that year
outputs/kouseihi_kpi_YYYY.csv       -- fact_kouseihi_kpi rows for that year
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pyodbc
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _connect() -> pyodbc.Connection:
    load_dotenv()
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['DB_SERVER']};"
        f"DATABASE={os.environ['DB_NAME']};"
        f"UID={os.environ['DB_USER']};"
        f"PWD={os.environ['DB_PASSWORD']};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

SQL_YEARS = "SELECT DISTINCT report_year FROM fact_kouseihi_category ORDER BY report_year"

SQL_CATEGORY = """
SELECT
    report_year,
    report_month,
    period_type,
    category,
    sales_result,
    sales_yoy_pct,
    composition_curr_pct,
    composition_prev_pct,
    loaded_at
FROM fact_kouseihi_category
WHERE report_year = ?
ORDER BY period_type, report_month, category
"""

SQL_KPI = """
SELECT
    report_year,
    report_month,
    period_type,
    customer_count,
    customer_yoy_pct,
    unit_price,
    unit_price_yoy_pct,
    turnover_curr,
    turnover_prev,
    day_in_month_curr,
    day_in_month_prev,
    avg_daily_sales,
    avg_daily_sales_yoy_pct,
    loaded_at
FROM fact_kouseihi_kpi
WHERE report_year = ?
ORDER BY period_type, report_month
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)

    conn = _connect()
    print("Connected to database.")

    years: list[int] = [row[0] for row in conn.execute(SQL_YEARS).fetchall()]
    if not years:
        print("No KOUSEIHI data found in fact_kouseihi_category.")
        conn.close()
        return

    print(f"Found years: {years}")

    for year in years:
        # --- category ---
        cur = conn.cursor()
        cur.execute(SQL_CATEGORY, (year,))
        cols_cat = [d[0] for d in cur.description]
        df_cat = pd.DataFrame.from_records(cur.fetchall(), columns=cols_cat)
        cat_path = out_dir / f"kouseihi_category_{year}.csv"
        df_cat.to_csv(cat_path, index=False, encoding="utf-8-sig")
        print(f"  [{year}] category -> {cat_path}  ({len(df_cat)} rows)")

        # --- kpi ---
        cur.execute(SQL_KPI, (year,))
        cols_kpi = [d[0] for d in cur.description]
        df_kpi = pd.DataFrame.from_records(cur.fetchall(), columns=cols_kpi)
        kpi_path = out_dir / f"kouseihi_kpi_{year}.csv"
        df_kpi.to_csv(kpi_path, index=False, encoding="utf-8-sig")
        print(f"  [{year}] kpi     -> {kpi_path}  ({len(df_kpi)} rows)")

    conn.close()
    print("\nDone. All files written to outputs/")


if __name__ == "__main__":
    main()
