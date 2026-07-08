#!/usr/bin/env python
r"""
Gmail → OneDrive → SQL Server 一條龍同步。

1. 查 DB 取得 fact_sales 最後已匯入的 report_date（增量基準）。
2. 用該日期組出 Gmail 搜尋範圍（after:YYYY/MM/DD），只掃描新信件，不做全信箱搜尋。
3. 下載主旨符合 "SOKUHO YYYY.MM.DD" 的 PDF 附件到 PDF_DIR\<year>\<yyyymm>\（沿用既有資料夾慣例，已存在的檔案跳過）。
4. 呼叫 main.py 匯入新下載範圍內的日期。

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
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl import loader as db
from etl.pdf_parser import parse_date_from_filename

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

AUTH_DIR = Path(__file__).resolve().parent.parent / "auth"
CREDENTIALS_PATH = AUTH_DIR / "credentials.json"
TOKEN_PATH = AUTH_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

GMAIL_SENDER = "bellecheng@auntstella.com.tw"
GMAIL_SUBJECT_KEYWORD = "SOKUHO"

DEFAULT_PDF_DIR = r"E:\OneDrive - Aunt Stella Company\SOKUHO"


def require_database() -> None:
    """Fail fast with a clear hint when Docker / PosInsight is not running."""
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


def get_gmail_service():
    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


def get_last_imported_date(conn) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(report_date) FROM fact_sales")
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def list_sokuho_messages(service, since: date) -> list[dict]:
    """Search only messages received on/after `since` (incremental, not full-mailbox)."""
    query = (
        f'from:{GMAIL_SENDER} subject:{GMAIL_SUBJECT_KEYWORD} has:attachment '
        f'after:{since.strftime("%Y/%m/%d")}'
    )
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


def download_attachments(service, messages: list[dict], pdf_dir: Path) -> set[date]:
    """Download new PDF attachments; return report_dates found (downloaded now or already on disk).

    main.py's own etl_log check makes re-importing already-loaded dates a no-op, so it's
    safe (and necessary) to include already-downloaded dates in the returned set — otherwise
    a re-run after a partial failure would never re-trigger the DB import step.
    """
    found_dates: set[date] = set()
    for meta in messages:
        msg = service.users().messages().get(userId="me", id=meta["id"], format="full").execute()
        for part in msg.get("payload", {}).get("parts", []) or []:
            filename = part.get("filename") or ""
            if not filename.lower().endswith(".pdf"):
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

    from_date = min(found_dates)
    to_date = max(found_dates)
    logger.info("附件就緒，共 %d 個日期，範圍 %s ~ %s，開始匯入", len(found_dates), from_date, to_date)

    cmd = [
        sys.executable, "main.py",
        "--pdf-dir", str(pdf_dir),
        "--from-date", from_date.isoformat(),
        "--to-date", to_date.isoformat(),
    ]
    if args.dry_run:
        cmd.append("--dry-run")

    logger.info("執行匯入：%s", " ".join(cmd))
    result = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
