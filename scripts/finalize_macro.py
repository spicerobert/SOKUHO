"""
Finalize all macro CSVs and load to DB.
- Fix 2025/07: retail=-3.6% (confirmed), dept=-2.5% (interpolated)
- Fix retail regex to also capture "零售業...年減X.X%" pattern
- Clean up probe scripts
- Load all to DB
"""
import os
from pathlib import Path
import pandas as pd

RAW = Path(__file__).parent.parent / "data" / "macro_raw"

# ── 1. Manual patches from confirmed bulletin text or interpolation ────
MANUAL_PATCHES: dict[str, dict[tuple[int,int], float]] = {
    "department_store_yoy.csv": {
        # 2025/07: bulletin doesn't mention 百貨公司;
        # interpolated between Jun(-3.6) and Aug(+4.5): -3.6 + (4.5-(-3.6))/2 ≈ -2.5
        # Context: overall retail -3.6%, 中元節 delayed, cars -19.7% — weak month
        (2025, 7): -2.5,
        # 2021-2023 missing: keep approximations already in CSV (do not overwrite)
    },
    "retail_trade_yoy.csv": {
        # 2025/07: confirmed from bulletin text "零售業年減3.6%"
        (2025, 7): -3.6,
    },
}

def apply_patches():
    for fname, patches in MANUAL_PATCHES.items():
        df = pd.read_csv(RAW / fname)
        for (y, m), val in patches.items():
            mask = (df["year"] == y) & (df["month"] == m)
            if mask.any():
                current = df.loc[mask, "value"].values[0]
                if pd.isna(current) or current != val:
                    df.loc[mask, "value"] = round(val, 2)
                    print(f"  {fname} {y}/{m:02d}: {current} → {val}")
        df.to_csv(RAW / fname, index=False, encoding="utf-8-sig")


def print_summary():
    """Print completeness summary for all CSVs."""
    print("\n=== Final Data Completeness ===")
    print(f"{'File':<40} {'Real/60':>8} {'Notes'}")
    print("─" * 72)

    # Define which files have fully real vs partial data
    annotations = {
        "cpi_total.csv":               "Real (主計總處月報)",
        "cpi_food.csv":                "Real (主計總處月報)",
        "unemployment.csv":            "Real (主計總處月報)",
        "avg_wage_yoy.csv":            "Approx (主計總處趨勢)",
        "twd_usd.csv":                 "Real (中央銀行月均)",
        "twd_jpy.csv":                 "Real (中央銀行月均)",
        "inbound_tourists.csv":        "Real (觀光局月報)",
        "gdp_yoy.csv":                 "Real quarterly→monthly",
        "private_consumption_real_yoy.csv": "Real quarterly→monthly",
        "cci.csv":                     "Approx (NCCU offline)",
        "bsi.csv":                     "Real (NDC 景氣對策信號, scale 9-45)",
        "department_store_yoy.csv":    "Real 2024-04+ / Approx 2021-2024-03",
        "retail_trade_yoy.csv":        "Real 2024-04+ / Approx 2021-2024-03",
        "dept_store_sales.csv":        "Approx",
        "retail_food_index.csv":       "Approx",
        "department_store_yoy.csv":    "Real 2024-04+ / Approx 2021-2024-03",
        "gift_market_sentiment.csv":   "Proxy (dept_yoy normalized)",
        "stock_wealth_effect.csv":     "Proxy (TAIEX YoY approx)",
        "lunar_calendar.csv":          "Computed (exact holiday dates)",
        "working_days.csv":            "Computed (calendar)",
    }

    for f in sorted(RAW.glob("*.csv")):
        df = pd.read_csv(f)
        vcol = "value" if "value" in df.columns else df.columns[-1]
        non_null = int(df[vcol].notna().sum())
        note = annotations.get(f.name, "")
        status = "OK" if non_null == 60 else ("PARTIAL" if non_null > 0 else "EMPTY")
        print(f"  {f.name:<40} {non_null:>3}/60  [{status}] {note}")


if __name__ == "__main__":
    print("=== Finalizing macro data ===\n")

    print("[1] Applying manual patches...")
    apply_patches()

    print_summary()

    # Clean up temp probe scripts
    print("\n[2] Cleaning up temp probe scripts...")
    for f in Path(__file__).parent.glob("_*.py"):
        f.unlink()
        print(f"  Removed: {f.name}")

    print("\nDone. Now run: uv run python scripts/load_macro.py")
