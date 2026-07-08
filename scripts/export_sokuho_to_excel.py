"""
匯出 fact_sales 全資料 → 每年一個 CSV 檔案
輸出：outputs/sokuho_YYYY.csv
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from etl.loader import get_connection

load_dotenv()

COLUMN_RENAME = {
    "report_date":                 "報表日期",
    "store_code":                  "門市代碼",
    "store_name":                  "門市名稱",
    "store_short_name":            "門市簡稱",
    "store_type":                  "門市類型",
    "record_type":                 "記錄類型",
    "sales_result":                "銷售金額",
    "sales_budget_pct":            "預算達成率%",
    "sales_yoy_pct":               "銷售YoY%",
    "customer_count":              "客數",
    "customer_yoy_pct":            "客數YoY%",
    "unit_price":                  "客單價",
    "unit_price_yoy_pct":          "客單價YoY%",
    "transfer_amount":             "調撥金額",
    "sales_incl_result":           "含調撥銷售金額",
    "sales_incl_budget_pct":       "含調撥預算達成率%",
    "sales_incl_yoy_pct":          "含調撥YoY%",
    "source_file":                 "來源檔案",
}

SQL = """
SELECT
    fs.report_date,
    ds.store_code,
    ds.store_name,
    ds.store_short_name,
    ds.store_type,
    RTRIM(fs.record_type)         AS record_type,
    fs.sales_result,
    fs.sales_budget_pct,
    fs.sales_yoy_pct,
    fs.customer_count,
    fs.customer_yoy_pct,
    fs.unit_price,
    fs.unit_price_yoy_pct,
    fs.transfer_amount,
    fs.sales_incl_result,
    fs.sales_incl_budget_pct,
    fs.sales_incl_yoy_pct,
    fs.source_file
FROM fact_sales fs
JOIN dim_store  ds ON ds.store_id = fs.store_id
ORDER BY fs.report_date, ds.display_order, fs.record_type
"""


def main() -> None:
    conn = get_connection(
        os.environ["DB_SERVER"],
        os.environ["DB_NAME"],
        os.environ["DB_USER"],
        os.environ["DB_PASSWORD"],
    )
    print("Connected to DB. Querying fact_sales ...")
    df = pd.read_sql(SQL, conn)
    conn.close()

    print(f"Total rows: {len(df):,}")
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    df["year"] = pd.to_datetime(df["report_date"]).dt.year
    df.rename(columns=COLUMN_RENAME, inplace=True)

    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)

    export_cols = [c for c in COLUMN_RENAME.values() if c in df.columns]
    years = sorted(df["year"].unique())

    for yr in years:
        subset = df[df["year"] == yr][export_cols]
        out_path = out_dir / f"sokuho_{yr}.csv"
        subset.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  sokuho_{yr}.csv — {len(subset):,} rows → {out_path.resolve()}")

    print(f"\n匯出完成：共 {len(years)} 個檔案，存放於 {out_dir.resolve()}")


if __name__ == "__main__":
    main()
