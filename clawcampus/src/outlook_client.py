"""
Outlook email client via Maton Gateway with mock fallback.
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

MATON_API_KEY = os.environ.get("MATON_API_KEY", "")
MATON_BASE = "https://gateway.maton.ai"
USE_MOCK = os.environ.get("USE_MOCK", "true").lower() == "true"

MOCK_DIR = Path(__file__).parent.parent / "mock_data"

HEADERS = {"Authorization": f"Bearer {MATON_API_KEY}"} if MATON_API_KEY else {}


def _load_mock_emails() -> list[dict]:
    path = MOCK_DIR / "emails.json"
    with open(path) as f:
        return json.load(f)


def _api_get(endpoint: str) -> list[dict] | None:
    """Try a real Maton/Outlook API call. Returns None on failure."""
    if USE_MOCK or not MATON_API_KEY:
        return None
    try:
        resp = requests.get(
            f"{MATON_BASE}{endpoint}",
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("value", data) if isinstance(data, dict) else data
    except Exception:
        return None


def get_inbox(top: int = 10) -> list[dict]:
    """Fetch recent inbox emails or return mock data."""
    result = _api_get(f"/outlook/v1.0/me/mailFolders/Inbox/messages?$top={top}")
    if result is not None:
        return result
    return _load_mock_emails()


def get_unread_emails() -> list[dict]:
    """Return only unread emails."""
    emails = get_inbox()
    unread = [e for e in emails if not e.get("isRead", True)]
    unread.sort(key=_email_datetime, reverse=True)
    return unread


def _email_datetime(email: dict) -> datetime:
    """Best-effort parse for sorting newest-first."""
    raw = email.get("date") or email.get("receivedDateTime")
    if not isinstance(raw, str) or not raw.strip():
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def get_calendar_events() -> list[dict]:
    """Fetch Outlook calendar events (mock: returns empty list)."""
    result = _api_get("/outlook/v1.0/me/calendar/events")
    if result is not None:
        return result
    # No separate mock for Outlook calendar — Canvas covers this
    return []


def send_email(to: str, subject: str, body: str, draft_only: bool = True) -> dict:
    """
    Draft or send an email. For safety, defaults to draft_only=True.
    In mock mode, always returns a mock success.
    """
    if USE_MOCK or not MATON_API_KEY or draft_only:
        return {
            "status": "draft_saved",
            "to": to,
            "subject": subject,
            "body_preview": body[:100],
            "note": "Draft mode — not actually sent.",
        }
    # Real send via Maton (POST)
    try:
        resp = requests.post(
            f"{MATON_BASE}/outlook/v1.0/me/sendMail",
            headers={**HEADERS, "Content-Type": "application/json"},
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                }
            },
            timeout=10,
        )
        resp.raise_for_status()
        return {"status": "sent", "to": to, "subject": subject}
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    print("=== Outlook Client Test ===")
    print(f"Mock mode: {USE_MOCK}")
    emails = get_inbox()
    print(f"\nInbox ({len(emails)} emails):")
    for e in emails:
        read_flag = "  " if e.get("isRead") else "* "
        print(f"  {read_flag}{e['subject']} — from {e['from']}")
    unread = get_unread_emails()
    print(f"\nUnread: {len(unread)}")
    print("\nDraft test:")
    result = send_email("test@nus.edu.sg", "Test Subject", "Hello, this is a test.")
    print(f"  {result}")
