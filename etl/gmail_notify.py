"""Send notification emails via Gmail API."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText

from etl.gmail_auth import get_gmail_service


def send_email(*, to: str, subject: str, body: str) -> None:
    message = MIMEText(body, _charset="utf-8")
    message["to"] = to
    message["from"] = "me"
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service = get_gmail_service()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
