#!/usr/bin/env python
"""Export vw_gift_analysis_dataset to CSV."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
import pyodbc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/gift_analysis_dataset.csv")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['DB_SERVER']};"
        f"DATABASE={os.environ['DB_NAME']};"
        f"UID={os.environ['DB_USER']};"
        f"PWD={os.environ['DB_PASSWORD']};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )
    sql = "SELECT * FROM vw_gift_analysis_dataset ORDER BY report_year, report_month, canonical_group"
    df = pd.read_sql(sql, conn)
    conn.close()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"Exported rows={len(df)} to {output}")


if __name__ == "__main__":
    main()
