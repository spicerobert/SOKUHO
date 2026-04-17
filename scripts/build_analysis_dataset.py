#!/usr/bin/env python
"""
Export vw_analysis_monthly to CSV.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
import pyodbc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export vw_analysis_monthly to CSV")
    parser.add_argument(
        "--output",
        default="data/analysis_dataset.csv",
        help="Output CSV path",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['DB_SERVER']};"
        f"DATABASE={os.environ['DB_NAME']};"
        f"UID={os.environ['DB_USER']};"
        f"PWD={os.environ['DB_PASSWORD']};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )
    sql = "SELECT * FROM vw_analysis_monthly ORDER BY report_year, report_month"
    df = pd.read_sql(sql, conn)
    conn.close()

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Exported rows={len(df)} to {output_path}")


if __name__ == "__main__":
    main()
