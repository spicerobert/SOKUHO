---
name: kouseihi-gift-forecast
description: >-
  SOKUHO repo 的分析子系統：KOUSEIHI 構成比 PDF 匯入、禮盒銷售預測（v2 模型、MAPE、分群）、
  macro 外部指標資料品質與更新、禮盒業務規律。Use when KOUSEIHI、import_kouseihi_from_pdf.py、
  fact_kouseihi_*、run_gift_analysis_v2.py、build_gift_dataset.py、GIFT_LOW／GIFT_HIGH／GIFT_COMBINED、
  MAPE、load_macro.py、scrape_final.py、fetch_ndc_full.py、macro、牌價門檻時。
---

# KOUSEIHI 與禮盒分析預測

資料庫連線、指令總表見根目錄 `CLAUDE.md`。

## KOUSEIHI ETL

- 來源：`YYYYMM-KOUSEIHI Company.pdf`（2021–2025 為年度版，MM=12）；臨時例外 `E:\OneDrive - Aunt Stella Company\KOUSEIHI\202603-KOUSEIHI Company.pdf`
- `fact_kouseihi_category` 唯一鍵 `(report_year, report_month, period_type, category)`，`period_type` = `MONTHLY`/`H1`/`H2`/`ANNUAL`
- 驗收：category 600 列、kpi 375 列（5 年）；2025 TOTAL ANNUAL = 377,054,372 TWD
- 規格書：`docs/SDD_KOUSEIHI_AND_ANALYSIS.md`

**禮盒牌價門檻逐年調整，造成跨年結構性斷點**（以 `dim_gift_category_mapping` 正規化）：

| 年份 | 類別代碼 | GIFT_LOW | GIFT_HIGH |
|------|---------|----------|-----------|
| 2021-2022 | `GIFT_760_DOWN/UP` | ≤760 | 761–5000 |
| 2023 | `GIFT_850_DOWN/UP` | ≤850 | 851–5000 |
| 2024-2025 | `GIFT_900_DOWN/UP` | ≤900 | 901–5000 |

`GIFT_5000_UP` 為單筆 ≥5000 的大單（= `GIFT_LARGE`）。GIFT 系列約占年銷售 70–80%。

## 禮盒分析預測

- 正式版是 `scripts/run_gift_analysis_v2.py`；`run_gift_analysis.py` 為 v1 課程版，僅保留備查
- 分群：`GIFT_LOW` / `GIFT_HIGH` / `GIFT_LARGE` / `GIFT_COMBINED`（= LOW + HIGH，不含大單）
- **GIFT_COMBINED 一律用 bottom-up（LOW_pred + HIGH_pred）**，直接建模差很多（22.6% vs 13.6%）
- 驗證：LOYO，val_years = [2023, 2024]
- **MAPE 一律看 `outputs/v2_mape_summary.csv`**（`mape_summary.csv` 是 v1）；不要信 `docs/analysis_report.md` 的數字
- 目標 MAPE：LOW <20%、HIGH <18%、LARGE <25%、COMBINED <15%；GIFT_HIGH 是唯一長期未達標的群

### 已做過的關鍵修正（不要改回去）

| 問題 | 修正 |
|------|------|
| GIFT_HIGH 被 lag_12m 污染 | 使用專屬特徵集，移除 `sales_lag_12m`、`trend_yoy_adj`、`yoy_estimate`、`comp_x_lag12` |
| 2 月春節跨月 | `lag_12m_cny_adj`：以歷史非春節同月平均取代被污染的 lag_12m |
| 中秋前置月被誤判 | `lead_1_mid_autumn=1` 時強制 `midautumn_shift_signal=0` |
| 合成的 macro 特徵無效 | `REAL_MACRO_FEATURES = []`（預設停用） |
| `load_macro.py` regex | `r"WD:(\d+)"`（曾誤寫成 `\\d`，造成 working_days 全為 NULL） |

### GIFT_HIGH 卡關原因

1. 2025 年 3–8 月比 2024 年系統性低 15–45%，但可用的 macro 指標是近似值
2. 春節跨月極端值：2025/02 實際 1.98M，lag_12m（2024/02 春節）是 7.37M；訓練資料只有一個類似案例
3. 2025 年中秋落在 10/6，9 月變成前置備貨月（76.2M，歷史最高），這種組合訓練資料裡從未出現

要再改善，需要真實的 CCI、百貨業 YoY、受雇薪資月資料。

## Macro 資料品質

- **真實**：`cpi_total/food`、`unemployment`、`twd_usd/jpy`、`inbound_tourists`、`bsi`（NDC 景氣對策信號，60/60）；`dept_store_yoy` / `retail_trade_yoy` 2024/04 起為 MOEA 真實值
- **近似**：`cci`（NCCU 站已下線）、`dept_store_yoy` 2021–2024/03（EE520 需登入）、`avg_wage_yoy`、`dept_store_sales`
- **代理**：`gift_market_sentiment`、`stock_wealth_effect`
- 零售業資料可從 MOEA EE521（`https://service.moea.gov.tw/EE521/visualize/VisDashboard.aspx?d=2`）取得，用 `Highcharts.charts[0].series` 擷取；百貨細目只有 EE520（需登入）和月報文字有
- 更新腳本：`scripts/scrape_final.py`（MOEA）、`scripts/fetch_ndc_full.py`（BSI）

## 業務規律

- 春節月銷售約為平月 3–5 倍（1 月或 2 月，看春節落點）；中秋月約 2–4 倍
- 2023 年門檻 760→850：GIFT_LOW 金額跳升，是牌價造成的，不是銷量
- 交叉驗算：任一月 GIFT_COMBINED = GIFT_LOW + GIFT_HIGH
