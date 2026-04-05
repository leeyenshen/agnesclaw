"""
Canvas LMS REST client with seamless mock fallback.
If USE_MOCK=true or API call fails, returns data from mock_data/.
"""
from __future__ import annotations

import os
import json
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CANVAS_URL = os.environ.get("CANVAS_URL", "https://canvas.nus.edu.sg")
CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "")
USE_MOCK = os.environ.get("USE_MOCK", "true").lower() == "true"

MOCK_DIR = Path(__file__).parent.parent / "mock_data"

HEADERS = {"Authorization": f"Bearer {CANVAS_TOKEN}"} if CANVAS_TOKEN else {}


def _load_mock(filename: str) -> list[dict]:
    path = MOCK_DIR / filename
    with open(path) as f:
        return json.load(f)


def _api_get_json(endpoint: str) -> list[dict] | dict | None:
    """Try a real Canvas API call. Returns None on failure."""
    if USE_MOCK or not CANVAS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{CANVAS_URL}{endpoint}",
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _api_get(endpoint: str) -> list[dict] | None:
    """Compatibility wrapper for list endpoints."""
    data = _api_get_json(endpoint)
    return data if isinstance(data, list) else None


def get_todo_items() -> list[dict]:
    """Fetch upcoming assignments from Canvas or mock data."""
    result = _api_get("/api/v1/users/self/todo")
    if result is not None:
        return result
    return _load_mock("canvas_todo.json")


def get_upcoming_events() -> list[dict]:
    """Fetch upcoming calendar events from Canvas or mock data."""
    result = _api_get("/api/v1/users/self/upcoming_events")
    if result is not None:
        return result
    return _load_mock("canvas_events.json")


def get_courses() -> list[dict]:
    """Fetch enrolled courses. Mock returns extracted course names from todo data."""
    result = _api_get("/api/v1/courses")
    if result is not None:
        return result
    # Derive courses from mock todo data
    todos = _load_mock("canvas_todo.json")
    seen = set()
    courses = []
    for item in todos:
        name = item.get("context_name", "")
        if name and name not in seen:
            seen.add(name)
            courses.append({
                "id": item["assignment"]["course_id"],
                "name": name,
            })
    return courses


def list_assignment_titles(limit: int = 10) -> list[str]:
    """Return assignment names from current todo list."""
    titles = []
    for item in get_todo_items()[: max(1, limit)]:
        assignment = item.get("assignment", {})
        title = assignment.get("name")
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return titles


def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(no_tags.split())


def _load_mock_briefs() -> list[dict]:
    path = MOCK_DIR / "canvas_assignment_briefs.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def find_assignment_todo(query: str) -> dict | None:
    """
    Find a Canvas todo assignment by id or fuzzy title match.
    Returns the todo item.
    """
    query_norm = str(query or "").strip().lower()
    if not query_norm:
        return None

    todos = get_todo_items()
    for item in todos:
        assignment = item.get("assignment", {})
        assignment_id = str(assignment.get("id", "")).strip().lower()
        if assignment_id and query_norm == assignment_id:
            return item

    # Fuzzy match on assignment name
    for item in todos:
        assignment = item.get("assignment", {})
        title = str(assignment.get("name", "")).strip().lower()
        if query_norm and query_norm in title:
            return item

    return None


def get_assignment_brief(assignment_query: str) -> dict | None:
    """
    Download/resolve an assignment brief by id or title.

    Returns:
    {
      assignment_id, course_id, title, course_name, due_at, source_url,
      brief_text, confidence
    }
    """
    query_norm = str(assignment_query or "").strip()
    if not query_norm:
        return None

    todo_item = find_assignment_todo(query_norm)
    assignment = todo_item.get("assignment", {}) if todo_item else {}
    assignment_id = assignment.get("id")
    course_id = assignment.get("course_id")
    title = assignment.get("name")
    course_name = todo_item.get("context_name") if todo_item else None
    due_at = assignment.get("due_at")
    source_url = assignment.get("html_url")

    if assignment_id and course_id:
        # Real Canvas assignment endpoint often includes HTML description.
        details = _api_get_json(f"/api/v1/courses/{course_id}/assignments/{assignment_id}")
        if isinstance(details, dict):
            description = _strip_html(str(details.get("description", "")))
            if description:
                return {
                    "assignment_id": details.get("id", assignment_id),
                    "course_id": details.get("course_id", course_id),
                    "title": details.get("name") or title,
                    "course_name": course_name,
                    "due_at": details.get("due_at") or due_at,
                    "source_url": details.get("html_url") or source_url,
                    "brief_text": description,
                    "confidence": "high",
                }

    # Mock brief lookup by assignment id or title.
    for brief in _load_mock_briefs():
        bid = str(brief.get("assignment_id", "")).strip().lower()
        btitle = str(brief.get("title", "")).strip().lower()
        if (assignment_id and str(assignment_id).lower() == bid) or (
            query_norm.lower() and query_norm.lower() in btitle
        ):
            return {
                "assignment_id": brief.get("assignment_id", assignment_id),
                "course_id": brief.get("course_id", course_id),
                "title": brief.get("title") or title,
                "course_name": brief.get("course_name") or course_name,
                "due_at": brief.get("due_at") or due_at,
                "source_url": brief.get("source_url") or source_url,
                "brief_text": brief.get("brief_text", ""),
                "confidence": "medium",
            }

    # Final fallback: synthesize minimal brief from todo metadata.
    if todo_item and title:
        synthesized = (
            f"Assignment: {title}\n"
            f"Course: {course_name or 'Unknown'}\n"
            f"Due: {due_at or 'Not provided'}\n"
            "No full brief text was retrieved. Use the Canvas URL for full instructions."
        )
        return {
            "assignment_id": assignment_id,
            "course_id": course_id,
            "title": title,
            "course_name": course_name,
            "due_at": due_at,
            "source_url": source_url,
            "brief_text": synthesized,
            "confidence": "low",
        }

    return None


if __name__ == "__main__":
    print("=== Canvas Client Test ===")
    print(f"Mock mode: {USE_MOCK}")
    print(f"\nTodo items ({len(get_todo_items())}):")
    for item in get_todo_items():
        a = item["assignment"]
        print(f"  - {a['name']} (due: {a['due_at']})")
    print(f"\nUpcoming events ({len(get_upcoming_events())}):")
    for ev in get_upcoming_events():
        print(f"  - {ev['title']} @ {ev.get('location_name', 'TBA')}")
    print(f"\nCourses ({len(get_courses())}):")
    for c in get_courses():
        print(f"  - {c['name']}")

    print("\nBrief test:")
    sample = get_assignment_brief("lab 5")
    if sample:
        print(f"  - {sample.get('title')} ({sample.get('confidence')})")
