"""Shared Gmail OAuth for SOKUHO sync (read) and notifications (send)."""

from __future__ import annotations

import logging
import os
import shutil
import webbrowser
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

AUTH_DIR = Path(__file__).resolve().parent.parent / "auth"
CREDENTIALS_PATH = AUTH_DIR / "credentials.json"
TOKEN_PATH = AUTH_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# SOKUHO 需要存取「公司」Gmail。此帳號透過 login_hint 傳給 Google，授權頁會預選它。
WORK_EMAIL = os.environ.get("GMAIL_LOGIN_HINT", "robert@auntstella.com.tw")

# Edge 多設定檔環境下，強制用「Work」設定檔開授權頁，避免落到個人設定檔。
# 可用環境變數覆寫；找不到 Edge 時會自動退回系統預設瀏覽器。
EDGE_PROFILE_DIR = os.environ.get("EDGE_PROFILE_DIR", "Profile 1")
_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_WORK_BROWSER_NAME = "edge-work"


def _register_work_browser() -> str | None:
    """Register an Edge controller pinned to the company profile.

    Returns the webbrowser name to pass to run_local_server(browser=...),
    or None to fall back to the system default browser.
    """
    edge = next((p for p in _EDGE_CANDIDATES if Path(p).exists()), None) or shutil.which("msedge")
    if not edge:
        logger.warning("找不到 Edge，改用系統預設瀏覽器開啟授權頁（可能落到錯誤設定檔）。")
        return None
    try:
        webbrowser.register(
            _WORK_BROWSER_NAME,
            None,
            webbrowser.BackgroundBrowser(
                [edge, f"--profile-directory={EDGE_PROFILE_DIR}", "%s"]
            ),
        )
        logger.info("授權頁將以 Edge 設定檔 '%s'（%s）開啟。", EDGE_PROFILE_DIR, WORK_EMAIL)
        return _WORK_BROWSER_NAME
    except Exception as exc:  # noqa: BLE001
        logger.warning("註冊 Edge 設定檔瀏覽器失敗（%s），改用系統預設瀏覽器。", exc)
        return None


def get_gmail_service():
    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))

    granted = set(creds.scopes or []) if creds else set()
    missing_scopes = set(SCOPES) - granted

    if creds and not missing_scopes and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid or missing_scopes:
        if missing_scopes:
            logger.info(
                "Gmail 需要重新授權（新增寄信權限）。將開啟瀏覽器，請用 %s 登入。",
                WORK_EMAIL,
            )
        browser_name = _register_work_browser()
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(
            port=0,
            browser=browser_name,      # None → 系統預設瀏覽器（fallback）
            login_hint=WORK_EMAIL,     # 預選公司帳號，避免選到個人帳號
            prompt="consent",          # 確保回傳 refresh_token
        )

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)
