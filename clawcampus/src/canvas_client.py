"""
Canvas LMS REST client with seamless mock fallback.
If USE_MOCK=true or API call fails, returns data from mock_data/.
"""
from __future__ import annotations

import os
import json
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


def _api_get(endpoint: str) -> list[dict] | None:
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
