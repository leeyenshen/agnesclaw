"""
Task/Deadline extraction pipeline.
Uses Agnes-1.5-Pro to extract structured tasks from emails, Canvas data, and raw text.
Falls back to rule-based extraction if Agnes API is unavailable.
"""
from __future__ import annotations

import json

from agnes_client import call_agnes_pro, extract_json
from canvas_client import get_todo_items, get_upcoming_events
from outlook_client import get_unread_emails
from time_utils import now_local, parse_iso_datetime

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
    text = f"Subject: {email.get('subject', '')}\nFrom: {email.get('from', '')}\nDate: {email.get('date', '')}\n\n{email.get('body', '')}"
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
    for email in get_unread_emails():
        tasks.extend(extract_from_email(email))

    # Deduplicate by title (simple approach)
    seen_titles = set()
    unique_tasks = []
    for task in tasks:
        title_key = task["title"].lower().strip()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_tasks.append(task)

    # Sort: urgent first, then soon, then later, then info
    urgency_order = {"urgent": 0, "soon": 1, "later": 2, "info": 3}
    unique_tasks.sort(key=lambda t: urgency_order.get(t.get("urgency", "info"), 4))

    return unique_tasks


if __name__ == "__main__":
    print("=== Task Extractor Test (Canvas + mock data) ===\n")

    # Test Canvas extraction (no Agnes needed)
    todos = get_todo_items()
    print(f"Canvas todos → {len(todos)} items:")
    for item in todos:
        task = extract_from_canvas_todo(item)
        print(f"  [{task['urgency'].upper():6s}] {task['title']} — due {task['due_date']}")

    events = get_upcoming_events()
    print(f"\nCanvas events → {len(events)} items:")
    for ev in events:
        task = extract_from_canvas_event(ev)
        print(f"  [{task['urgency'].upper():6s}] {task['title']} @ {task.get('location', 'TBA')}")

    # Test email extraction (needs Agnes or falls back)
    print("\nEmail extraction (may use Agnes or fallback):")
    emails = get_unread_emails()
    for email in emails:
        print(f"\n  Processing: {email['subject']}")
        tasks = extract_from_email(email)
        for t in tasks:
            print(f"    [{t['urgency'].upper():6s}] {t['title']}")
