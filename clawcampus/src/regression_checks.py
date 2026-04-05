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
import io
import zipfile
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


def test_live_mode_disables_mock_fallback():
    original_canvas_use_mock = canvas_client.USE_MOCK
    original_canvas_api_get = canvas_client._api_get
    original_canvas_load_mock = canvas_client._load_mock

    original_outlook_use_mock = outlook_client.USE_MOCK
    original_outlook_api_get = outlook_client._api_get
    original_outlook_load_mock = outlook_client._load_mock_emails

    try:
        canvas_client.USE_MOCK = False
        canvas_client._api_get = lambda endpoint: None
        canvas_client._load_mock = lambda filename: (_ for _ in ()).throw(
            AssertionError("Canvas mock loader should not be used in live mode")
        )
        assert canvas_client.get_todo_items() == []
        assert canvas_client.get_upcoming_events() == []
        assert canvas_client.get_courses() == []

        outlook_client.USE_MOCK = False
        outlook_client._api_get = lambda endpoint: None
        outlook_client._load_mock_emails = lambda: (_ for _ in ()).throw(
            AssertionError("Outlook mock loader should not be used in live mode")
        )
        assert outlook_client.get_inbox() == []
    finally:
        canvas_client.USE_MOCK = original_canvas_use_mock
        canvas_client._api_get = original_canvas_api_get
        canvas_client._load_mock = original_canvas_load_mock

        outlook_client.USE_MOCK = original_outlook_use_mock
        outlook_client._api_get = original_outlook_api_get
        outlook_client._load_mock_emails = original_outlook_load_mock


def test_assignment_brief_uses_attachment_text():
    original_use_mock = canvas_client.USE_MOCK
    original_find_assignment_todo = canvas_client.find_assignment_todo
    original_api_get_json = canvas_client._api_get_json
    original_download_attachments = canvas_client._download_assignment_attachments

    try:
        canvas_client.USE_MOCK = False
        canvas_client.find_assignment_todo = lambda query: {
            "context_name": "CS2040S",
            "assignment": {
                "id": 204001,
                "course_id": 2040,
                "name": "Lab 5: Graphs & BFS",
                "due_at": "2026-04-10T15:59:00Z",
                "html_url": "https://canvas.nus.edu.sg/courses/2040/assignments/204001",
            },
        }
        canvas_client._api_get_json = lambda endpoint: {
            "id": 204001,
            "course_id": 2040,
            "name": "Lab 5: Graphs & BFS",
            "due_at": "2026-04-10T15:59:00Z",
            "html_url": "https://canvas.nus.edu.sg/courses/2040/assignments/204001",
            "description": "<p>Implement BFS and analyze O(V+E).</p>",
            "attachments": [{"filename": "brief.txt", "url": "https://canvas.nus.edu.sg/files/1/download"}],
        }
        canvas_client._download_assignment_attachments = lambda **kwargs: [
            {
                "url": "https://canvas.nus.edu.sg/files/1/download",
                "filename": "brief.txt",
                "saved_path": "/tmp/brief.txt",
                "text_excerpt": "Attachment says include complexity proof.",
                "status": "downloaded",
            }
        ]

        brief = canvas_client.get_assignment_brief("lab 5")
        assert brief is not None
        assert "Assignment description:" in brief.get("brief_text", "")
        assert "Attachment (brief.txt) extracted text" in brief.get("brief_text", "")
        assert len(brief.get("attachments", [])) == 1
    finally:
        canvas_client.USE_MOCK = original_use_mock
        canvas_client.find_assignment_todo = original_find_assignment_todo
        canvas_client._api_get_json = original_api_get_json
        canvas_client._download_assignment_attachments = original_download_attachments


def test_replace_synced_tasks_replaces_non_manual(tmpdir: Path):
    memory_manager.MEMORY_PATH = tmpdir / "MEMORY_replace.md"
    memory_manager.init_memory()
    memory_manager.add_tasks([
        {
            "title": "Old Canvas Task",
            "course": "CS0001",
            "due_date": "2026-04-01T10:00:00Z",
            "urgency": "later",
            "source": "canvas",
        },
        {
            "title": "Keep Manual Task",
            "course": None,
            "due_date": None,
            "urgency": "info",
            "source": "manual",
        },
    ])

    memory_manager.replace_synced_tasks([
        {
            "title": "New Canvas Task",
            "course": "CS2040S",
            "due_date": "2026-04-10T15:59:00Z",
            "urgency": "soon",
            "source": "canvas",
        }
    ])

    titles = {t.get("title") for t in memory_manager.get_all_tasks()}
    assert "Keep Manual Task" in titles
    assert "New Canvas Task" in titles
    assert "Old Canvas Task" not in titles


def test_zip_attachment_text_extraction():
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("brief/requirements.txt", "Need BFS, DFS and complexity analysis.")
        zf.writestr("brief/notes.md", "Remember to include test cases.")
        zf.writestr("brief/image.png", b"\x89PNG\r\n\x1a\n")

    zip_bytes = memory.getvalue()
    extracted = canvas_client._extract_text_from_attachment(
        zip_bytes,
        filename="assignment_materials.zip",
        content_type="application/zip",
    )
    assert "[ZIP:brief/requirements.txt]" in extracted
    assert "Need BFS, DFS and complexity analysis." in extracted
    assert "Remember to include test cases." in extracted


def test_find_assignment_todo_course_aware_fuzzy():
    original_get_todo_items = canvas_client.get_todo_items
    try:
        canvas_client.get_todo_items = lambda: [
            {
                "context_name": "CS4243 Computer Vision and Pattern Recognition",
                "assignment": {
                    "id": 1001,
                    "course_id": 4243,
                    "name": "Tutorial 9: Object Detection",
                    "due_at": "2026-04-20T10:00:00Z",
                },
            },
            {
                "context_name": "CS4243 Computer Vision and Pattern Recognition",
                "assignment": {
                    "id": 1002,
                    "course_id": 4243,
                    "name": "Tutorial 10 - Image Segmentation",
                    "due_at": "2026-04-25T10:00:00Z",
                },
            },
            {
                "context_name": "CS2105 Introduction to Computer Networks",
                "assignment": {
                    "id": 2001,
                    "course_id": 2105,
                    "name": "Tutorial 10 - Routing",
                    "due_at": "2026-04-21T10:00:00Z",
                },
            },
        ]
        item = canvas_client.find_assignment_todo("CS4243 tutorial 10")
        assert item is not None
        assert item.get("assignment", {}).get("id") == 1002
    finally:
        canvas_client.get_todo_items = original_get_todo_items


def test_collect_attachment_candidates_includes_course_file_search():
    original_search = canvas_client._search_course_files
    try:
        canvas_client._search_course_files = lambda course_id, query_text, limit=4: [
            {
                "url": "https://canvas.nus.edu.sg/files/987/download",
                "filename": "CS4243_Tutorial10_Brief.zip",
                "source": "course_file_search",
            }
        ]
        candidates = canvas_client._collect_attachment_candidates(
            details={"attachments": []},
            description_html="",
            course_id=4243,
            query_text="tutorial 10",
            assignment_title="Tutorial 10",
        )
        assert candidates, "Expected at least one candidate from course file search"
        assert candidates[0].get("source") == "course_file_search"
        assert "Tutorial10" in candidates[0].get("filename", "")
    finally:
        canvas_client._search_course_files = original_search


def test_missing_brief_analysis_is_conservative():
    placeholder = (
        "Assignment: Tutorial 10 Submission\n"
        "Course: CS3264 Foundations of Machine Learning\n"
        "Due: 2026-04-06T08:00:00Z\n"
        "No full brief text was retrieved. Use the Canvas URL for full instructions."
    )
    result = assignment_coach.analyze_assignment_brief(
        placeholder,
        assignment_title="Tutorial 10 Submission",
        course_name="CS3264 Foundations of Machine Learning",
        due_at="2026-04-06T08:00:00Z",
    )
    assert result.get("recommended_slides") == []
    assert result.get("recommended_sources") == []
    gaps = " ".join(result.get("gaps_or_unknowns", []))
    assert "missing" in gaps.lower() or "unable" in gaps.lower()


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
        test_live_mode_disables_mock_fallback()
        test_assignment_brief_uses_attachment_text()
        test_replace_synced_tasks_replaces_non_manual(tmpdir)
        test_zip_attachment_text_extraction()
        test_find_assignment_todo_course_aware_fuzzy()
        test_collect_attachment_candidates_includes_course_file_search()
        test_missing_brief_analysis_is_conservative()

    print("All regression checks passed.")


if __name__ == "__main__":
    main()
