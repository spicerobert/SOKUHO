#!/usr/bin/env python
"""Send SOKUHO sync result email (success, warnings, or failure)."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl import loader as db
from etl.gmail_notify import send_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_NOTIFY_EMAIL = "robert@auntstella.com.tw"
WARN_PATTERNS = re.compile(
    r"WARNING|ERROR|Unknown store|Skipping unknown|SKIPPED DAY|FAILED|失敗|警告",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send SOKUHO sync notification email")
    p.add_argument("--exit-code", type=int, required=True)
    p.add_argument("--log-file", type=str, default=None)
    p.add_argument("--error-message", type=str, default=None)
    p.add_argument("--lookback-minutes", type=int, default=60)
    return p.parse_args()


def _read_log_warnings(log_file: Path | None) -> list[str]:
    if not log_file or not log_file.exists():
        return []
    lines: list[str] = []
    for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if WARN_PATTERNS.search(line):
            lines.append(line.strip())
    return lines[-20:]


def _fetch_recent_etl_log(conn, lookback_minutes: int) -> list[dict]:
    since = datetime.now() - timedelta(minutes=lookback_minutes)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT report_date, source_file, status, records_loaded, error_message, run_at
            FROM etl_log
            WHERE run_at >= ?
            ORDER BY run_at DESC
            """,
            since,
        )
        rows = cur.fetchall()
    return [
        {
            "report_date": row.report_date,
            "source_file": row.source_file,
            "status": row.status,
            "records_loaded": row.records_loaded,
            "error_message": row.error_message,
            "run_at": row.run_at,
        }
        for row in rows
    ]


def _fetch_max_report_date(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(report_date) FROM fact_sales WHERE record_type = 'DAILY'")
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def _build_subject(exit_code: int, etl_rows: list[dict], log_warnings: list[str]) -> str:
    if exit_code != 0:
        return "[SOKUHO 失敗] 每日同步異常"

    issues = [
        r for r in etl_rows
        if r["status"] in ("FAILED", "SKIPPED") or r["error_message"]
    ]
    if issues or log_warnings:
        return "[SOKUHO 警告] 同步完成但有異常需留意"

    max_date = next((r["report_date"] for r in etl_rows if r["report_date"]), None)
    if max_date:
        return f"[SOKUHO 完成] 同步成功（最新 {max_date}）"
    return "[SOKUHO 完成] 同步成功"


def _build_body(
    *,
    exit_code: int,
    error_message: str | None,
    log_warnings: list[str],
    etl_rows: list[dict],
    max_daily_date,
) -> str:
    lines = ["SOKUHO 每日自動同步報告", "=" * 40, ""]

    if exit_code != 0:
        lines.append("狀態：失敗")
        if error_message:
            lines.append(f"錯誤：{error_message}")
    elif any(r["status"] == "FAILED" for r in etl_rows) or log_warnings:
        lines.append("狀態：完成但有警告")
    else:
        lines.append("狀態：成功")

    lines.append(f"fact_sales 最新 DAILY 日期：{max_daily_date or '（無資料）'}")
    lines.append("")

    if etl_rows:
        lines.append("本次 etl_log（近 1 小時）：")
        for row in etl_rows:
            note = f" — {row['error_message']}" if row["error_message"] else ""
            lines.append(
                f"  {row['run_at']}  {row['report_date']}  {row['status']}  "
                f"{row['source_file']}  ({row['records_loaded']} rows){note}"
            )
        lines.append("")
    else:
        lines.append("本次 etl_log：無新匯入紀錄（可能無新信件或已全部匯入）")
        lines.append("")

    unknown_notes = [
        r["error_message"] for r in etl_rows
        if r.get("error_message") and "Unknown stores" in r["error_message"]
    ]
    if unknown_notes:
        lines.append("未知門市／通路（請更新 db/seed_stores.sql 後重跑）：")
        for note in unknown_notes:
            lines.append(f"  {note}")
        lines.append("")

    if log_warnings:
        lines.append("日誌警告摘要：")
        for line in log_warnings:
            lines.append(f"  {line}")
        lines.append("")

    lines.append("日誌路徑：E:\\Git\\SOKUHO\\logs\\")
    lines.append("")
    lines.append("— PosInsight SOKUHO 自動同步")
    return "\n".join(lines)


def main() -> None:
    load_dotenv()
    args = parse_args()
    notify_to = os.environ.get("NOTIFY_EMAIL", DEFAULT_NOTIFY_EMAIL)
    log_file = Path(args.log_file) if args.log_file else None
    log_warnings = _read_log_warnings(log_file)

    exit_code = args.exit_code
    error_message = args.error_message
    etl_rows: list[dict] = []
    max_daily_date = None
    try:
        conn = db.get_connection(
            server=os.environ["DB_SERVER"],
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )
        etl_rows = _fetch_recent_etl_log(conn, args.lookback_minutes)
        max_daily_date = _fetch_max_report_date(conn)
        conn.close()
    except Exception as exc:
        logger.warning("無法查詢 DB 以組成郵件內容：%s", exc)
        if exit_code == 0:
            exit_code = 1
            error_message = error_message or str(exc)

    subject = _build_subject(exit_code, etl_rows, log_warnings)
    body = _build_body(
        exit_code=exit_code,
        error_message=error_message,
        log_warnings=log_warnings,
        etl_rows=etl_rows,
        max_daily_date=max_daily_date,
    )

    try:
        send_email(to=notify_to, subject=subject, body=body)
        logger.info("已寄送通知至 %s（%s）", notify_to, subject)
    except Exception as exc:
        logger.error("寄送通知失敗：%s", exc)
        logger.error(
            "若為 OAuth 權限問題，請執行：uv run python scripts/send_sync_notification.py "
            "--exit-code 0 --log-file logs/sokuho_sync_YYYYMMDD.log 以重新授權 gmail.send"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
