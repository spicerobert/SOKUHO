#!/usr/bin/env python
"""Load macro indicators from data/macro_raw/*.csv into SQL Server."""

from __future__ import annotations

import argparse
import calendar
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
import pyodbc

MERGE_SQL = """
MERGE dim_macro_indicators AS tgt
USING (
    SELECT
        CAST(? AS SMALLINT) AS report_year,
        CAST(? AS TINYINT) AS report_month,
        CAST(? AS DECIMAL(18,2)) AS dept_store_sales,
        CAST(? AS DECIMAL(8,2)) AS retail_food_index,
        CAST(? AS DECIMAL(8,2)) AS cci_index,
        CAST(? AS DECIMAL(6,2)) AS cpi_yoy_pct,
        CAST(? AS DECIMAL(6,2)) AS cpi_food_yoy_pct,
        CAST(? AS DECIMAL(6,2)) AS avg_wage_yoy_pct,
        CAST(? AS DECIMAL(8,4)) AS twd_jpy_rate,
        CAST(? AS DECIMAL(8,4)) AS twd_usd_rate,
        CAST(? AS DECIMAL(5,2)) AS unemployment_rate,
        CAST(? AS INT) AS inbound_tourists,
        CAST(? AS DECIMAL(8,2)) AS bsi_index,
        CAST(? AS BIT) AS has_lunar_new_year,
        CAST(? AS TINYINT) AS lunar_new_year_day,
        CAST(? AS BIT) AS has_mid_autumn,
        CAST(? AS TINYINT) AS mid_autumn_day,
        CAST(? AS TINYINT) AS working_days,
        CAST(? AS TINYINT) AS calendar_days,
        CAST(? AS TINYINT) AS weekend_days,
        CAST(? AS DECIMAL(6,2)) AS gdp_yoy_pct,
        CAST(? AS DECIMAL(6,2)) AS private_consumption_real_yoy_pct,
        CAST(? AS DECIMAL(6,2)) AS department_store_yoy_pct,
        CAST(? AS DECIMAL(6,2)) AS retail_trade_yoy_pct,
        CAST(? AS DECIMAL(8,2)) AS gift_market_sentiment_index,
        CAST(? AS DECIMAL(8,2)) AS stock_wealth_effect_index,
        CAST(? AS NVARCHAR(200)) AS data_source
) AS src
ON tgt.report_year = src.report_year
AND tgt.report_month = src.report_month
WHEN MATCHED THEN
    UPDATE SET
        dept_store_sales = src.dept_store_sales,
        retail_food_index = src.retail_food_index,
        cci_index = src.cci_index,
        cpi_yoy_pct = src.cpi_yoy_pct,
        cpi_food_yoy_pct = src.cpi_food_yoy_pct,
        avg_wage_yoy_pct = src.avg_wage_yoy_pct,
        twd_jpy_rate = src.twd_jpy_rate,
        twd_usd_rate = src.twd_usd_rate,
        unemployment_rate = src.unemployment_rate,
        inbound_tourists = src.inbound_tourists,
        bsi_index = src.bsi_index,
        has_lunar_new_year = src.has_lunar_new_year,
        lunar_new_year_day = src.lunar_new_year_day,
        has_mid_autumn = src.has_mid_autumn,
        mid_autumn_day = src.mid_autumn_day,
        working_days = src.working_days,
        calendar_days = src.calendar_days,
        weekend_days = src.weekend_days,
        gdp_yoy_pct = src.gdp_yoy_pct,
        private_consumption_real_yoy_pct = src.private_consumption_real_yoy_pct,
        department_store_yoy_pct = src.department_store_yoy_pct,
        retail_trade_yoy_pct = src.retail_trade_yoy_pct,
        gift_market_sentiment_index = src.gift_market_sentiment_index,
        stock_wealth_effect_index = src.stock_wealth_effect_index,
        data_source = src.data_source,
        updated_at = GETDATE()
WHEN NOT MATCHED THEN
    INSERT (
        report_year, report_month,
        dept_store_sales, retail_food_index, cci_index, cpi_yoy_pct,
        cpi_food_yoy_pct, avg_wage_yoy_pct, twd_jpy_rate, twd_usd_rate, unemployment_rate, inbound_tourists, bsi_index,
        has_lunar_new_year, lunar_new_year_day, has_mid_autumn, mid_autumn_day, working_days, calendar_days, weekend_days,
        gdp_yoy_pct, private_consumption_real_yoy_pct, department_store_yoy_pct, retail_trade_yoy_pct,
        gift_market_sentiment_index, stock_wealth_effect_index,
        data_source
    )
    VALUES (
        src.report_year, src.report_month,
        src.dept_store_sales, src.retail_food_index, src.cci_index, src.cpi_yoy_pct,
        src.cpi_food_yoy_pct, src.avg_wage_yoy_pct, src.twd_jpy_rate, src.twd_usd_rate, src.unemployment_rate, src.inbound_tourists, src.bsi_index,
        src.has_lunar_new_year, src.lunar_new_year_day, src.has_mid_autumn, src.mid_autumn_day, src.working_days, src.calendar_days, src.weekend_days,
        src.gdp_yoy_pct, src.private_consumption_real_yoy_pct, src.department_store_yoy_pct, src.retail_trade_yoy_pct,
        src.gift_market_sentiment_index, src.stock_wealth_effect_index,
        src.data_source
    );
"""

CSV_COLUMNS = [
    "report_year", "report_month",
    "dept_store_sales", "retail_food_index", "cci_index", "cpi_yoy_pct",
    "cpi_food_yoy_pct", "avg_wage_yoy_pct", "twd_jpy_rate", "twd_usd_rate",
    "unemployment_rate", "inbound_tourists", "bsi_index",
    "has_lunar_new_year", "lunar_new_year_day", "has_mid_autumn", "mid_autumn_day",
    "working_days", "calendar_days", "weekend_days",
    "gdp_yoy_pct", "private_consumption_real_yoy_pct", "department_store_yoy_pct", "retail_trade_yoy_pct",
    "gift_market_sentiment_index", "stock_wealth_effect_index",
    "data_source",
]

FILE_COLUMN_MAP = {
    "dept_store_sales.csv": "dept_store_sales",
    "retail_food_index.csv": "retail_food_index",
    "cci.csv": "cci_index",
    "cpi_total.csv": "cpi_yoy_pct",
    "cpi_food.csv": "cpi_food_yoy_pct",
    "avg_wage_yoy.csv": "avg_wage_yoy_pct",
    "unemployment.csv": "unemployment_rate",
    "twd_jpy.csv": "twd_jpy_rate",
    "twd_usd.csv": "twd_usd_rate",
    "inbound_tourists.csv": "inbound_tourists",
    "bsi.csv": "bsi_index",
    "gdp_yoy.csv": "gdp_yoy_pct",
    "private_consumption_real_yoy.csv": "private_consumption_real_yoy_pct",
    "department_store_yoy.csv": "department_store_yoy_pct",
    "retail_trade_yoy.csv": "retail_trade_yoy_pct",
    "gift_market_sentiment.csv": "gift_market_sentiment_index",
    "stock_wealth_effect.csv": "stock_wealth_effect_index",
    "lunar_calendar.csv": "lunar_calendar",
    "working_days.csv": "working_days_pack",
}


def _to_py(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load macro indicators CSV directory into SQL Server")
    parser.add_argument("--raw-dir", default="data/macro_raw", help="Directory containing macro raw CSV files")
    return parser.parse_args()


def _base_frame() -> pd.DataFrame:
    return pd.MultiIndex.from_product([range(2021, 2026), range(1, 13)], names=["report_year", "report_month"]).to_frame(index=False)


def _apply_calendar_payload(df: pd.DataFrame) -> pd.DataFrame:
    if "lunar_calendar" in df.columns:
        series = df["lunar_calendar"].fillna("").astype(str)
        df["has_lunar_new_year"] = series.str.contains("LNY").astype(int)
        df["lunar_new_year_day"] = series.str.extract(r"LNY:(\d+)")[0]
        df["has_mid_autumn"] = series.str.contains("MA").astype(int)
        df["mid_autumn_day"] = series.str.extract(r"MA:(\d+)")[0]
    else:
        df["has_lunar_new_year"] = 0
        df["lunar_new_year_day"] = None
        df["has_mid_autumn"] = 0
        df["mid_autumn_day"] = None

    if "working_days_pack" in df.columns:
        pack = df["working_days_pack"].fillna("").astype(str)
        df["working_days"] = pack.str.extract(r"WD:(\d+)")[0]
        df["calendar_days"] = pack.str.extract(r"CD:(\d+)")[0]
    else:
        df["calendar_days"] = [calendar.monthrange(int(y), int(m))[1] for y, m in zip(df["report_year"], df["report_month"])]
        df["working_days"] = (df["calendar_days"] * 5 // 7).astype(int)
    return df


def build_macro_frame(raw_dir: Path) -> pd.DataFrame:
    df = _base_frame()
    for file_name, key in FILE_COLUMN_MAP.items():
        csv_path = raw_dir / file_name
        if not csv_path.exists():
            continue
        part = pd.read_csv(csv_path)
        part.columns = [c.strip().lower() for c in part.columns]
        if not {"year", "month", "value"} <= set(part.columns):
            continue
        part = part.rename(columns={"year": "report_year", "month": "report_month", "value": key})
        df = df.merge(part[["report_year", "report_month", key]], on=["report_year", "report_month"], how="left")

    df = _apply_calendar_payload(df)
    df["weekend_days"] = pd.to_numeric(df["calendar_days"], errors="coerce").fillna(0) - pd.to_numeric(df["working_days"], errors="coerce").fillna(0)
    df["data_source"] = "macro_raw_compiled_v2"

    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[CSV_COLUMNS]


def main() -> None:
    load_dotenv()
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw directory not found: {raw_dir}")
    df = build_macro_frame(raw_dir)

    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['DB_SERVER']};"
        f"DATABASE={os.environ['DB_NAME']};"
        f"UID={os.environ['DB_USER']};"
        f"PWD={os.environ['DB_PASSWORD']};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )
    inserted = 0
    with conn.cursor() as cur:
        for _, row in df.iterrows():
            cur.execute(MERGE_SQL, [_to_py(row.get(column)) for column in CSV_COLUMNS])
            inserted += 1
    conn.commit()
    conn.close()
    print(f"Loaded macro indicators rows: {inserted}")


if __name__ == "__main__":
    main()
