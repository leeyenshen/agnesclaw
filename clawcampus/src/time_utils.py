"""
Shared timezone/date helpers for ClawCampus.
Defaults to Asia/Singapore unless APP_TIMEZONE is set.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Singapore"


def get_local_tz() -> ZoneInfo:
    """Return configured local timezone, with safe fallback."""
    tz_name = os.environ.get("APP_TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def now_local() -> datetime:
    """Current time in local timezone."""
    return datetime.now(get_local_tz())


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime string into an aware datetime."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
