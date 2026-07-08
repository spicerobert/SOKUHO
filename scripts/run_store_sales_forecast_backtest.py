#!/usr/bin/env python
from __future__ import annotations

import argparse
import calendar as cal_module
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from lunardate import LunarDate
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_percentage_error

try:
    from xgboost import XGBRegressor
    HAS_XGB = True
except Exception:
    HAS_XGB = False

import pyodbc


@dataclass
class BacktestResult:
    model: str
    val_mape: float
    test_mape: float
    pred: np.ndarray


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Store/SR/Web monthly sales backtest")
    p.add_argument("--train-start-year", type=int, default=2021)
    p.add_argument("--train-end-year", type=int, default=2025)
    p.add_argument("--test-year", type=int, default=2026)
    p.add_argument("--test-month-end", type=int, default=3, help="backtest up to month N in test year")
    return p.parse_args()


def _conn() -> pyodbc.Connection:
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


def load_monthly_sales() -> pd.DataFrame:
    sql = """
    SELECT
        report_year,
        report_month,
        SUM(COALESCE(sales_incl_result, 0)) AS sales_incl_result
    FROM vw_daily_store_sales
    WHERE store_type IN ('store', 'SR', 'Web')
    GROUP BY report_year, report_month
    ORDER BY report_year, report_month
    """
    conn = _conn()
    df = pd.read_sql(sql, conn)
    conn.close()
    df["report_year"] = pd.to_numeric(df["report_year"], errors="coerce").astype(int)
    df["report_month"] = pd.to_numeric(df["report_month"], errors="coerce").astype(int)
    df["sales_incl_result"] = pd.to_numeric(df["sales_incl_result"], errors="coerce").astype(float)
    print(f"[INFO] monthly rows={len(df)} range={df['report_year'].min()}-{df['report_year'].max()}")
    return df


def load_macro_monthly() -> pd.DataFrame:
    sql = """
    SELECT
        report_year,
        report_month,
        cci_index,
        dept_store_sales,
        avg_wage_yoy_pct,
        unemployment_rate,
        inbound_tourists,
        gdp_yoy_pct,
        private_consumption_real_yoy_pct,
        department_store_yoy_pct,
        retail_trade_yoy_pct,
        gift_market_sentiment_index,
        stock_wealth_effect_index
    FROM dim_macro_indicators
    ORDER BY report_year, report_month
    """
    conn = _conn()
    df = pd.read_sql(sql, conn)
    conn.close()
    df["report_year"] = pd.to_numeric(df["report_year"], errors="coerce").astype(int)
    df["report_month"] = pd.to_numeric(df["report_month"], errors="coerce").astype(int)
    for c in df.columns:
        if c not in ("report_year", "report_month"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    print(f"[INFO] macro rows={len(df)} range={df['report_year'].min()}-{df['report_year'].max()}")
    return df


def _festival_flags(year: int, month: int) -> tuple[int, int, int, int]:
    cny = LunarDate(year, 1, 1).toSolarDate()
    ma = LunarDate(year, 8, 15).toSolarDate()
    has_cny = 1 if cny.month == month else 0
    has_ma = 1 if ma.month == month else 0
    lead_cny = 1 if ((month % 12) + 1) == cny.month else 0
    lead_ma = 1 if ((month % 12) + 1) == ma.month else 0
    return has_cny, lead_cny, has_ma, lead_ma


def prepare(df: pd.DataFrame, macro_df: pd.DataFrame | None = None) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(dict(year=df.report_year, month=df.report_month, day=1))
    df = df.sort_values("date").reset_index(drop=True)

    df["calendar_days"] = df.apply(lambda r: cal_module.monthrange(int(r["report_year"]), int(r["report_month"]))[1], axis=1)
    df["working_days"] = (df["calendar_days"] * 5 // 7).astype(int)
    df["month_sin"] = np.sin(2 * np.pi * df["report_month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["report_month"] / 12)
    df["is_peak_month"] = df["report_month"].isin([1, 2, 8, 9, 10, 12]).astype(int)

    festival = df.apply(lambda r: _festival_flags(int(r["report_year"]), int(r["report_month"])), axis=1)
    df[["has_lunar_new_year", "lead_1_lunar_new_year", "has_mid_autumn", "lead_1_mid_autumn"]] = pd.DataFrame(
        festival.tolist(), index=df.index
    )

    for lag in [1, 2, 3, 6, 12]:
        df[f"sales_lag_{lag}m"] = df["sales_incl_result"].shift(lag)
    df["rolling_3m_mean"] = df["sales_incl_result"].shift(1).rolling(3).mean()
    df["rolling_6m_mean"] = df["sales_incl_result"].shift(1).rolling(6).mean()
    df["yoy_ratio"] = (df["sales_lag_12m"] / df["sales_lag_1m"].replace(0, np.nan)).clip(0.3, 3.0)

    if macro_df is not None and not macro_df.empty:
        df = df.merge(macro_df, on=["report_year", "report_month"], how="left")
        macro_cols = [c for c in macro_df.columns if c not in ("report_year", "report_month")]
        # 不使用當月未知值，改用 lag1 / lag12
        for col in macro_cols:
            df[f"{col}_lag1"] = df[col].shift(1)
            df[f"{col}_lag12"] = df[col].shift(12)
        # 對測試年度缺漏的 macro 先以前值補齊（等價於可用最新已知）
        lag_cols = [f"{c}_lag1" for c in macro_cols] + [f"{c}_lag12" for c in macro_cols]
        df[lag_cols] = df[lag_cols].ffill()
    return df


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true != 0)
    if mask.sum() == 0:
        return float("nan")
    return float(mean_absolute_percentage_error(y_true[mask], y_pred[mask]) * 100)


def _fit_predict(model, train: pd.DataFrame, test: pd.DataFrame, features: list[str], use_log: bool) -> np.ndarray:
    x_train = train[features].fillna(0.0).to_numpy(dtype=float)
    y_train = train["sales_incl_result"].to_numpy(dtype=float)
    x_test = test[features].fillna(0.0).to_numpy(dtype=float)
    y_fit = np.log1p(y_train) if use_log else y_train
    model.fit(x_train, y_fit)
    raw = model.predict(x_test)
    pred = np.expm1(raw) if use_log else raw
    return np.maximum(pred, 0)


def run_backtest(df: pd.DataFrame, train_start: int, train_end: int, test_year: int, test_month_end: int, use_macro: bool) -> BacktestResult:
    base_features = [
        "report_month", "month_sin", "month_cos", "is_peak_month", "working_days", "calendar_days",
        "has_lunar_new_year", "lead_1_lunar_new_year", "has_mid_autumn", "lead_1_mid_autumn",
        "sales_lag_1m", "sales_lag_2m", "sales_lag_3m", "sales_lag_6m", "sales_lag_12m",
        "rolling_3m_mean", "rolling_6m_mean", "yoy_ratio",
    ]
    macro_features = []
    if use_macro:
        macro_features = [c for c in df.columns if c.endswith("_lag1") or c.endswith("_lag12")]
    features = base_features + macro_features
    work = df[df["report_year"] >= train_start].copy()
    work = work.dropna(subset=["sales_lag_12m"]).reset_index(drop=True)

    val_years = [y for y in [train_end - 1, train_end] if y in work["report_year"].unique()]
    candidates: list[tuple[str, object, bool]] = [
        ("Ridge", Ridge(alpha=20.0), False),
        ("Ridge_log1p", Ridge(alpha=20.0), True),
        ("RandomForest", RandomForestRegressor(n_estimators=400, max_depth=4, min_samples_leaf=2, random_state=42), False),
    ]
    if HAS_XGB:
        candidates.append(
            ("XGBoost", XGBRegressor(
                n_estimators=300, learning_rate=0.05, max_depth=3,
                subsample=0.8, colsample_bytree=0.8, reg_alpha=2.0, reg_lambda=10.0,
                random_state=42, verbosity=0
            ), False)
        )

    best_name, best_obj, best_log, best_val = "SeasonalNaive12", None, False, float("inf")

    for name, model, use_log in candidates:
        fold_mapes: list[float] = []
        for vy in val_years:
            train = work[work["report_year"] < vy]
            val = work[work["report_year"] == vy]
            if train.empty or val.empty:
                continue
            pred = _fit_predict(model, train, val, features, use_log)
            fold_mapes.append(_safe_mape(val["sales_incl_result"].to_numpy(), pred))
        if fold_mapes:
            mape = float(np.mean(fold_mapes))
            if mape < best_val:
                best_name, best_obj, best_log, best_val = name, model, use_log, mape

    train_full = work[(work["report_year"] >= train_start) & (work["report_year"] <= train_end)]
    test = work[(work["report_year"] == test_year) & (work["report_month"] <= test_month_end)].sort_values("date")
    if test.empty:
        return BacktestResult(best_name, best_val, float("nan"), np.array([]))

    if best_obj is None:
        pred = test["sales_lag_12m"].fillna(test["rolling_6m_mean"]).fillna(train_full["sales_incl_result"].median()).to_numpy()
        best_name = "SeasonalNaive12"
    else:
        pred = _fit_predict(best_obj, train_full, test, features, best_log)
    test_mape = _safe_mape(test["sales_incl_result"].to_numpy(), pred)
    final_name = f"{best_name}{'_with_macro' if use_macro else '_baseline'}"
    return BacktestResult(final_name, best_val, test_mape, pred)


def main() -> None:
    args = parse_args()
    sales_df = load_monthly_sales()
    macro_df = load_macro_monthly()
    df_base = prepare(sales_df, macro_df=None)
    df_macro = prepare(sales_df, macro_df=macro_df)
    res_base = run_backtest(df_base, args.train_start_year, args.train_end_year, args.test_year, args.test_month_end, use_macro=False)
    res_macro = run_backtest(df_macro, args.train_start_year, args.train_end_year, args.test_year, args.test_month_end, use_macro=True)
    res = res_macro if np.isfinite(res_macro.test_mape) and res_macro.test_mape <= res_base.test_mape else res_base

    selected_df = df_macro if res is res_macro else df_base
    test = selected_df[
        (selected_df["report_year"] == args.test_year) &
        (selected_df["report_month"] <= args.test_month_end) &
        (selected_df["sales_lag_12m"].notna())
    ].sort_values("date")

    out = Path("outputs")
    out.mkdir(exist_ok=True)
    rows = []
    for (_, r), p in zip(test.iterrows(), res.pred):
        actual = float(r["sales_incl_result"])
        err = abs(actual - float(p)) / max(abs(actual), 1.0) * 100
        rows.append({
            "report_year": int(r["report_year"]),
            "report_month": int(r["report_month"]),
            "actual_sales_incl_result": actual,
            "pred_sales_incl_result": float(p),
            "ape_pct": err,
        })
    monthly_df = pd.DataFrame(rows)
    monthly_df.to_csv(out / "store_sr_web_backtest_monthly.csv", index=False, encoding="utf-8-sig")
    summary_rows = [
        {
            "variant": "baseline_no_macro",
            "train_range": f"{args.train_start_year}-{args.train_end_year}",
            "test_year": args.test_year,
            "test_month_end": args.test_month_end,
            "best_model": res_base.model,
            "val_mape_pct": round(res_base.val_mape, 2) if np.isfinite(res_base.val_mape) else None,
            "test_mape_pct": round(res_base.test_mape, 2) if np.isfinite(res_base.test_mape) else None,
        },
        {
            "variant": "with_macro_lag_features",
            "train_range": f"{args.train_start_year}-{args.train_end_year}",
            "test_year": args.test_year,
            "test_month_end": args.test_month_end,
            "best_model": res_macro.model,
            "val_mape_pct": round(res_macro.val_mape, 2) if np.isfinite(res_macro.val_mape) else None,
            "test_mape_pct": round(res_macro.test_mape, 2) if np.isfinite(res_macro.test_mape) else None,
        },
        {
            "variant": "selected_final",
            "train_range": f"{args.train_start_year}-{args.train_end_year}",
            "test_year": args.test_year,
            "test_month_end": args.test_month_end,
            "best_model": res.model,
            "val_mape_pct": round(res.val_mape, 2) if np.isfinite(res.val_mape) else None,
            "test_mape_pct": round(res.test_mape, 2) if np.isfinite(res.test_mape) else None,
        },
    ]
    pd.DataFrame(summary_rows).to_csv(out / "store_sr_web_backtest_summary.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame([{
        "train_range": f"{args.train_start_year}-{args.train_end_year}",
        "test_year": args.test_year,
        "test_month_end": args.test_month_end,
        "best_model": res.model,
        "val_mape_pct": round(res.val_mape, 2) if np.isfinite(res.val_mape) else None,
        "test_mape_pct": round(res.test_mape, 2) if np.isfinite(res.test_mape) else None,
    }]).to_csv(out / "store_sr_web_backtest_selected.csv", index=False, encoding="utf-8-sig")

    print(f"Best model: {res.model}")
    print(f"Validation MAPE: {res.val_mape:.2f}%")
    print(f"Test MAPE ({args.test_year}~{args.test_month_end:02d}): {res.test_mape:.2f}%")
    print(f"Baseline(no macro) Test MAPE: {res_base.test_mape:.2f}%")
    print(f"With macro lags Test MAPE: {res_macro.test_mape:.2f}%")
    if not monthly_df.empty:
        print(monthly_df.to_string(index=False))
    print("Saved outputs/store_sr_web_backtest_summary.csv and outputs/store_sr_web_backtest_monthly.csv")


if __name__ == "__main__":
    main()
