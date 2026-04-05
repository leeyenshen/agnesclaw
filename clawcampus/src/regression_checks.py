#!/usr/bin/env python3
"""
Lightweight regression checks for key ClawCampus behaviors.

Run:
    python src/regression_checks.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

import finance_tracker
import memory_manager
from time_utils import get_local_tz

# Test-only stubs so this script can run without optional external deps.
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
if "requests" not in sys.modules:
    sys.modules["requests"] = types.SimpleNamespace(get=None, post=None)

import outlook_client


def _seed_memory(path: Path):
    path.write_text(
        """# ClawCampus Memory

Last updated: 2026-04-05T00:00:00+00:00

## Tasks
- {"title": "Subject: Test Notice
From: test@nus.edu.sg
Date", "course": null, "due_date": null, "type": "admin", "urgency": "info", "source": "email", "raw_snippet": "Subject: Test Notice
From: test@nus.edu.sg
Date: 2026-04-05", "extracted_at": "2026-04-05T00:00:00+00:00"}

## Courses

## Preferences

## Transactions

## Food Deals
""",
        encoding="utf-8",
    )


def test_memory_cleanup_and_dedup(tmpdir: Path):
    memory_manager.MEMORY_PATH = tmpdir / "MEMORY_cleanup.md"
    _seed_memory(memory_manager.MEMORY_PATH)

    changed = memory_manager.cleanup_memory()
    assert changed is True, "cleanup_memory should repair malformed task entries"

    tasks = memory_manager.get_all_tasks()
    assert len(tasks) == 1, "Expected repaired single task in memory"
    assert "\n" not in tasks[0].get("title", ""), "Task title should be normalized to one line"

    tx = {"merchant": "GrabFood", "amount": 12.29, "date": "2026-04-05", "category": "food"}
    assert memory_manager.add_transaction(tx) is True
    assert memory_manager.add_transaction(tx) is False, "Duplicate transaction must be skipped"
    assert len(memory_manager.get_transactions()) == 1


def test_weekly_filter(tmpdir: Path):
    memory_manager.MEMORY_PATH = tmpdir / "MEMORY_weekly.md"
    memory_manager.init_memory()

    recent = {"merchant": "Coffee", "amount": 4.5, "date": "2026-04-05", "category": "food"}
    old = {"merchant": "Old Expense", "amount": 30.0, "date": "2026-03-01", "category": "other"}
    memory_manager.add_transaction(recent)
    memory_manager.add_transaction(old)

    transactions = memory_manager.get_transactions()
    weekly = finance_tracker.get_weekly_transactions(
        transactions,
        now=datetime.fromisoformat("2026-04-05T12:00:00+08:00"),
    )
    assert len(weekly) == 1, "Only recent transaction should be counted in 7-day window"
    assert abs(weekly[0].get("amount", 0) - 4.5) < 1e-9


def test_latest_unread_sort():
    original_get_inbox = outlook_client.get_inbox
    try:
        outlook_client.get_inbox = lambda top=10: [
            {"subject": "older", "isRead": False, "date": "2026-04-01T10:00:00+08:00"},
            {"subject": "newest", "isRead": False, "date": "2026-04-05T10:00:00+08:00"},
            {"subject": "middle", "isRead": False, "date": "2026-04-03T10:00:00+08:00"},
            {"subject": "read", "isRead": True, "date": "2026-04-06T10:00:00+08:00"},
        ]
        unread = outlook_client.get_unread_emails()
        assert [e["subject"] for e in unread] == ["newest", "middle", "older"]
    finally:
        outlook_client.get_inbox = original_get_inbox


def test_timezone_default_and_override():
    old_tz = os.environ.get("APP_TIMEZONE")
    try:
        os.environ.pop("APP_TIMEZONE", None)
        assert getattr(get_local_tz(), "key", "") == "Asia/Singapore"
        os.environ["APP_TIMEZONE"] = "UTC"
        assert getattr(get_local_tz(), "key", "") in {"UTC", "Etc/UTC"}
    finally:
        if old_tz is None:
            os.environ.pop("APP_TIMEZONE", None)
        else:
            os.environ["APP_TIMEZONE"] = old_tz


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        test_memory_cleanup_and_dedup(tmpdir)
        test_weekly_filter(tmpdir)
        test_latest_unread_sort()
        test_timezone_default_and_override()

    print("All regression checks passed.")


if __name__ == "__main__":
    main()
