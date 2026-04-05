"""
MEMORY.md manager — persistent storage for tasks, preferences, and user data.
Uses structured markdown sections for OpenClaw compatibility.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

MEMORY_PATH = Path(__file__).parent.parent / "MEMORY.md"

# Section headers used in MEMORY.md
SECTION_TASKS = "## Tasks"
SECTION_COURSES = "## Courses"
SECTION_PREFERENCES = "## Preferences"
SECTION_TRANSACTIONS = "## Transactions"
SECTION_FOOD_DEALS = "## Food Deals"


def _read_memory() -> str:
    """Read the full MEMORY.md content."""
    if not MEMORY_PATH.exists():
        return ""
    return MEMORY_PATH.read_text(encoding="utf-8")


def _write_memory(content: str):
    """Write full content to MEMORY.md."""
    MEMORY_PATH.write_text(content, encoding="utf-8")


def _ensure_section(content: str, section: str) -> str:
    """Ensure a section header exists in the content."""
    if section not in content:
        content = content.rstrip() + f"\n\n{section}\n"
    return content


def _get_section_content(content: str, section: str) -> str:
    """Extract content under a specific section header."""
    pattern = re.escape(section) + r"\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


def _replace_section_content(content: str, section: str, new_content: str) -> str:
    """Replace the content under a specific section header."""
    content = _ensure_section(content, section)
    pattern = re.escape(section) + r"\n(.*?)(?=\n## |\Z)"
    replacement = f"{section}\n{new_content}\n"
    result = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return result


def init_memory():
    """Initialize MEMORY.md with empty sections if it doesn't exist."""
    if MEMORY_PATH.exists():
        return
    content = """# ClawCampus Memory

Last updated: {now}

## Tasks

## Courses

## Preferences

## Transactions

## Food Deals
""".format(now=datetime.now(timezone.utc).isoformat())
    _write_memory(content)


def add_tasks(tasks: list[dict]):
    """Append tasks to the Tasks section as JSON-encoded bullet points."""
    if not tasks:
        return
    content = _read_memory()
    if not content:
        init_memory()
        content = _read_memory()

    existing = _get_section_content(content, SECTION_TASKS)
    lines = existing.split("\n") if existing else []

    # Load existing task titles for dedup
    existing_titles = set()
    for line in lines:
        if line.startswith("- "):
            try:
                task_data = json.loads(line[2:])
                existing_titles.add(task_data.get("title", "").lower().strip())
            except json.JSONDecodeError:
                pass

    # Add new tasks
    for task in tasks:
        title_key = task.get("title", "").lower().strip()
        if title_key and title_key not in existing_titles:
            lines.append(f"- {json.dumps(task, ensure_ascii=False)}")
            existing_titles.add(title_key)

    new_section = "\n".join(lines)
    content = _replace_section_content(content, SECTION_TASKS, new_section)

    # Update timestamp
    content = re.sub(
        r"Last updated: .*",
        f"Last updated: {datetime.now(timezone.utc).isoformat()}",
        content,
    )
    _write_memory(content)


def get_all_tasks() -> list[dict]:
    """Read all tasks from MEMORY.md."""
    content = _read_memory()
    if not content:
        return []
    section = _get_section_content(content, SECTION_TASKS)
    tasks = []
    for line in section.split("\n"):
        if line.startswith("- "):
            try:
                tasks.append(json.loads(line[2:]))
            except json.JSONDecodeError:
                pass
    return tasks


def get_tasks_by_urgency(urgency: str) -> list[dict]:
    """Filter tasks by urgency level."""
    return [t for t in get_all_tasks() if t.get("urgency") == urgency]


def get_pending_tasks() -> list[dict]:
    """Get tasks that aren't marked as done."""
    return [t for t in get_all_tasks() if not t.get("done")]


def mark_task_done(title: str) -> bool:
    """Mark a task as done by title (case-insensitive partial match)."""
    content = _read_memory()
    if not content:
        return False
    section = _get_section_content(content, SECTION_TASKS)
    lines = section.split("\n")
    updated = False

    for i, line in enumerate(lines):
        if line.startswith("- "):
            try:
                task = json.loads(line[2:])
                if title.lower() in task.get("title", "").lower():
                    task["done"] = True
                    task["done_at"] = datetime.now(timezone.utc).isoformat()
                    lines[i] = f"- {json.dumps(task, ensure_ascii=False)}"
                    updated = True
            except json.JSONDecodeError:
                pass

    if updated:
        new_section = "\n".join(lines)
        content = _replace_section_content(content, SECTION_TASKS, new_section)
        _write_memory(content)
    return updated


def set_courses(courses: list[dict]):
    """Set the courses list in memory."""
    content = _read_memory()
    if not content:
        init_memory()
        content = _read_memory()
    lines = []
    for course in courses:
        lines.append(f"- {course.get('name', 'Unknown')} (ID: {course.get('id', '?')})")
    new_section = "\n".join(lines)
    content = _replace_section_content(content, SECTION_COURSES, new_section)
    _write_memory(content)


def set_preferences(prefs: dict):
    """Save user preferences."""
    content = _read_memory()
    if not content:
        init_memory()
        content = _read_memory()
    lines = [f"- **{k}**: {v}" for k, v in prefs.items()]
    new_section = "\n".join(lines)
    content = _replace_section_content(content, SECTION_PREFERENCES, new_section)
    _write_memory(content)


def add_transaction(transaction: dict):
    """Append a financial transaction."""
    content = _read_memory()
    if not content:
        init_memory()
        content = _read_memory()
    existing = _get_section_content(content, SECTION_TRANSACTIONS)
    lines = existing.split("\n") if existing else []
    lines.append(f"- {json.dumps(transaction, ensure_ascii=False)}")
    new_section = "\n".join(lines)
    content = _replace_section_content(content, SECTION_TRANSACTIONS, new_section)
    _write_memory(content)


def get_transactions() -> list[dict]:
    """Read all transactions from memory."""
    content = _read_memory()
    if not content:
        return []
    section = _get_section_content(content, SECTION_TRANSACTIONS)
    transactions = []
    for line in section.split("\n"):
        if line.startswith("- "):
            try:
                transactions.append(json.loads(line[2:]))
            except json.JSONDecodeError:
                pass
    return transactions


def add_food_deals(deals: list[dict]):
    """Save food deals to memory."""
    content = _read_memory()
    if not content:
        init_memory()
        content = _read_memory()
    lines = []
    for deal in deals:
        lines.append(f"- {json.dumps(deal, ensure_ascii=False)}")
    new_section = "\n".join(lines)
    content = _replace_section_content(content, SECTION_FOOD_DEALS, new_section)
    _write_memory(content)


def get_food_deals() -> list[dict]:
    """Read food deals from memory."""
    content = _read_memory()
    if not content:
        return []
    section = _get_section_content(content, SECTION_FOOD_DEALS)
    deals = []
    for line in section.split("\n"):
        if line.startswith("- "):
            try:
                deals.append(json.loads(line[2:]))
            except json.JSONDecodeError:
                pass
    return deals


if __name__ == "__main__":
    print("=== Memory Manager Test ===\n")
    init_memory()

    # Test adding tasks
    sample_tasks = [
        {"title": "CS2040S Lab 5", "course": "CS2040S", "due_date": "2026-04-10T15:59:00Z", "urgency": "soon", "source": "canvas"},
        {"title": "MA2001 Group Project", "course": "MA2001", "due_date": "2026-04-11T09:00:00Z", "urgency": "soon", "source": "canvas"},
    ]
    add_tasks(sample_tasks)
    print(f"Added {len(sample_tasks)} tasks.")

    # Test reading tasks
    all_tasks = get_all_tasks()
    print(f"Total tasks in memory: {len(all_tasks)}")
    for t in all_tasks:
        print(f"  [{t.get('urgency', '?').upper():6s}] {t['title']}")

    # Test courses
    set_courses([{"id": 2040, "name": "CS2040S Data Structures"}, {"id": 2001, "name": "MA2001 Linear Algebra"}])
    print("\nCourses saved.")

    # Test preferences
    set_preferences({"study_time": "after 7pm", "notification": "morning digest + urgent alerts"})
    print("Preferences saved.")

    print(f"\nMemory file: {MEMORY_PATH}")
    print("Contents:")
    print(_read_memory())
