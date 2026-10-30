# CLAUDE.md

**PosInsight**：詩特莉食品銷售數據平台。三個子系統共用 SQL Server 的 `PosInsight` 庫，Python 一律用 `uv`。

**資料庫在正式機**：位於 Integration_of_POS 的容器 `integration_pos_db`（port 1434，compose 由 Integration_of_POS 管理），連線用 `.env` 的專用帳號，不用 sa。主機、帳號、備份路徑一律放 `.env`，不寫進 repo。本專案沒有自己的 Docker；不要加回自動 `docker compose up`，那會在本機另起一個空庫。開發機已淘汰（2026-10-21 起收信／解析／入庫／上雲都在正式機 .120），不要再派工或連到開發機的庫。搬遷交接紀錄放在備份共用資料夾的 `HANDOFF.md`（路徑見 `.env` 的 `SOKUHO_BAK_DEST`），不進 git。

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

排程只在正式機上跑；開發機（筆電）的排程已於 2026-10-22 刪除，不要在開發機重新註冊，兩邊同時跑會重複匯入、重複寄信：
- 每日 11:00「SOKUHO Daily Sync」跑 `scripts/scheduled_sync_sokuho.ps1`（Gmail 同步 → 匯入，日誌在 `logs/`；只有真正失敗或異常才寄信通知）。訂 11:00 是因為 FIN 約 9 點寄報表。註冊：`scripts/register_sokuho_scheduled_task.ps1`。
- 每日 06:30「SOKUHO - 每日 .bak 備份」跑 `scripts/backup_sokuho_db.py`，備份到 `.env` 的 `SOKUHO_BAK_DEST`，保留 30 份。註冊：`scripts/register_sokuho_backup_task.ps1`。
- 下游的 11:15 雲端同步（`sokuho_daily` → Drive／BigQuery）也在正式機上，但不屬於本 repo；改 11:00 的同步時間時要一起考慮它。

確認排程有沒有跑：`etl_log.run_at` 是 UTC，台灣時間要 +8 小時（11:00 的排程寫入的是 `03:0x`）。

**`PosInsight` 與正式庫 `POS` 在同一個容器**：不對它做 DROP／TRUNCATE／沒有 WHERE 的 DELETE 來測試或除錯；規則全文見 `E:\Git\Integration_of_POS\.claude\rules\destructive-db-operations.md`。

`GMAIL_LOGIN_HINT`、`EDGE_PROFILE_DIR`、`NOTIFY_EMAIL` 只能由 `.env` 提供，不要在 ps1 設預設值：`load_dotenv()` 不覆蓋既有環境變數，ps1 先設了 `.env` 就失效。

## 往哪裡找

| 主題 | 在哪 |
|---|---|
| SOKUHO 解析、補值、overrides、Gmail 同步陷阱（改 `scripts/sync_and_import_sokuho.py` 也要讀） | `etl/CLAUDE.md` |
| KOUSEIHI ETL、禮盒分析預測、Macro、業務規律 | `skill kouseihi-gift-forecast` |
| 上雲（`sokuho_daily`） | Integration_of_POS 的 `cloud_sync/CLAUDE.md` |
