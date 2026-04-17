#!/usr/bin/env python
"""Prepare data/macro_raw CSV files (60 months each)."""

from __future__ import annotations

from pathlib import Path
import calendar
import pandas as pd
from lunardate import LunarDate


def _base_frame() -> pd.DataFrame:
    rows = []
    for year in range(2021, 2026):
        for month in range(1, 13):
            rows.append({"year": year, "month": month})
    return pd.DataFrame(rows)


def _write_metric(path: Path, df: pd.DataFrame, value_col: str) -> None:
    out = df[["year", "month", value_col]].rename(columns={value_col: "value"})
    out.to_csv(path, index=False, encoding="utf-8-sig")


def _lunar_flags(df: pd.DataFrame) -> pd.DataFrame:
    lny = {}
    ma = {}
    for y in range(2021, 2026):
        lny_date = LunarDate(y, 1, 1).toSolarDate()
        ma_date = LunarDate(y, 8, 15).toSolarDate()
        lny[(lny_date.year, lny_date.month)] = lny_date.day
        ma[(ma_date.year, ma_date.month)] = ma_date.day
    values = []
    for _, row in df.iterrows():
        key = (int(row["year"]), int(row["month"]))
        parts = []
        if key in lny:
            parts.append(f"LNY:{lny[key]}")
        if key in ma:
            parts.append(f"MA:{ma[key]}")
        values.append("|".join(parts))
    out = df.copy()
    out["value"] = values
    return out


def _working_days(df: pd.DataFrame) -> pd.DataFrame:
    values = []
    for _, row in df.iterrows():
        y = int(row["year"])
        m = int(row["month"])
        cal_days = calendar.monthrange(y, m)[1]
        wd = 0
        for d in range(1, cal_days + 1):
            if calendar.weekday(y, m, d) < 5:
                wd += 1
        values.append(f"WD:{wd}|CD:{cal_days}")
    out = df.copy()
    out["value"] = values
    return out


def main() -> None:
    root = Path("data")
    raw_dir = root / "macro_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    source = pd.read_csv(root / "macro_indicators.csv")
    source.columns = [c.strip().lower() for c in source.columns]
    source = source.rename(columns={"report_year": "year", "report_month": "month"})
    base = _base_frame()
    merged = base.merge(source, on=["year", "month"], how="left")

    mapping = {
        "dept_store_sales.csv": "department_store_yoy_pct",
        "retail_food_index.csv": "retail_sales_index",
        "cci.csv": "cci_index",
        "cpi_total.csv": "cpi_yoy_pct",
        "cpi_food.csv": "cpi_yoy_pct",
        "avg_wage_yoy.csv": "private_consumption_real_yoy_pct",
        "unemployment.csv": "unemployment_rate",
        "twd_jpy.csv": "twd_jpy_rate",
        "twd_usd.csv": "twd_usd_rate",
        "inbound_tourists.csv": "inbound_tourists",
        "bsi.csv": "gift_market_sentiment_index",
        "gdp_yoy.csv": "gdp_yoy_pct",
        "private_consumption_real_yoy.csv": "private_consumption_real_yoy_pct",
        "department_store_yoy.csv": "department_store_yoy_pct",
        "retail_trade_yoy.csv": "retail_trade_yoy_pct",
        "gift_market_sentiment.csv": "gift_market_sentiment_index",
        "stock_wealth_effect.csv": "stock_wealth_effect_index",
    }
    for file_name, col in mapping.items():
        _write_metric(raw_dir / file_name, merged, col)

    _lunar_flags(base).to_csv(raw_dir / "lunar_calendar.csv", index=False, encoding="utf-8-sig")
    _working_days(base).to_csv(raw_dir / "working_days.csv", index=False, encoding="utf-8-sig")
    print("Prepared macro_raw CSV files.")


if __name__ == "__main__":
    main()
