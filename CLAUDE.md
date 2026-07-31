# CLAUDE.md

本檔案為 Claude Code 的專案長期記憶，涵蓋 SOKUHO ETL、KOUSEIHI ETL、與禮盒銷售分析預測系統三個子系統。

---

## 專案概述

**PosInsight** 為詩特莉食品公司的銷售數據平台，共有三個子系統：

| 子系統 | 資料來源 | 目的 |
|--------|---------|------|
| **SOKUHO ETL** | 每日 PDF 速報 | 門市日報 → `fact_sales` |
| **KOUSEIHI ETL** | 年度 PDF 構成比報表 | 品類月報 → `fact_kouseihi_category` / `fact_kouseihi_kpi` |
| **禮盒分析預測** | `vw_gift_analysis_dataset`（DB View）| 五年禮盒銷售因子分析 + 年度預測 |

共用同一 SQL Server 資料庫（PosInsight），Python + uv + .venv 開發環境。

---

## 常用指令

```bash
# 環境
cp .env.example .env && uv sync

# SOKUHO ETL
uv run python main.py --from-date 2026-03-01 --to-date 2026-03-31
uv run python main.py --from-date 2026-03-01 --to-date 2026-03-31 --force
uv run python main.py --from-date 2026-03-01 --to-date 2026-03-31 --dry-run

# SOKUHO Gmail 同步（Gmail 搜尋 → 下載附件 → 匯入，一行指令）
uv run python scripts/sync_and_import_sokuho.py              # 以 DB 最後 report_date 增量搜尋
uv run python scripts/sync_and_import_sokuho.py --dry-run    # 只下載附件，不寫入 DB
uv run python scripts/sync_and_import_sokuho.py --since 2026-01-01  # 手動覆寫增量基準日期

# KOUSEIHI ETL（尚在開發，SDD 詳見 docs/SDD_KOUSEIHI_AND_ANALYSIS.md）
uv run python main_kouseihi.py               # 全量跑 5 年
uv run python main_kouseihi.py --force       # 強制重跑
uv run python main_kouseihi.py --dry-run     # 驗證不寫入

# 禮盒分析（建模 + 預測 + 圖表）
uv run python scripts/run_gift_analysis_v2.py              # 從 DB 讀取
uv run python scripts/run_gift_analysis_v2.py --from-csv   # 從 CSV（不需 DB）

# 匯出分析資料集
uv run python scripts/build_gift_dataset.py                # vw_gift_analysis_dataset → data/gift_analysis_dataset.csv
uv run python scripts/build_analysis_dataset.py            # vw_kouseihi_analysis_view → data/analysis_dataset.csv

# 載入 macro 資料
uv run python scripts/load_macro.py --raw-dir data/macro_raw
```

---

## 一、SOKUHO ETL

### 流程

```
PDF 檔案 → pdf_parser.py → transformer.py → loader.py → SQL Server
              parse_pdf()   records_to_dataframe()  load_file()
```

### PDF 格式偵測（五種格式）

| 格式 | Page 1 門市數 | Page 2 門市數 | 適用時期 |
|------|-------------|-------------|---------|
| A | 17 | 10 | 10 月 |
| B | 17 | 8  | 11/1–5 |
| D | 17 | 11 | 11/6–10 |
| C | 19 | 9  | 11/11+（CL SOGO B1、Taichung Mitsukoshi 上移 page 1） |
| E | 20 | 11 | 2026-05+（Tian-Mu Mitsukoshi、Hanshin Kaohsiung 上移 page 1；page 2 為 Costco/Anhe/BD 通路） |

### 資料庫結構

- **`dim_store`** — 門市主檔（store_code, store_name, store_type = `store`/`subtotal`/`grand_total`/`HQ`）
- **`fact_sales`** — 唯一鍵：`(report_date, store_id, record_type)`
- **`etl_log`** — 每次匯入結果（`SUCCESS`/`FAILED`/`SKIPPED`）
- **`etl_sokuho_import_resolution`** — override 情況追蹤

PowerBI Views：`vw_daily_store_sales`、`vw_daily_grand_total`、`vw_month_end_reconcile`

### 重要設計決策

- **人事費欄位強制為 NULL**（`load_dataframe` 中設定），避免 DAX 誤用
- **門市名稱正規化**：Unicode 連字號 → ASCII `-`；`ALL 17/19 STORES` → `ALL 18 STORES`；`BD` → `Business Development`
- **非標準 PDF 覆寫**：設定在 `etl/sokuho_import_overrides.yaml`

---

## 二、KOUSEIHI ETL（任務一）

### 資料來源

年度 PDF：`YYYYMM-KOUSEIHI Company.pdf`（預設 MM 固定為 12，年度彙總）。2021~2025 年共 5 份。

臨時例外（2026-03）：
- `E:\OneDrive - Aunt Stella Company\KOUSEIHI\202603-KOUSEIHI Company.pdf`
- 用途：先行補入 2026 年 3 月版本，作為短期分析/驗證資料

每份 PDF 包含：
- 8 商品類別 × 15 時期 = 120 筆 category 記錄
- 5 KPI × 15 時期 = 75 筆 KPI 記錄

### 商品類別代碼

| 代碼 | 說明 |
|------|------|
| `GRAM_COOKIES` | 餅乾類 |
| `GIFT_760_DOWN/UP` | 禮盒 ≤760 / >760（2021-2022） |
| `GIFT_850_DOWN/UP` | 禮盒 ≤850 / >850（2023） |
| `GIFT_900_DOWN/UP` | 禮盒 ≤900 / >900（2024-2025） |
| `GIFT_5000_UP` | 大單 ≥5000 TWD |
| `DRY_CAKE` | 蛋糕類 |
| `FB` | 餐飲類 |
| `OTHER` | 其他 |

### 資料庫結構

- **`fact_kouseihi_category`** — `(report_year, report_month, period_type, category)` 唯一
  - `period_type`: `MONTHLY` / `H1` / `H2` / `ANNUAL`
- **`fact_kouseihi_kpi`** — 客數、客單價、週轉率、月銷售日數、日均銷售
- **`etl_kouseihi_log`** — `SUCCESS`/`FAILED`/`SKIPPED`
- **`dim_gift_category_mapping`** — 年度牌價門檻映射（用於正規化跨年比較）

### ETL 模組架構

```
kouseihi/
  pdf_parser.py    ← pdfplumber 解析，回傳 {categories: [...], kpis: [...]}
  transformer.py   ← 驗證、正規化
  loader.py        ← MERGE 寫入 + etl_kouseihi_log
main_kouseihi.py   ← CLI 入口（--year / --force / --dry-run）
```

### 驗收規格（5 年全量）

```sql
SELECT COUNT(*) FROM fact_kouseihi_category;  -- 應 = 600（5年×120）
SELECT COUNT(*) FROM fact_kouseihi_kpi;        -- 應 = 375（5年×75）
-- 2025 年 TOTAL ANNUAL: 377,054,372 TWD
```

---

## 三、禮盒銷售分析預測系統（任務二）

### 分析聚焦

GIFT 系列合計占年度總銷售約 **70-80%**，是最關鍵商品線。

| 分析群 | 組成 | 說明 |
|--------|------|------|
| `GIFT_LOW` | GIFT_*_DOWN（各年） | 牌價 ≤ 門檻（低牌價禮盒） |
| `GIFT_HIGH` | GIFT_*_UP（各年） | 門檻 < 牌價 ≤ 5000 TWD |
| `GIFT_LARGE` | GIFT_5000_UP | 單筆訂單 ≥ 5000 TWD（大單） |
| `GIFT_COMBINED` | LOW + HIGH | 不分群合計（排除大單） |

### 牌價門檻演進（重要：造成跨年結構性斷點）

| 年份 | GIFT_LOW 門檻 | GIFT_HIGH 門檻 | 調幅 |
|------|-------------|--------------|------|
| 2021-2022 | ≤760 | 761-5000 | 基準 |
| 2023 | ≤850 | 851-5000 | +12% |
| 2024-2025 | ≤900 | 901-5000 | +6% |

### 資料流

```
fact_kouseihi_category
  ↓ JOIN dim_gift_category_mapping
  ↓ UNION + dim_macro_indicators
vw_gift_analysis_dataset（240 列，4 群 × 60 月，2021-01 ~ 2025-12）
  ↓ build_gift_dataset.py
data/gift_analysis_dataset.csv
  ↓ run_gift_analysis_v2.py
outputs/v2_*.csv / outputs/v2_*.png
```

### 建模流程（v2 腳本）

**主腳本**：`scripts/run_gift_analysis_v2.py`（~1000 行）

**特徵工程三類**（`prepare()` 函數中計算）：

| 類型 | 重要特徵 |
|------|---------|
| 月曆特徵 | `report_month`, `month_sin/cos`, `has_lunar_new_year`, `has_mid_autumn`, `lead_1_mid_autumn`, `is_peak_month` |
| 結構性特徵 | `threshold_floor/ceiling`, `year_in_regime`（距上次門檻調整年數）, `composition_curr/prev_pct` |
| 滯後特徵 | `sales_lag_1/3/6/12m`, `rolling_3/6m_mean`, `sales_festival_midautumn_lag1y`, `sales_festival_cny_lag1y`, `cny_shift_signal`, `lag_12m_cny_adj` |

**驗證策略**：LOYO（Leave-One-Year-Out），val_years = [2023, 2024]

**候選模型**（含 regime-weighted 版本 `_rw`）：
- Ridge(10/100)、ElasticNet、RandomForest(shallow)、XGBoost、XGBoost_tight
- 每個模型對應 `raw` / `log1p` / `yoy_ratio` 三種目標轉換 + `_rw` 加權版

**GIFT_COMBINED**：不直接建模，採 **bottom-up**（LOW_pred + HIGH_pred），效果大幅優於直接建模。

### v2 最終預測結果

| 群組 | v1 MAPE | v2 MAPE | 目標 | 狀態 |
|------|---------|---------|------|------|
| GIFT_LOW | 14.50% | **13.31%** | <20% | ✅ 達標 |
| GIFT_HIGH | 91.10% | **23.99%** | <18% | ❌ 未達標 |
| GIFT_LARGE | 34.35% | **16.02%** | <25% | ✅ 達標 |
| GIFT_COMBINED | 60.76% | **13.57%** | <15% | ✅ 達標 |

**最佳模型**：

| 群組 | 最佳模型 |
|------|---------|
| GIFT_LOW | XGBoost_rw |
| GIFT_HIGH | Ensemble_top3(XGBoost_rw, XGBoost_log1p_rw, XGBoost) |
| GIFT_LARGE | XGBoost |
| GIFT_COMBINED | bottom-up（LOW + HIGH） |

### GIFT_HIGH 未達標的根本原因

GIFT_HIGH 23.99% 無法進一步改善的結構性限制：

1. **2025 離峰月系統性低於 2024**（Mar-Aug，低 15-45%）：`cci` 仍為近似值（NCCU 全站下線）；`dept_store_yoy` 2021-2024/03 為近似值（MOEA EE520 需登入）；2024/04 起已有真實 MOEA 月報數據
2. **CNY 跨月極端案例**：Feb 2025 lag_12m = Feb 2024（CNY）= 7.37M，但實際 1.98M（-73%）；訓練資料中僅 1 個類似案例（Feb 2023，僅 -9%）
3. **零訓練案例**：2021-2024 年中秋均在 9 月；2025 年中秋在 10/6，Sep 成「前置備貨月」——此特徵組合從未出現在訓練資料中

**改善門檻**：需取得真實 CCI（消費者信心指數）、百貨業 YoY、受雇薪資等官方月頻指標。

### 已知修正與關鍵工程決策

| 問題 | 修正方式 |
|------|---------|
| `load_macro.py` Regex Bug | `r"WD:(\\d+)"` → `r"WD:(\d+)"` （working_days/calendar_days 全為 NULL 已修） |
| v1 MAPE 虛報 | `analysis_report.md` 舊版數字錯誤；真實結果見 `outputs/mape_summary.csv` |
| GIFT_HIGH lag_12m 污染 | GIFT_HIGH 使用專屬特徵集，移除 `sales_lag_12m`、`trend_yoy_adj`、`yoy_estimate`、`comp_x_lag12` |
| Feb CNY 跨月 | 新增 `lag_12m_cny_adj`（用歷史非春節同月均值取代被污染的 lag_12m） |
| 中秋前置月誤判 | `lead_1_mid_autumn=1` 時強制 `midautumn_shift_signal=0`（不向下調整） |
| 合成 macro 無效 | `REAL_MACRO_FEATURES = []`（預設停用）；`bsi`/`dept_store_yoy`/`retail_trade_yoy` 已有部分真實資料，可考慮重新測試 |

### 輸出檔案

| 檔案 | 說明 |
|------|------|
| `outputs/v2_model_compare.csv` | 所有候選模型的 LOYO val_mape |
| `outputs/v2_predictions_2025.csv` | 各群 2025 月度預測值 |
| `outputs/v2_feature_importance_*.csv` | 特徵重要度 |
| `outputs/v2_*.png` | 預測 vs 實際圖表 |
| `docs/analysis_report.md` | 完整分析報告（含月度誤差明細） |

---

## 四、分析資料集說明（`data/analysis_dataset.csv`）

每列為一個月份的全品類匯總，共 60 列（2021-01 ~ 2025-12）。

**核心欄位**：

| 欄位 | 說明 |
|------|------|
| `report_year` / `report_month` | 年月（2021-2025） |
| `monthly_total_sales` | 全品類月度銷售合計（TWD） |
| `gift_5000_sales` | GIFT_5000_UP（大單）銷售 |
| `gift_floor_category` | 當年禮盒類別代碼（如 `GIFT_900_DOWN`） |
| `gift_floor_sales` | 當年低牌價禮盒銷售 |
| `gram_cookies_sales` / `fb_sales` | 餅乾 / 餐飲銷售 |
| `customer_count` / `unit_price` | 客數 / 客單價 |
| `has_lunar_new_year` / `has_mid_autumn` | 節日旗標 |
| macro 指標（14 欄） | `bsi`/`dept_store_yoy`/`retail_trade_yoy` 2024-04+ 已更新真實數據；其餘為近似值或代理指標 |

**重要業務規律**（可從資料直接觀察）：

- **春節效應**：CNY 月銷售是一般月 3-5x（Jan/Feb 依春節落月而異）
- **中秋效應**：中秋月（8/9月）銷售是一般月 2-4x；2025 年中秋在 10/6 → Sep 2025 為大型前置備貨月（76.2M，歷史最高）
- **門檻調漲**：2023 年 760→850 造成 GIFT_LOW 銷售金額跳升（相同量但更高金額）
- **GIFT_COMBINED 驗算**：任一月 GIFT_COMBINED = GIFT_LOW + GIFT_HIGH（可交叉驗證）

---

## 五、開發注意事項

- **Python 環境**：一律用 `uv`，絕不直接 `pip install`
- **SOKUHO Gmail 自動同步**（`scripts/sync_and_import_sokuho.py`）：
  - `auth/credentials.json` 是 Gmail API OAuth（installed-app，project `pipeline-499103`），`auth/token.json` 為授權後快取的 refresh token；兩者皆已加入 `.gitignore`，不可提交
  - 增量策略：先查 `fact_sales` 的 `MAX(report_date)` 當作基準，Gmail 搜尋只用 `after:<基準日>` 縮小範圍（不掃全信箱）。信件條件為 `(from:bellecheng@ OR from:mantsu@ OR from:billy@) subject:SOKUHO has:attachment filename:SOKUHO`（可用環境變數 `SOKUHO_GMAIL_SENDERS` 覆寫）。收件／OAuth 帳號仍是 `robert@auntstella.com.tw`；代班時寄件人常是 `mantsu@`（若只搜 bellecheng 會漏抓範圍主旨那批）
  - 主旨可能是單日或日期範圍（如 `SOKUHO 2026.07.03-07.05`、`SOKUHO 2026.06.18~2026.06.21`、`SOKUHO 2026.07.24~2026.7.26`），但**附件檔名仍是逐日拆開**的 `SOKUHO YYYY.MM.DD.pdf`（一封信可能有多個附件），下載邏輯遞迴走 MIME、逐一附件解析日期，不受主旨格式影響；下載後依 `parse_date_from_filename` 分類到 `PDF_DIR\<year>\<yyyymm>\`（沿用既有資料夾慣例，如 `2026\202607\`），本機已存在的檔名會跳過不重複下載
  - 下載完成後自動呼叫 `main.py --from-date --to-date` 匯入新範圍，等同「搜尋→下載→分類→匯入」一行指令。若曾漏抓，用 `--since <缺口前一日>` 回補（增量預設不會往回看）
- **macro 資料品質**（2026-05 更新）：
  - **真實資料**：`cpi_total/food`, `unemployment`, `twd_usd/jpy`, `inbound_tourists`（主計總處/央行）；`bsi`（NDC 景氣對策信號 9-45分，60/60筆）；`dept_store_yoy`/`retail_trade_yoy`（2024/04-2025/12 MOEA 月報真實值）
  - **近似值**：`cci`（NCCU 網站 DNS 不存在，無存檔）；`dept_store_yoy` 2021-2024/03（MOEA EE520 查詢系統需登入）；`avg_wage_yoy`、`dept_store_sales`（趨勢近似）
  - **代理指標**：`gift_market_sentiment`（dept_yoy 正規化）；`stock_wealth_effect`（TAIEX YoY 近似）
  - **重大改進（2026-05）**：`retail_trade_yoy` 2025/04-12 從 MOEA EE521 Highcharts API 取得真實值；`bsi` 完整 60 筆 NDC 景氣對策信號；`dept_store_yoy` 2024/04+ 從 MOEA 月報 regex 提取
  - **EE521 系統**：`https://service.moea.gov.tw/EE521/visualize/VisDashboard.aspx?d=2`（零售業），Highcharts 物件可用 `Highcharts.charts[0].series` 直接提取
  - **百貨公司細目**：僅存於 MOEA EE520（需登入）和月報文字；EE521 只有整體零售業
  - 更新腳本：`scripts/scrape_final.py`（MOEA bulletin + Highcharts）、`scripts/fetch_ndc_full.py`（NDC BSI）
  - 重跑指令：`uv run python scripts/scrape_final.py` → `uv run python scripts/scrape_highcharts.py`（若需重建 Highcharts）→ `uv run python scripts/load_macro.py`
- **MAPE 真實值**：永遠查 `outputs/mape_summary.csv`，不要信任 `docs/analysis_report.md` 內的舊版數字（可能人工編輯過）
- **v1 vs v2**：`scripts/run_gift_analysis.py` 為課程 agent 版（v1，保留備查）；正式版為 `scripts/run_gift_analysis_v2.py`
- **Bottom-up 優先**：GIFT_COMBINED 預測永遠用 LOW_pred + HIGH_pred，直接建模效果差很多（22.6% vs 13.6%）
