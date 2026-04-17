#!/usr/bin/env python
"""Run EDA, correlation, and forecasting for gift groups."""

from __future__ import annotations

import os
from pathlib import Path
import warnings

import joblib
import numpy as np
import pandas as pd
import pyodbc
import seaborn as sns
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
import statsmodels.api as sm
try:
    from xgboost import XGBRegressor
    HAS_XGB = True
except Exception:
    HAS_XGB = False

warnings.filterwarnings("ignore")

GROUPS = ["GIFT_LOW", "GIFT_HIGH", "GIFT_LARGE", "GIFT_COMBINED"]
FEATURES = [
    # Curated raw indicators (remove duplicated/similar proxies)
    "dept_store_sales",
    "retail_food_index",
    "cci_index",
    "cpi_food_yoy_pct",
    "avg_wage_yoy_pct",
    "unemployment_rate",
    "twd_jpy_rate",
    "twd_usd_rate",
    "inbound_tourists",
    "bsi_index",
    "gdp_yoy_pct",
    "private_consumption_real_yoy_pct",
    "gift_market_sentiment_index",
    "stock_wealth_effect_index",
    "working_days",
    "has_lunar_new_year",
    "has_mid_autumn",
]

STATIC_FEATURES = [
    "sales_yoy_pct",
    "composition_curr_pct",
    "composition_prev_pct",
    "threshold_floor",
    "threshold_ceiling",
    "lunar_new_year_day",
    "mid_autumn_day",
    "calendar_days",
]


def _safe_mape(y_true: pd.Series, y_pred: np.ndarray) -> float:
    if len(y_true) == 0:
        return float("nan")
    return float(mean_absolute_percentage_error(y_true, y_pred) * 100)


def _conn():
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


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["date"] = pd.to_datetime(dict(year=d.report_year, month=d.report_month, day=1))
    d = d.sort_values(["canonical_group", "date"]).reset_index(drop=True)
    for lag in [1, 3, 12]:
        d[f"sales_lag_{lag}m"] = d.groupby("canonical_group")["sales_result"].shift(lag)
    d["sales_rolling_3m_mean"] = d.groupby("canonical_group")["sales_result"].shift(1).rolling(3).mean().reset_index(level=0, drop=True)
    d["sales_rolling_6m_mean"] = d.groupby("canonical_group")["sales_result"].shift(1).rolling(6).mean().reset_index(level=0, drop=True)
    d["month_sin"] = np.sin(2 * np.pi * d["report_month"] / 12)
    d["month_cos"] = np.cos(2 * np.pi * d["report_month"] / 12)
    d["has_lunar_new_year"] = d["has_lunar_new_year"].fillna(0)
    d["has_mid_autumn"] = d["has_mid_autumn"].fillna(0)
    d["lead_1_lunar_new_year"] = d.groupby("canonical_group")["has_lunar_new_year"].shift(-1).fillna(0)
    for col in FEATURES:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
            d[col] = d.groupby("canonical_group")[col].transform(lambda s: s.ffill().bfill())
    for col in STATIC_FEATURES:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def main() -> None:
    out = Path("outputs")
    models = Path("models")
    out.mkdir(exist_ok=True)
    models.mkdir(exist_ok=True)

    conn = _conn()
    df = pd.read_sql("SELECT * FROM vw_gift_analysis_dataset ORDER BY report_year, report_month, canonical_group", conn)
    conn.close()
    df = _prepare(df)

    # EDA figure 1 + 4
    plt.figure(figsize=(12, 6))
    for g in GROUPS:
        sub = df[df.canonical_group == g]
        plt.plot(sub["date"], sub["sales_result"], label=g)
    plt.legend()
    plt.title("Gift Group Monthly Sales (2021-2025)")
    plt.tight_layout()
    plt.savefig(out / "gift_timeseries_4groups.png", dpi=150)
    plt.close()

    # threshold impact chart
    low = df[df.canonical_group == "GIFT_LOW"]
    plt.figure(figsize=(12, 4))
    plt.plot(low["date"], low["sales_result"])
    plt.axvline(pd.Timestamp("2023-01-01"), color="red", linestyle="--")
    plt.axvline(pd.Timestamp("2024-01-01"), color="red", linestyle="--")
    plt.title("GIFT_LOW Threshold Impact")
    plt.tight_layout()
    plt.savefig(out / "threshold_impact.png", dpi=150)
    plt.close()

    # correlations and models
    mape_rows = []
    compare_rows = []
    corr_rows = []
    for g in GROUPS:
        sub = df[df.canonical_group == g].copy()
        corr = sub[["sales_result"] + FEATURES].corr(numeric_only=True)["sales_result"].drop("sales_result")
        for k, v in corr.items():
            corr_rows.append({"group": g, "feature": k, "pearson": v})

        model_cols = FEATURES + STATIC_FEATURES + [
            "lead_1_lunar_new_year",
            "month_sin",
            "month_cos",
            "sales_lag_1m",
            "sales_lag_3m",
            "sales_lag_12m",
            "sales_rolling_3m_mean",
            "sales_rolling_6m_mean",
            "sales_result",
            "report_year",
            "date",
        ]
        model_df = sub[model_cols].copy()
        for col in model_cols:
            if col in {"sales_result", "report_year", "date"}:
                continue
            model_df[col] = model_df[col].fillna(model_df[col].median())
        model_df = model_df.dropna(subset=["sales_result"])
        train = model_df[model_df["report_year"] <= 2024]
        test = model_df[model_df["report_year"] == 2025]
        if train.empty:
            mape_rows.append({"group": g, "model": "RandomForest", "mape_2025_pct": np.nan})
            continue
        X_train = train.drop(columns=["sales_result", "report_year", "date"])
        y_train = train["sales_result"]
        X_test = test.drop(columns=["sales_result", "report_year", "date"])
        y_test = test["sales_result"]
        X_train = X_train.apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
        X_test = X_test.apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
        y_train = pd.to_numeric(y_train, errors="coerce").fillna(y_train.median()).astype(float)
        y_test = pd.to_numeric(y_test, errors="coerce").fillna(y_test.median() if len(y_test) else 0).astype(float)

        # walk-forward validation: mean MAPE on 2023 and 2024
        validation_years = [2023, 2024]

        candidates = {
            "RandomForest": RandomForestRegressor(n_estimators=500, random_state=42),
            "HistGBR": HistGradientBoostingRegressor(random_state=42, max_depth=4, learning_rate=0.05),
            "Ridge": Ridge(alpha=1.0),
        }
        if HAS_XGB:
            candidates["XGBoost"] = XGBRegressor(
                n_estimators=600,
                learning_rate=0.03,
                max_depth=4,
                subsample=0.9,
                colsample_bytree=0.9,
                objective="reg:squarederror",
                random_state=42,
            )

        best_name = None
        best_model = None
        best_use_log = False
        best_is_naive = False
        best_val_mape = float("inf")
        for use_log in [False, True]:
            for name, model in candidates.items():
                fold_mapes: list[float] = []
                for vy in validation_years:
                    train_core = model_df[model_df["report_year"] < vy]
                    val = model_df[model_df["report_year"] == vy]
                    if train_core.empty or val.empty:
                        continue
                    X_core = train_core.drop(columns=["sales_result", "report_year", "date"]).apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
                    y_core = pd.to_numeric(train_core["sales_result"], errors="coerce").fillna(train_core["sales_result"].median()).astype(float)
                    X_val = val.drop(columns=["sales_result", "report_year", "date"]).apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
                    y_val = pd.to_numeric(val["sales_result"], errors="coerce").fillna(val["sales_result"].median()).astype(float)

                    y_fit = np.log1p(y_core) if use_log else y_core
                    model.fit(X_core, y_fit)
                    val_pred_raw = model.predict(X_val)
                    val_pred = np.expm1(val_pred_raw) if use_log else val_pred_raw
                    val_pred = np.maximum(val_pred, 0)
                    fold_mapes.append(_safe_mape(y_val, val_pred))
                val_mape = float(np.mean(fold_mapes)) if fold_mapes else float("inf")
                label = f"{name}_log1p" if use_log else name
                compare_rows.append({"group": g, "model": label, "val_2024_mape_pct": val_mape})
                if val_mape < best_val_mape:
                    best_val_mape = val_mape
                    best_name = label
                    best_model = model
                    best_use_log = use_log
                    best_is_naive = False

        # Seasonal naive baseline often outperforms overfit models in short monthly series.
        naive_fold_mapes: list[float] = []
        for vy in validation_years:
            val = model_df[model_df["report_year"] == vy]
            train_core = model_df[model_df["report_year"] < vy]
            if val.empty or train_core.empty:
                continue
            y_val = pd.to_numeric(val["sales_result"], errors="coerce").fillna(val["sales_result"].median()).astype(float)
            naive_val = val["sales_lag_12m"].fillna(val["sales_lag_3m"]).fillna(val["sales_lag_1m"]).fillna(train_core["sales_result"].median())
            naive_fold_mapes.append(_safe_mape(y_val, naive_val.to_numpy()))
        if naive_fold_mapes:
            naive_val_mape = float(np.mean(naive_fold_mapes))
            compare_rows.append({"group": g, "model": "SeasonalNaive12", "val_2024_mape_pct": naive_val_mape})
            if naive_val_mape < best_val_mape:
                best_val_mape = naive_val_mape
                best_name = "SeasonalNaive12"
                best_model = None
                best_use_log = False
                best_is_naive = True

        # fit best model on <=2024 then evaluate 2025
        if best_is_naive:
            pred = test["sales_lag_12m"].fillna(test["sales_lag_3m"]).fillna(test["sales_lag_1m"]).fillna(y_train.median()).to_numpy()
        else:
            X_train_full = X_train
            y_train_full = np.log1p(y_train) if best_use_log else y_train
            best_model.fit(X_train_full, y_train_full)
            pred_raw = best_model.predict(X_test)
            pred = np.expm1(pred_raw) if best_use_log else pred_raw
            pred = np.maximum(pred, 0)
        mape = _safe_mape(y_test, pred) if len(y_test) else np.nan
        mape_rows.append({"group": g, "model": best_name, "mape_2025_pct": mape, "val_2024_mape_pct": best_val_mape})
        if not best_is_naive:
            joblib.dump(best_model, models / f"gift_{g.lower()}_best.pkl")

        if best_model is not None and hasattr(best_model, "feature_importances_"):
            importances = best_model.feature_importances_
        else:
            # fallback for models without native importances
            importances = np.zeros(len(X_train.columns))
        fi = pd.DataFrame({"feature": X_train.columns, "importance": importances}).sort_values("importance", ascending=False)
        fi.to_csv(out / f"feature_importance_{g}.csv", index=False, encoding="utf-8-sig")
        plt.figure(figsize=(8, 4))
        sns.barplot(data=fi.head(10), x="importance", y="feature")
        plt.title(f"Feature Importance - {g}")
        plt.tight_layout()
        plt.savefig(out / f"feature_importance_{g}.png", dpi=150)
        plt.close()

        # OLS
        X_ols = sm.add_constant(X_train, has_constant="add")
        X_ols = X_ols.replace([np.inf, -np.inf], np.nan).fillna(0)
        y_ols = y_train.replace([np.inf, -np.inf], np.nan).fillna(y_train.median()).astype(float)
        ols = sm.OLS(y_ols, X_ols).fit()
        (out / f"ols_{g}.txt").write_text(ols.summary().as_text(), encoding="utf-8")

        # prediction chart
        if len(test):
            plt.figure(figsize=(8, 4))
            plt.plot(test["date"], y_test.values, label="actual")
            plt.plot(test["date"], pred, label="pred")
            plt.title(f"Prediction vs Actual - {g}")
            plt.legend()
            plt.tight_layout()
            plt.savefig(out / f"prediction_vs_actual_{g}.png", dpi=150)
            plt.close()

    pd.DataFrame(corr_rows).to_csv(out / "corr_matrix_long.csv", index=False, encoding="utf-8-sig")
    corr_pivot = pd.DataFrame(corr_rows).pivot(index="feature", columns="group", values="pearson")
    plt.figure(figsize=(9, 7))
    sns.heatmap(corr_pivot, annot=True, cmap="RdBu_r", center=0)
    plt.title("Correlation Heatmap by Group")
    plt.tight_layout()
    plt.savefig(out / "corr_heatmap_4groups.png", dpi=150)
    plt.close()

    # lag correlation charts
    for g in GROUPS:
        sub = df[df.canonical_group == g].copy()
        lags = [0, 1, 2, 3]
        rows = []
        for feature in ["cci_index", "bsi_index", "dept_store_sales", "retail_food_index"]:
            for lag in lags:
                rows.append({"feature": feature, "lag": lag, "corr": sub["sales_result"].corr(sub[feature].shift(lag))})
        lag_df = pd.DataFrame(rows)
        plt.figure(figsize=(8, 4))
        for feature in lag_df["feature"].unique():
            p = lag_df[lag_df["feature"] == feature]
            plt.plot(p["lag"], p["corr"], marker="o", label=feature)
        plt.title(f"Lag Correlation - {g}")
        plt.xlabel("lag month")
        plt.ylabel("corr")
        plt.legend(fontsize=7)
        plt.tight_layout()
        plt.savefig(out / f"lag_corr_{g}.png", dpi=150)
        plt.close()

    pd.DataFrame(compare_rows).to_csv(out / "model_compare_2024.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(mape_rows).to_csv(out / "mape_summary.csv", index=False, encoding="utf-8-sig")
    print("Analysis pipeline finished.")


if __name__ == "__main__":
    main()
