"""
Gmail email client via Gmail API with mock fallback.
"""
from __future__ import annotations

import base64
import json
import os
import re
from email.header import decode_header
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

USE_MOCK = os.environ.get("USE_MOCK", "true")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
ROOT_DIR = Path(__file__).parent.parent
MOCK_PATH = ROOT_DIR / "mock_data" / "emails.json"
CREDENTIALS_PATH = ROOT_DIR / "credentials.json"
TOKEN_PATH = ROOT_DIR / "token.json"


def _use_mock() -> bool:
    return USE_MOCK.lower() == "true"


def _load_mock_emails(max_results: int | None = None, unread_only: bool = False) -> list[dict]:
    with open(MOCK_PATH) as f:
        emails = json.load(f)

    normalized = []
    for email in emails:
        normalized.append({
            "id": email.get("id", ""),
            "subject": email.get("subject", ""),
            "sender": email.get("sender", email.get("from", "")),
            "date": email.get("date", ""),
            "snippet": email.get("snippet", email.get("body", "")[:160].strip()),
            "body": re.sub(r"\s+", " ", email.get("body", "")).strip(),
            "isRead": email.get("isRead", True),
        })

    if unread_only:
        normalized = [email for email in normalized if not email.get("isRead", True)]
    if max_results is not None:
        normalized = normalized[:max_results]
    return normalized


def _decode_header_value(value: str) -> str:
    if not value:
        return ""

    parts = []
    for decoded, encoding in decode_header(value):
        if isinstance(decoded, bytes):
            parts.append(decoded.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(decoded)
    return "".join(parts).strip()


def _decode_body_data(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode(data + padding)
    return decoded.decode("utf-8", errors="replace")


def _extract_text_plain(payload: dict | None) -> str:
    if not payload:
        return ""

    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")
    filename = payload.get("filename")

    if mime_type == "text/plain" and body_data and not filename:
        return _decode_body_data(body_data)

    for part in payload.get("parts", []):
        text = _extract_text_plain(part)
        if text:
            return text

    if mime_type == "text/plain" and body_data:
        return _decode_body_data(body_data)

    return ""


def _get_header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return _decode_header_value(header.get("value", ""))
    return ""


def _normalize_message(message: dict) -> dict:
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    body = _extract_text_plain(payload)
    body = re.sub(r"\s+", " ", body).strip()

    return {
        "id": message.get("id", ""),
        "subject": _get_header(headers, "Subject"),
        "sender": _get_header(headers, "From"),
        "date": _get_header(headers, "Date"),
        "snippet": message.get("snippet", "").strip(),
        "body": body,
    }


def get_service():
    """Authenticate and return a Gmail API service object.
    Load token.json if it exists, otherwise run OAuth flow from credentials.json.
    Save token.json after auth.
    """
    if _use_mock():
        return None

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def fetch_recent_emails(service, max_results=10):
    """
    Fetch the most recent `max_results` emails from the inbox.
    For each email, return a dict with:
    - id: message id
    - subject: decoded subject header
    - sender: decoded From header
    - date: decoded Date header
    - snippet: Gmail snippet (short preview)
    - body: full plain-text body (decode from base64, prefer text/plain part)

    Handle multipart emails. Strip excessive whitespace from body.
    Return list of dicts.
    """
    if _use_mock():
        return _load_mock_emails(max_results=max_results)

    response = service.users().messages().list(
        userId="me",
        labelIds=["INBOX"],
        maxResults=max_results,
    ).execute()
    messages = response.get("messages", [])

    emails = []
    for message in messages:
        details = service.users().messages().get(
            userId="me",
            id=message["id"],
            format="full",
        ).execute()
        emails.append(_normalize_message(details))
    return emails


def fetch_unread_emails(service, max_results=10):
    """Same as fetch_recent_emails but filtered to UNREAD messages only (label: UNREAD)."""
    if _use_mock():
        return _load_mock_emails(max_results=max_results, unread_only=True)

    response = service.users().messages().list(
        userId="me",
        labelIds=["INBOX", "UNREAD"],
        maxResults=max_results,
    ).execute()
    messages = response.get("messages", [])

    emails = []
    for message in messages:
        details = service.users().messages().get(
            userId="me",
            id=message["id"],
            format="full",
        ).execute()
        emails.append(_normalize_message(details))
    return emails


if __name__ == "__main__":
    service = get_service()
    emails = fetch_recent_emails(service, max_results=5)
    for email in emails:
        print(f"{email['subject']} — {email['sender']}")
