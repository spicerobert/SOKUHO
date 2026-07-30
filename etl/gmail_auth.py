"""Shared Gmail OAuth for SOKUHO sync (read) and notifications (send)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
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

_DEFAULT_WORK_EMAIL = "robert@auntstella.com.tw"
_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_WORK_BROWSER_NAME = "edge-work"
_EDGE_USER_DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data"


def work_email() -> str:
    """Company Gmail used for OAuth hint + mailbox assertion (read at call time)."""
    return os.environ.get("GMAIL_LOGIN_HINT", _DEFAULT_WORK_EMAIL).strip().lower()


# Back-compat for callers that imported WORK_EMAIL as a constant.
WORK_EMAIL = _DEFAULT_WORK_EMAIL


def resolve_edge_profile_dir() -> str:
    """Resolve Edge profile folder for the company Gmail account.

    Priority:
    1. EDGE_PROFILE_DIR env (explicit override)
    2. Scan Edge Local State for company email
    3. Fallback ``Profile 1`` (this machine's current Work profile)
    """
    explicit = (os.environ.get("EDGE_PROFILE_DIR") or "").strip()
    if explicit:
        return explicit

    expected = work_email()
    local_state = _EDGE_USER_DATA / "Local State"
    if local_state.exists():
        try:
            data = json.loads(local_state.read_text(encoding="utf-8"))
            info = (data.get("profile") or {}).get("info_cache") or {}
            for folder, meta in info.items():
                email = str((meta or {}).get("user_name") or "").strip().lower()
                if email == expected:
                    logger.info(
                        "由 Edge Local State 對應公司信箱 %s → 設定檔 '%s'",
                        expected,
                        folder,
                    )
                    return folder
        except Exception as exc:  # noqa: BLE001
            logger.warning("讀取 Edge Local State 失敗：%s", exc)

    logger.warning(
        "找不到公司信箱 %s 的 Edge 設定檔，改用預設 'Profile 1'。"
        "請設定環境變數 EDGE_PROFILE_DIR。",
        expected,
    )
    return "Profile 1"


def _register_work_browser() -> str | None:
    """Register an Edge controller pinned to the company profile.

    Returns the webbrowser name to pass to run_local_server(browser=...),
    or None to fall back to the system default browser.
    """
    edge = next((p for p in _EDGE_CANDIDATES if Path(p).exists()), None) or shutil.which("msedge")
    if not edge:
        logger.warning("找不到 Edge，改用系統預設瀏覽器開啟授權頁（可能落到錯誤設定檔）。")
        return None
    profile_dir = resolve_edge_profile_dir()
    expected = work_email()
    try:
        webbrowser.register(
            _WORK_BROWSER_NAME,
            None,
            webbrowser.BackgroundBrowser(
                [edge, f"--profile-directory={profile_dir}", "%s"]
            ),
        )
        logger.info("授權頁將以 Edge 設定檔 '%s'（%s）開啟。", profile_dir, expected)
        return _WORK_BROWSER_NAME
    except Exception as exc:  # noqa: BLE001
        logger.warning("註冊 Edge 設定檔瀏覽器失敗（%s），改用系統預設瀏覽器。", exc)
        return None


def _assert_work_mailbox(service) -> None:
    """Fail fast if the authorized Gmail account is not the company mailbox."""
    expected = work_email()
    profile = service.users().getProfile(userId="me").execute()
    email = str(profile.get("emailAddress") or "").strip().lower()
    logger.info("Gmail API 目前帳號：%s", email)
    if email != expected:
        raise RuntimeError(
            f"Gmail 授權帳號錯誤：目前為 {email or '(unknown)'}，"
            f"預期為公司信箱 {expected}。"
            f"請刪除 {TOKEN_PATH} 後重新執行，並在 Edge 公司設定檔登入授權。"
        )


def get_gmail_service():
    # Ensure .env values (GMAIL_LOGIN_HINT / EDGE_PROFILE_DIR) are visible
    # even when this module was imported before the caller ran load_dotenv().
    load_dotenv()
    global WORK_EMAIL
    WORK_EMAIL = work_email()

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
            browser=browser_name,  # None → 系統預設瀏覽器（fallback）
            login_hint=WORK_EMAIL,  # 預選公司帳號，避免選到個人帳號
            prompt="consent",  # 確保回傳 refresh_token
        )

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    service = build("gmail", "v1", credentials=creds)
    _assert_work_mailbox(service)
    return service
