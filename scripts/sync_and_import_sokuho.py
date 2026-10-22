#!/usr/bin/env python
r"""
Gmail → OneDrive → SQL Server 一條龍同步。

1. 查 DB 取得 fact_sales 最後已匯入的 report_date（增量基準）。
2. 用該日期組出 Gmail 搜尋範圍（after:YYYY/MM/DD），只掃描新信件，不做全信箱搜尋。
3. 下載主旨含 SOKUHO 的 PDF 附件到 PDF_DIR\<year>\<yyyymm>\（沿用既有資料夾慣例，已存在的檔案跳過）。
   主旨可為單日（SOKUHO YYYY.MM.DD）或範圍（SOKUHO YYYY.MM.DD~YYYY.MM.DD / YYYY.MM.DD-MM.DD）；
   附件檔名仍是逐日拆開的 SOKUHO YYYY.MM.DD.pdf。
4. 呼叫 main.py 匯入新下載範圍內的日期。

寄件者不只 bellecheng：代班時可能是 mantsu@ / billy@ 等（見 SOKUHO_GMAIL_SENDERS）。

首次執行會開瀏覽器要求用 robert@auntstella.com.tw 登入 Google 授權一次；
之後 token 快取在 auth/token.json，不需要再登入。

Usage:
  uv run python scripts/sync_and_import_sokuho.py
  uv run python scripts/sync_and_import_sokuho.py --dry-run   # 只下載不匯入 DB
  uv run python scripts/sync_and_import_sokuho.py --since 2026-01-01  # 手動覆寫增量基準
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl import loader as db
from etl.gmail_auth import get_gmail_service
from etl.pdf_parser import parse_date_from_filename

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 正常寄件人 + 代班寄件人。可用環境變數 SOKUHO_GMAIL_SENDERS（逗號分隔）覆寫。
_DEFAULT_SENDERS = (
    "bellecheng@auntstella.com.tw,"
    "mantsu@auntstella.com.tw,"
    "billy@auntstella.com.tw"
)
GMAIL_SUBJECT_KEYWORD = "SOKUHO"

DEFAULT_PDF_DIR = r"E:\OneDrive - Aunt Stella Company\SOKUHO"


def gmail_senders() -> list[str]:
    raw = os.environ.get("SOKUHO_GMAIL_SENDERS", _DEFAULT_SENDERS)
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def gmail_from_clause(senders: list[str]) -> str:
    """Build Gmail `from:` clause; OR-group when multiple senders."""
    if not senders:
        raise ValueError("SOKUHO_GMAIL_SENDERS 不可為空")
    if len(senders) == 1:
        return f"from:{senders[0]}"
    return "(" + " OR ".join(f"from:{s}" for s in senders) + ")"


def require_database() -> None:
    """Fail fast with a clear hint when PosInsight is unreachable.

    資料庫在正式機的 integration_pos_db 容器內，本專案不負責啟動它；
    不可自動 docker compose up（曾經會在本機另起一個空庫）。
    """
    try:
        conn = db.get_connection(
            server=os.environ["DB_SERVER"],
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )
        conn.close()
    except db.DatabaseUnavailableError as exc:
        logger.error("%s", exc)
        sys.exit(1)


def get_last_imported_date(conn) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(report_date) FROM fact_sales")
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def get_loaded_dates(conn, dates: set[date]) -> set[date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT report_date FROM fact_sales WHERE report_date IN (%s)" % ",".join("?" * len(dates)),
            *sorted(dates),
        )
        return {row[0] for row in cur.fetchall()}


def list_sokuho_messages(service, since: date) -> list[dict]:
    """Search only messages received on/after `since` (incremental, not full-mailbox).

    Subject may be a single day or a multi-day range (``~`` / ``-``); filtering is by
    keyword SOKUHO + known senders, not by exact single-date subject shape.
    """
    senders = gmail_senders()
    query = (
        f'{gmail_from_clause(senders)} subject:{GMAIL_SUBJECT_KEYWORD} '
        f'has:attachment filename:SOKUHO after:{since.strftime("%Y/%m/%d")}'
    )
    logger.info("Gmail senders: %s", ", ".join(senders))
    logger.info("Gmail query: %s", query)
    messages: list[dict] = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, pageToken=page_token
        ).execute()
        messages.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return messages


def _iter_parts(payload: dict):
    """Yield MIME parts depth-first (handles multipart/related nesting)."""
    yield payload
    for child in payload.get("parts") or []:
        yield from _iter_parts(child)


def download_attachments(service, messages: list[dict], pdf_dir: Path) -> set[date]:
    """Download new PDF attachments; return report_dates found (downloaded now or already on disk).

    main.py's own etl_log check makes re-importing already-loaded dates a no-op, so it's
    safe (and necessary) to include already-downloaded dates in the returned set — otherwise
    a re-run after a partial failure would never re-trigger the DB import step.
    """
    found_dates: set[date] = set()
    for meta in messages:
        msg = service.users().messages().get(userId="me", id=meta["id"], format="full").execute()
        for part in _iter_parts(msg.get("payload", {}) or {}):
            filename = part.get("filename") or ""
            if not filename.lower().endswith(".pdf"):
                continue
            if "SOKUHO" not in filename.upper():
                continue
            report_date = parse_date_from_filename(filename)
            if report_date is None:
                logger.warning("Skip attachment (unparseable date): %s", filename)
                continue

            month_dir = pdf_dir / str(report_date.year) / f"{report_date.year}{report_date.month:02d}"
            month_dir.mkdir(parents=True, exist_ok=True)
            dest = month_dir / filename
            found_dates.add(report_date)
            if dest.exists():
                logger.debug("Already downloaded, skip: %s", dest)
                continue

            body = part.get("body", {})
            attachment_id = body.get("attachmentId")
            if attachment_id:
                att = service.users().messages().attachments().get(
                    userId="me", messageId=meta["id"], id=attachment_id
                ).execute()
                data = att["data"]
            else:
                data = body.get("data")
                if not data:
                    continue

            dest.write_bytes(base64.urlsafe_b64decode(data))
            logger.info("Downloaded: %s", dest)
    return found_dates


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gmail → OneDrive → SQL Server SOKUHO 同步")
    p.add_argument("--pdf-dir", default=os.environ.get("PDF_DIR", DEFAULT_PDF_DIR))
    p.add_argument("--since", type=str, default=None, help="覆寫增量基準日期 (YYYY-MM-DD)，預設用 DB 最後匯入日期")
    p.add_argument("--dry-run", action="store_true", help="只下載附件，不呼叫 main.py 匯入")
    return p.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    pdf_dir = Path(args.pdf_dir)

    # --since + --dry-run 不需 DB；其餘情況先檢查，避免跑到一半才失敗。
    if not (args.since and args.dry_run):
        require_database()

    if args.since:
        since = date.fromisoformat(args.since)
    else:
        conn = db.get_connection(
            server=os.environ["DB_SERVER"],
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )
        last_date = get_last_imported_date(conn)
        conn.close()
        if last_date is None:
            logger.error("fact_sales 是空的，無法判斷增量基準，請先用 --since 指定日期。")
            sys.exit(1)
        since = last_date
        logger.info("DB 最後匯入日期：%s", last_date)

    service = get_gmail_service()
    messages = list_sokuho_messages(service, since)
    logger.info("找到 %d 封符合條件的信件（after %s）", len(messages), since)
    if not messages:
        logger.info("沒有新信件，結束。")
        return

    found_dates = download_attachments(service, messages, pdf_dir)
    if not found_dates:
        logger.info("沒有可用附件，結束。")
        return

    # 只匯入還沒進 DB 的日期、一天一跑：用 min~max 一整段時，信箱裡一封補寄的舊報表
    # （2026-10-22：3/30 那封）會把 200 多個已匯入的檔重新解析一遍，舊檔的 parser 警告就觸發誤報信。
    if not (args.since and args.dry_run):
        conn = db.get_connection(
            server=os.environ["DB_SERVER"],
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )
        found_dates -= get_loaded_dates(conn, found_dates)
        conn.close()
    if not found_dates:
        logger.info("附件的日期都已匯入，結束。")
        return
    logger.info("待匯入 %d 個日期：%s", len(found_dates), ", ".join(d.isoformat() for d in sorted(found_dates)))

    rc = 0
    for d in sorted(found_dates):
        cmd = [
            sys.executable, "main.py",
            "--pdf-dir", str(pdf_dir),
            "--from-date", d.isoformat(),
            "--to-date", d.isoformat(),
        ]
        if args.dry_run:
            cmd.append("--dry-run")
        logger.info("執行匯入：%s", " ".join(cmd))
        rc = rc or subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent).returncode
    sys.exit(rc)


if __name__ == "__main__":
    main()
