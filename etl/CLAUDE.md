# etl/ — SOKUHO 解析與入庫

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

- `fact_sales` 唯一鍵：`(report_date, store_id, record_type)`；`dim_store.store_type` = `store`/`BD`/`SR`/`Web`/`HQ`/`internal`（8001 CF）/`subtotal`/`grand_total`
- **人事費欄位強制寫 NULL**（`load_dataframe`），避免 DAX 誤用
- 門市名稱正規化：Unicode 連字號 → `-`；`ALL 17/19 STORES` → `ALL 18 STORES`；`BD` → `Business Development`
- 單日列和月累計列依店名配對（`_pair_rows`），不依位置；列數不符只記 info，有孤兒列才發 WARNING
- 單日為 0 或缺列、當天客數 > 0 時，`derive_daily_from_mtd` 用月累計差補單日，標 `value_source='DERIVED'`；客數 0 是入帳調整，不補（view 的 `adjustment` 欄）
- `--force` 只刪 (report_date, source_file)：改 overrides 換檔重載後，要查該日已經沒有舊 source_file 的列
- `dim_store` 的英文名／簡稱和 Integration_of_POS `posinsight.dim_store` 同代號同名（4004 Duty Free／DF、4011 BD），改一邊要改兩邊

## Gmail 同步陷阱（`scripts/sync_and_import_sokuho.py`、`etl/gmail_auth.py`）

- `auth/credentials.json`（OAuth installed-app，project `pipeline-499103`）、`auth/token.json` 皆被 gitignore，不可提交
- 增量基準是 `fact_sales` 的 `MAX(report_date)`，只搜 `after:<基準日>`，**不會往回看**；漏抓時用 `--since <缺口前一日>` 回補
- 寄件人：`bellecheng@` / `mantsu@`（代班）/ `billy@`，可用 `SOKUHO_GMAIL_SENDERS` 覆寫；只搜 bellecheng 會漏信
- 主旨可能是日期範圍（`2026.07.03-07.05`、`2026.06.18~2026.06.21`），但附件一定是逐日的 `SOKUHO YYYY.MM.DD.pdf`；解析依附件檔名，存到 `PDF_DIR\<year>\<yyyymm>\`
