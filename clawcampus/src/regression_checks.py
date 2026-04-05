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
if "openai" not in sys.modules:
    class _DummyOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(
                    create=lambda **kwargs: types.SimpleNamespace(
                        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=""))]
                    )
                )
            )
            self.base_url = kwargs.get("base_url", "")

    sys.modules["openai"] = types.SimpleNamespace(OpenAI=_DummyOpenAI)

import outlook_client
import job_matcher
import canvas_client
import assignment_coach


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
    # Header-style synthetic task should be removed as low-quality noise.
    assert len(tasks) == 0, "Expected malformed header-like task to be filtered out"

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


def test_jobmatch_template_parse_and_fallback():
    payload = """Here is my master resume/profile:
Python, SQL, data projects

Here is the email to analyze:
Data Analyst Intern - Acme
Software Engineer Intern at Rocket Labs

My goals and preferences:
- Preferred roles: Data Analyst Intern, Software Engineer Intern
- Roles I do NOT want: Sales Intern
"""
    parsed = job_matcher.parse_jobmatch_sections(payload)
    assert parsed is not None
    assert "Python" in parsed.get("master_resume", "")
    assert "Acme" in parsed.get("email_text", "")

    result = job_matcher.run_job_matching(
        master_resume=parsed.get("master_resume", ""),
        email_text=parsed.get("email_text", ""),
        goals_preferences=parsed.get("goals_preferences", ""),
        top_k=3,
    )
    assert result.get("roles"), "Expected fallback/model stage to extract at least one role"
    report = job_matcher.format_job_matching_report(result)
    assert "A. Extracted Job Postings" in report
    assert "B. Suitability Ranking" in report


def test_job_email_detection():
    job_email = {
        "subject": "Internship Openings - Apply Now",
        "from": "careers@example.com",
        "date": "2026-04-05T09:00:00+08:00",
        "body": "We are hiring Software Engineer Interns and Data Analyst Interns.",
    }
    non_job_email = {
        "subject": "Your GrabFood receipt",
        "from": "noreply@grab.com",
        "date": "2026-04-05T09:00:00+08:00",
        "body": "Total: $12.29. Order receipt.",
    }
    assert job_matcher.is_job_related_email(job_email) is True
    assert job_matcher.is_job_related_email(non_job_email) is False


def test_assignment_brief_coach():
    brief = canvas_client.get_assignment_brief("Lab 5")
    assert brief is not None, "Expected mock/Canvas brief for Lab 5"
    assert "brief_text" in brief and brief["brief_text"].strip()

    analysis = assignment_coach.analyze_assignment_brief(
        brief["brief_text"],
        assignment_title=brief.get("title", ""),
        course_name=brief.get("course_name", ""),
        due_at=brief.get("due_at"),
    )
    assert analysis.get("recommended_slides"), "Expected slide recommendations"

    report = assignment_coach.format_assignment_study_guide(
        analysis,
        assignment_title=brief.get("title", ""),
        course_name=brief.get("course_name", ""),
        due_at=brief.get("due_at"),
        source_url=brief.get("source_url"),
    )
    assert "Lecture Slides to Read" in report
    assert "Other Relevant Sources" in report


def test_cross_source_duplicate_task_filtered(tmpdir: Path):
    memory_manager.MEMORY_PATH = tmpdir / "MEMORY_dupe.md"
    memory_manager.init_memory()
    memory_manager.add_tasks([
        {
            "title": "Lab 5: Graphs & BFS",
            "course": "CS2040S",
            "due_date": "2026-04-10T15:59:00Z",
            "urgency": "soon",
            "source": "canvas",
        },
        {
            "title": "Submit CS2040S Lab 5",
            "course": "CS2040S",
            "due_date": "2026-04-10T15:59:00Z",
            "urgency": "soon",
            "source": "email",
        },
    ])
    tasks = memory_manager.get_all_tasks()
    assert len(tasks) == 1, "Expected near-duplicate cross-source task to be deduplicated"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        test_memory_cleanup_and_dedup(tmpdir)
        test_weekly_filter(tmpdir)
        test_latest_unread_sort()
        test_timezone_default_and_override()
        test_jobmatch_template_parse_and_fallback()
        test_job_email_detection()
        test_assignment_brief_coach()
        test_cross_source_duplicate_task_filtered(tmpdir)

    print("All regression checks passed.")


if __name__ == "__main__":
    main()
