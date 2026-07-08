#!/usr/bin/env python
from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.run_gift_analysis_v2 as m


GROUPS = ["GIFT_LOW", "GIFT_HIGH", "GIFT_LARGE", "GIFT_COMBINED"]


def _festival_months(df: pd.DataFrame, flag_col: str) -> pd.DataFrame:
    base = (
        df[df["canonical_group"] == "GIFT_COMBINED"][["report_year", "report_month", flag_col]]
        .drop_duplicates()
        .sort_values(["report_year", "report_month"])
    )
    return base[base[flag_col] == 1][["report_year", "report_month"]]


def _month_sales(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    return (
        df[(df["report_year"] == year) & (df["report_month"] == month) & (df["canonical_group"].isin(GROUPS))]
        [["canonical_group", "sales_result"]]
        .set_index("canonical_group")
    )


def main() -> None:
    df_raw = m.load_data(from_csv=False)
    df = m.prepare(df_raw)

    cny = _festival_months(df, "has_lunar_new_year")
    cny_lead = _festival_months(df, "lead_1_lunar_new_year")
    mid = _festival_months(df, "has_mid_autumn")
    mid_lead = _festival_months(df, "lead_1_mid_autumn")

    print("=== Festival Anchor (2021-2026) ===")
    print("CNY months:", cny.values.tolist())
    print("CNY lead-1 months:", cny_lead.values.tolist())
    print("Mid-Autumn months:", mid.values.tolist())
    print("Mid-Autumn lead-1 months:", mid_lead.values.tolist())

    print("\n=== CNY month vs previous month (sales ratio) ===")
    for _, r in cny.iterrows():
        y, mon = int(r["report_year"]), int(r["report_month"])
        if mon == 1:
            continue
        cur = _month_sales(df, y, mon)
        prev = _month_sales(df, y, mon - 1)
        if cur.empty or prev.empty:
            continue
        ratio = (cur["sales_result"] / prev["sales_result"]).rename("ratio_vs_prev")
        print(f"{y}-{mon:02d}", ratio.round(3).to_dict())

    print("\n=== Mid-Autumn month vs previous month (sales ratio) ===")
    for _, r in mid.iterrows():
        y, mon = int(r["report_year"]), int(r["report_month"])
        if mon == 1:
            continue
        cur = _month_sales(df, y, mon)
        prev = _month_sales(df, y, mon - 1)
        if cur.empty or prev.empty:
            continue
        ratio = (cur["sales_result"] / prev["sales_result"]).rename("ratio_vs_prev")
        print(f"{y}-{mon:02d}", ratio.round(3).to_dict())

    out = Path("outputs")
    models = Path("models")
    print("\n=== 2026Q1 backtest monthly error ===")
    for g in GROUPS:
        sub = df[df["canonical_group"] == g].copy()
        res = m.model_one_group(sub, g, m.ALL_FEATURES, out, models, test_year=2026, test_month_start=1, test_month_end=3)
        test = sub[(sub["report_year"] == 2026) & (sub["report_month"].between(1, 3))].sort_values("date")
        print(f"{g} MAPE={res['test_mape_pct']:.2f}%")
        for d, a, p in zip(test["date"], test["sales_result"], res["pred_series"]):
            err = abs(float(a) - float(p)) / max(abs(float(a)), 1.0) * 100
            print(f"  {str(d)[:10]} actual={int(a):,} pred={float(p):,.1f} err={err:.2f}%")


if __name__ == "__main__":
    main()
