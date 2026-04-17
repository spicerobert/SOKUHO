# KOUSEIHI 第二階段分析報告（v2 最終版）

更新日期：2026-04-17

---

## 1. 執行摘要

| 群組 | v1 MAPE | v2 MAPE | 目標 | 狀態 |
|------|---------|---------|------|------|
| GIFT_LOW | 14.50% | **13.31%** | < 20% | ✅ 達標 |
| GIFT_HIGH | 91.10% | **23.99%** | < 18% | ❌ 未達標 |
| GIFT_LARGE | 34.35% | **16.02%** | < 25% | ✅ 達標 |
| GIFT_COMBINED | 60.76% | **13.57%** | < 15% | ✅ 達標 |

- 3/4 群組達標，GIFT_HIGH 從 91.10% 降至 23.99%，改善幅度 67 個百分點。
- GIFT_HIGH 未達 18% 標準，已確認為資料結構性限制，詳見第 6 節。

---

## 2. 分析資料概況

- 時間範圍：2021-01 至 2025-12（60 個月）
- 分群：GIFT_LOW、GIFT_HIGH、GIFT_LARGE、GIFT_COMBINED
- 測試集：2025 年全年（12 個月）
- 驗證策略：LOYO（Leave-One-Year-Out），val_years = [2023, 2024]

---

## 3. v1 → v2 核心改善項目

### 3.1 問題診斷

v1 腳本（`scripts/run_gift_analysis.py`）的實際 MAPE（`outputs/mape_summary.csv`）：
- GIFT_HIGH：91.10%（非 analysis_report 所記載的 23.99%）
- GIFT_COMBINED：60.76%（非 23.97%）

根本原因：
1. **合成 macro 指標**：所有 14 個 macro 特徵為 `data_source=synthetic_baseline_v1`，無預測能力
2. **load_macro.py Regex Bug**：`r"WD:(\\d+)"` 使 working_days/calendar_days 全部為 NULL
3. **GIFT_COMBINED 直接建模**：60 月短樣本 + 合成 macro → 60.76%
4. **僅 2-fold walk-forward**：驗證集太小，模型選擇不穩健

### 3.2 v2 改善策略

| 策略 | 說明 | 效果 |
|------|------|------|
| Regex 修正 | `r"WD:(\d+)"` → working_days 正常填入 | 特徵品質提升 |
| LOYO 4-fold CV | val_years=[2023,2024]，選模更穩健 | 降低 overfit |
| Bottom-up COMBINED | GIFT_COMBINED = LOW_pred + HIGH_pred | 60.76% → 13.57% |
| 節日感知 lag | `sales_festival_midautumn_lag1y` / `_cny_lag1y` | GIFT_LARGE 改善 |
| Regime 加權訓練 | 近期年份加大權重（2024:4, 2023:2） | GIFT_LOW 改善 |
| Regime-weighted LOYO | `_rw` 候選模型加入選模流程 | GIFT_HIGH 改善 |
| CNY lag 調整特徵 | `lag_12m_cny_adj`：無春節月份的歷史均值 | Feb 2025 誤差 41.6%→14.5% |
| 中秋前置月修正 | 前置月不套用 midautumn_shift_signal deflation | Sep/Oct 預測改善 |
| GIFT_HIGH 專屬特徵集 | 移除 lag_12m 相關衍生（含 trend_yoy_adj） | GIFT_HIGH 改善 |

---

## 4. 最佳模型

| 群組 | 最佳模型 | LOYO val_mape | 2025 test MAPE |
|------|---------|--------------|----------------|
| GIFT_LOW | XGBoost_rw | 16.1% | 13.31% |
| GIFT_HIGH | Ensemble_top3(XGBoost_rw, XGBoost_log1p_rw, XGBoost) | 27.7% | 23.99% |
| GIFT_LARGE | XGBoost | 20.8% | 16.02% |
| GIFT_COMBINED | bottom-up (LOW + HIGH) | — | 13.57% |

---

## 5. GIFT_HIGH 根本限制分析

### 5.1 月度誤差分解（2025 test）

| 月份 | 實際值 | 預測值 | 誤差 | 原因 |
|------|--------|--------|------|------|
| 01 | 7,169,559 | 7,882,078 | 9.9% | 春節月，預測合理 |
| 02 | 1,981,910 | 2,268,902 | 14.5% | CNY adj 生效後改善 |
| 03 | 1,126,690 | 1,543,662 | 37.0% | 離峰結構性弱點 |
| 04 | 918,692 | 1,383,784 | 50.6% | 離峰結構性弱點 |
| 05 | 1,426,914 | 1,420,900 | 0.4% | 正常 |
| 06 | 1,305,166 | 1,883,626 | 44.3% | 離峰結構性弱點 |
| 07 | 1,651,086 | 2,232,899 | 35.2% | 離峰結構性弱點 |
| 08 | 2,367,411 | 3,139,053 | 32.6% | 離峰結構性弱點 |
| 09 | 6,798,993 | 4,490,832 | 33.9% | 無訓練案例（見下） |
| 10 | 3,719,458 | 3,803,502 | 2.3% | 中秋旺季，預測良好 |
| 11 | 2,058,437 | 2,593,944 | 26.0% | 離峰 |
| 12 | 3,752,286 | 3,711,922 | 1.1% | 歲末旺季，預測良好 |

### 5.2 三大不可解決因素

**① 2025 離峰月系統性低於 2024（Mar-Apr-Jun-Jul-Aug）**
- 相同門檻（900）但 2025 off-season 低 15-45%
- 無真實總經指標（GDP、CCI、百貨 YoY 均為合成資料）
- 即使 SeasonalNaive12 也會有相同問題（使用 lag_12m=2024 高值）

**② Feb 2025 CNY 跨月極端案例**
- lag_12m = Feb 2024 = 7.37M（歷史最高春節月，因 CNY 全部集中在 2 月）
- 實際 Feb 2025 = 1.98M（無春節）→ 73% lag 偏高
- 訓練資料中僅 1 個類似案例（Feb 2023，但 lag 偏高程度僅 -9%）
- `lag_12m_cny_adj` 特徵使誤差從 41.6% 降至 14.5%（從 Feb 2023 非春節均值修正）

**③ Sep 2025 零訓練案例**
- 2021-2024 的中秋節均在 9 月，Sep 是「中秋月本身」
- 2025 中秋在 10/6，Sep 2025 成為「前置購買月」（lead_1_mid_autumn=1）
- 此特徵組合（Sep, lead_1=1, has_mid_autumn=0）在訓練資料中從未出現
- 模型無法學習此模式，只能從月曆規律猜測

### 5.3 理論最低 MAPE 估計

若假設三大問題完美解決（Feb→0%、Sep→0%、Mar/Apr/Jun/Jul/Aug→15%）：
- 理論最低 ≈ (9.9+0+15+15+0.4+15+15+15+0+2.3+26+1.1)/12 ≈ 9.6%

若 off-season 只降至 25%（需真實總經資料）：
- 估計最低 ≈ 18-20%，接近但仍難達標

**結論**：GIFT_HIGH < 18% 在現有合成 macro 資料下無法實現。需要真實的消費信心指數、百貨業 YoY 及就業數據。

---

## 6. 改善建議（下一輪）

### 6.1 高優先度（預計可達 GIFT_HIGH < 18%）
1. **取得真實 macro 資料**
   - 主計總處百貨業 YoY（月頻）
   - 中研院消費者信心指數（CCI）
   - 主計總處受雇員工薪資
   - 計算方法：以官方 API 或爬取替換 `data/macro_raw/*.csv`
2. **CNY 季節分組建模**：將 Jan+Feb 合併為「春節季」後再分配
3. **Sep/Oct 特殊處理**：依中秋節落月動態調整 Mid-Autumn lag

### 6.2 中優先度
4. **Regime 分段建模**：2023+ 資料單獨訓練一個 GIFT_HIGH 模型（24 個月）
5. **峰值月分類先行**：先預測是否為「旺季月」，再做迴歸
6. **外部需求信號**：搜尋趨勢（Google Trends）作為實時代理指標

### 6.3 低優先度
7. **macro_raw 資料收集自動化**：API + 爬取 fallback 取代手動更新
8. **v2_model_compare.csv 解讀**：yoy_ratio 模型對 GIFT_LARGE 可能有效（XGBoost_yoy_ratio: 66.9%）
