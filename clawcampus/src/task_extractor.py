"""
Task/Deadline extraction pipeline.
Uses Agnes-1.5-Pro to extract structured tasks from emails, Canvas data, and raw text.
Falls back to rule-based extraction if Agnes API is unavailable.
"""
from __future__ import annotations

import json

import re

from agnes_client import call_agnes_pro, extract_json
from canvas_client import get_todo_items, get_upcoming_events

from time_utils import now_local, parse_iso_datetime

import os
from datetime import datetime, timezone

from agnes_client import call_agnes_pro, extract_json
from canvas_client import get_todo_items, get_upcoming_events
from gmail_client import get_service, fetch_recent_emails, fetch_unread_emails


EXTRACTION_PROMPT = """You are a student task extraction agent. Given the following text from a student's email or assignment page, extract ALL actionable items.

For each item, output JSON with:
- "title": concise task name
- "course": course code if applicable, else null
- "due_date": ISO 8601 date/time if found, else null
- "type": one of ["assignment", "event", "admin", "social", "financial"]
- "urgency": one of ["urgent", "soon", "later", "info"]
- "source": "email" | "canvas" | "manual"
- "raw_snippet": the exact text fragment this was extracted from (max 100 chars)

Classify urgency as:
- "urgent": due within 48 hours or marked important
- "soon": due within 1 week
- "later": due beyond 1 week
- "info": no deadline, informational only

Today's date is {today}.

Respond ONLY with a JSON array. No markdown, no explanation."""


_TITLE_STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "on",
    "at",
    "of",
    "and",
    "by",
    "with",
    "submit",
    "attend",
    "take",
    "complete",
    "rsvp",
    "reply",
}


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w and w not in _TITLE_STOPWORDS}


def _course_code(value: str | None) -> str:
    text = str(value or "")
    match = re.search(r"\b([A-Za-z]{2,4}\d{4}[A-Za-z]?)\b", text)
    return match.group(1).upper() if match else ""


def _course_compatible(first: str | None, second: str | None) -> bool:
    a = str(first or "").strip().lower()
    b = str(second or "").strip().lower()
    if not a or not b:
        return True
    if a == b or a in b or b in a:
        return True
    code_a = _course_code(a)
    code_b = _course_code(b)
    return bool(code_a and code_b and code_a == code_b)


def _is_low_quality_email_title(title: str) -> bool:
    normalized = " ".join(str(title or "").lower().split())
    if not normalized:
        return True
    if normalized.startswith("subject:") and (" from:" in normalized or " date" in normalized):
        return True
    if "subject:" in normalized and "from:" in normalized and "date" in normalized:
        return True
    return False


def _is_duplicate_task(candidate: dict, existing: dict) -> bool:
    candidate_title = str(candidate.get("title", "")).strip().lower()
    existing_title = str(existing.get("title", "")).strip().lower()
    if candidate_title == existing_title and candidate_title:
        return True

    cand_course = str(candidate.get("course", "")).strip().lower()
    exist_course = str(existing.get("course", "")).strip().lower()
    if not _course_compatible(cand_course, exist_course):
        return False

    due_a = parse_iso_datetime(candidate.get("due_date"))
    due_b = parse_iso_datetime(existing.get("due_date"))
    if not due_a or not due_b:
        return False
    delta_hours = abs((due_a - due_b).total_seconds()) / 3600
    if delta_hours > 3:
        return False

    tokens_a = _title_tokens(candidate_title)
    tokens_b = _title_tokens(existing_title)
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b)
    return overlap / min(len(tokens_a), len(tokens_b)) >= 0.6


def _deduplicate_tasks(tasks: list[dict]) -> list[dict]:
    # Keep Canvas-first ordering so canonical assignment/event names survive.
    source_rank = {"canvas": 0, "email": 1, "manual": 2}
    ordered = sorted(tasks, key=lambda t: source_rank.get(str(t.get("source", "")).lower(), 3))

    unique: list[dict] = []
    for task in ordered:
        title = str(task.get("title", "")).strip()
        if not title:
            continue
        if str(task.get("source", "")).lower() == "email" and _is_low_quality_email_title(title):
            continue
        if any(_is_duplicate_task(task, existing) for existing in unique):
            continue
        unique.append(task)

    # Preserve urgency ordering for user-facing task list.
    urgency_order = {"urgent": 0, "soon": 1, "later": 2, "info": 3}
    unique.sort(key=lambda t: urgency_order.get(t.get("urgency", "info"), 4))
    return unique


def extract_from_text(text: str, source: str = "manual") -> list[dict]:
    """Extract tasks from arbitrary text using Agnes-1.5-Pro."""
    today = now_local().strftime("%Y-%m-%d")
    prompt = EXTRACTION_PROMPT.format(today=today)

    try:
        response = call_agnes_pro([
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ])
        tasks = extract_json(response)
        if isinstance(tasks, list):
            # Ensure source field is set
            for task in tasks:
                task.setdefault("source", source)
                task["extracted_at"] = now_local().isoformat()
            return tasks
    except Exception as e:
        print(f"[task_extractor] Agnes call failed: {e}")

    if source == "email":
        # Avoid persisting noisy synthetic placeholders like:
        # "Subject: ... From: ... Date ..."
        return []

    # Fallback: return a single generic task
    return [{
        "title": text[:80].strip(),
        "course": None,
        "due_date": None,
        "type": "admin",
        "urgency": "info",
        "source": source,
        "raw_snippet": text[:100],
        "extracted_at": now_local().isoformat(),
    }]


def extract_from_email(email: dict) -> list[dict]:
    """Extract tasks from a single email dict."""
    text = (
        f"Subject: {email.get('subject', '')}\n"
        f"From: {email.get('sender', '')}\n"
        f"{email.get('body', '')}"
    )
    return extract_from_text(text, source="email")


def extract_from_canvas_todo(item: dict) -> dict:
    """Convert a Canvas todo item into our standard task format."""
    assignment = item.get("assignment", {})
    due = assignment.get("due_at")
    urgency = _classify_urgency(due)

    return {
        "title": assignment.get("name", "Untitled Assignment"),
        "course": item.get("context_name"),
        "due_date": due,
        "type": "assignment",
        "urgency": urgency,
        "source": "canvas",
        "raw_snippet": f"{assignment.get('name', '')} — {item.get('context_name', '')}",
        "extracted_at": now_local().isoformat(),
        "canvas_url": assignment.get("html_url"),
    }


def extract_from_canvas_event(event: dict) -> dict:
    """Convert a Canvas event into our standard task format."""
    start = event.get("start_at")
    urgency = _classify_urgency(start)

    return {
        "title": event.get("title", "Untitled Event"),
        "course": event.get("context_name"),
        "due_date": start,
        "type": "event",
        "urgency": urgency,
        "source": "canvas",
        "raw_snippet": f"{event.get('title', '')} @ {event.get('location_name', 'TBA')}",
        "extracted_at": now_local().isoformat(),
        "location": event.get("location_name"),
    }


def _classify_urgency(date_str: str | None) -> str:
    """Classify urgency based on how far away a date is."""
    if not date_str:
        return "info"
    due = parse_iso_datetime(date_str)
    if not due:
        return "info"
    now = now_local()
    delta = (due.astimezone(now.tzinfo) - now).total_seconds() / 3600  # hours
    if delta < 0:
        return "urgent"  # overdue
    if delta < 48:
        return "urgent"
    if delta < 168:  # 7 days
        return "soon"
    return "later"


def extract_all_sources() -> list[dict]:
    """
    Run full extraction pipeline:
    1. Canvas todos → direct conversion
    2. Canvas events → direct conversion
    3. Unread emails → Agnes extraction
    Returns deduplicated task list.
    """
    tasks = []

    # Canvas assignments
    for item in get_todo_items():
        tasks.append(extract_from_canvas_todo(item))

    # Canvas events
    for event in get_upcoming_events():
        tasks.append(extract_from_canvas_event(event))

    # Unread emails
    service = get_service()
    emails = fetch_unread_emails(service, max_results=10)
    for email in emails:
        tasks.extend(extract_from_email(email))

    return _deduplicate_tasks(tasks)


if __name__ == "__main__":
    os.environ["USE_MOCK"] = "false"

    service = get_service()
    emails = fetch_recent_emails(service, max_results=5)
    for email in emails:
        print("--- EMAIL ---")
        print(f"From: {email.get('sender', '')}")
        print(f"Subject: {email.get('subject', '')}")
        print()
        print("--- EXTRACTED TASKS ---")
        tasks = extract_from_email(email)
        if tasks:
            print(json.dumps(tasks, indent=2))
        else:
            print("No tasks extracted")
        print()
