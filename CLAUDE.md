# CLAUDE.md

**PosInsight**：詩特莉食品銷售數據平台。三個子系統共用 SQL Server（PosInsight，Docker），Python 一律用 `uv`。

| 子系統 | 資料來源 | 產出 |
|--------|---------|------|
| SOKUHO ETL | 每日 PDF 速報（Gmail 附件） | `fact_sales` |
| KOUSEIHI ETL | 構成比 PDF 報表 | `fact_kouseihi_category` / `fact_kouseihi_kpi` |
| 禮盒分析預測 | `vw_gift_analysis_dataset` | `outputs/v2_*` |

## 常用指令

```bash
cp .env.example .env && uv sync

# SOKUHO
uv run python main.py --from-date 2026-03-01 --to-date 2026-03-31 [--force] [--dry-run]
uv run python scripts/sync_and_import_sokuho.py [--dry-run] [--since 2026-01-01]   # Gmail 搜尋→下載→分類→匯入

# KOUSEIHI
uv run python scripts/import_kouseihi_from_pdf.py --pdf "<path>.pdf" --year 2025 --month-start 1 --month-end 12 [--force]
uv run python scripts/verify_kouseihi_import.py

# 禮盒分析
uv run python scripts/build_gift_dataset.py            # view → data/gift_analysis_dataset.csv
uv run python scripts/run_gift_analysis_v2.py [--from-csv]

# macro
uv run python scripts/scrape_final.py && uv run python scripts/load_macro.py --raw-dir data/macro_raw
```

每日 12:00 由 Windows 工作排程器「SOKUHO Daily Sync」跑 `scripts/scheduled_sync_sokuho.ps1`（啟動 Docker → Gmail 同步 → 匯入，日誌在 `logs/`；只有真正失敗或異常才寄信通知）。註冊：`scripts/register_sokuho_scheduled_task.ps1`。

## SOKUHO ETL

`etl/pdf_parser.py` → `etl/transformer.py` → `etl/loader.py`；非標準 PDF 的覆寫設定在 `etl/sokuho_import_overrides.yaml`。

PDF 格式依各頁門市數判斷，門市版面一改就要新增格式：

| 格式 | P1 | P2 | 適用時期 |
|------|----|----|---------|
| A | 17 | 10 | 10 月 |
| B | 17 | 8  | 11/1–5 |
| D | 17 | 11 | 11/6–10 |
| C | 19 | 9  | 11/11+（CL SOGO B1、Taichung Mitsukoshi 上移 P1） |
| E | 20 | 11 | 2026-05+（Tian-Mu Mitsukoshi、Hanshin Kaohsiung 上移 P1；P2 為 Costco/Anhe/BD） |
| F | 20 | 13 | 2026-08-22+（P2 新增 Taipei Dome 1079 台北大巨蛋、New Store Sales；**不是** 1041 Dome Hanshin 高雄巨蛋漢神） |

- `fact_sales` 唯一鍵：`(report_date, store_id, record_type)`；`dim_store.store_type` = `store`/`subtotal`/`grand_total`/`HQ`
- **人事費欄位強制寫 NULL**（`load_dataframe`），避免 DAX 誤用
- 門市名稱正規化：Unicode 連字號 → `-`；`ALL 17/19 STORES` → `ALL 18 STORES`；`BD` → `Business Development`

### Gmail 同步陷阱

- `auth/credentials.json`（OAuth installed-app，project `pipeline-499103`）、`auth/token.json` 皆被 gitignore，不可提交
- 增量基準是 `fact_sales` 的 `MAX(report_date)`，只搜 `after:<基準日>`，**不會往回看**；漏抓時用 `--since <缺口前一日>` 回補
- 寄件人：`bellecheng@` / `mantsu@`（代班）/ `billy@`，可用 `SOKUHO_GMAIL_SENDERS` 覆寫；只搜 bellecheng 會漏信
- 主旨可能是日期範圍（`2026.07.03-07.05`、`2026.06.18~2026.06.21`），但附件一定是逐日的 `SOKUHO YYYY.MM.DD.pdf`；解析依附件檔名，存到 `PDF_DIR\<year>\<yyyymm>\`

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
