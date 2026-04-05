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


def _update_timestamp(content: str) -> str:
    return re.sub(
        r"Last updated: .*",
        f"Last updated: {datetime.now(timezone.utc).isoformat()}",
        content,
    )


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


_TASK_TITLE_STOPWORDS = {
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


def _normalize_task(task: dict) -> dict:
    normalized = dict(task)
    for key in ("title", "course", "raw_snippet"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = _normalize_whitespace(value)
    return normalized


def _normalize_transaction(transaction: dict) -> dict:
    normalized = dict(transaction)
    if isinstance(normalized.get("merchant"), str):
        normalized["merchant"] = _normalize_whitespace(normalized["merchant"])
    if isinstance(normalized.get("date"), str):
        normalized["date"] = _normalize_whitespace(normalized["date"])
    return normalized


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w and w not in _TASK_TITLE_STOPWORDS}


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


def _parse_due(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        due = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due


def _due_close_hours(first: str | None, second: str | None, *, max_hours: float = 3.0) -> bool:
    due_a = _parse_due(first)
    due_b = _parse_due(second)
    if not due_a or not due_b:
        return False
    delta = abs((due_a - due_b).total_seconds()) / 3600
    return delta <= max_hours


def _is_low_quality_task(task: dict) -> bool:
    title = str(task.get("title", "")).strip().lower()
    if not title:
        return True
    if title.startswith("subject:") and (" from:" in title or " date" in title):
        return True
    if "subject:" in title and "from:" in title and "date" in title:
        return True
    if len(title) > 140 and ("from:" in title or "subject:" in title):
        return True
    return False


def _is_similar_task(candidate: dict, existing: dict) -> bool:
    # Exact semantic key match.
    if _task_key(candidate) == _task_key(existing):
        return True

    cand_course = str(candidate.get("course", "")).strip().lower()
    exist_course = str(existing.get("course", "")).strip().lower()
    if not _course_compatible(cand_course, exist_course):
        return False

    tokens_a = _title_tokens(str(candidate.get("title", "")))
    tokens_b = _title_tokens(str(existing.get("title", "")))
    if not tokens_a or not tokens_b:
        return False

    overlap = len(tokens_a & tokens_b)
    min_size = min(len(tokens_a), len(tokens_b))
    if min_size == 0:
        return False

    title_similar = overlap / min_size >= 0.6
    if not title_similar:
        return False

    # Prefer dedup only when due timestamps are very close to avoid
    # merging distinct class events with similarly named assignments.
    return _due_close_hours(candidate.get("due_date"), existing.get("due_date"))


def _task_key(task: dict) -> tuple[str, str, str]:
    title = str(task.get("title", "")).strip().lower()
    title = re.sub(r"^(submit|attend|take|complete|rsvp|reply)\s+", "", title)
    course = str(task.get("course", "")).strip().lower()
    course_code = _course_code(course)
    return (
        title,
        str(task.get("due_date", "")).strip().lower(),
        course_code or course,
    )


def _transaction_key(transaction: dict) -> tuple[str, str, str]:
    merchant = str(transaction.get("merchant", "")).strip().lower()
    date = str(transaction.get("date", "")).strip().lower()
    try:
        amount = f"{float(transaction.get('amount', 0)):0.2f}"
    except (TypeError, ValueError):
        amount = "0.00"
    return (merchant, amount, date)


def _iter_json_bullet_payloads(section_content: str) -> list[str]:
    """
    Return bullet payloads while supporting malformed multi-line entries.
    A new payload starts at lines prefixed with '- '.
    """
    payloads = []
    current: list[str] = []

    for line in section_content.splitlines():
        if line.startswith("- "):
            if current:
                payloads.append("\n".join(current).strip())
            current = [line[2:]]
            continue
        if current:
            current.append(line)

    if current:
        payloads.append("\n".join(current).strip())
    return [p for p in payloads if p]


def _decode_json_payload(payload: str) -> dict | None:
    # First attempt strict parse. If the payload was accidentally broken
    # across physical lines, escape those line breaks and retry.
    candidates = [payload, payload.replace("\n", "\\n")]
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def _parse_json_section(section_content: str, *, kind: str = "generic") -> tuple[list[dict], bool]:
    """
    Parse JSON bullet entries from a section.
    Returns parsed items and whether malformed data was detected/repaired.
    """
    repaired = False
    items: list[dict] = []

    for payload in _iter_json_bullet_payloads(section_content):
        obj = _decode_json_payload(payload)
        if obj is None:
            repaired = True
            continue

        if kind == "task":
            normalized = _normalize_task(obj)
            repaired = repaired or (normalized != obj)
            obj = normalized
        elif kind == "transaction":
            normalized = _normalize_transaction(obj)
            repaired = repaired or (normalized != obj)
            obj = normalized

        if "\n" in payload:
            repaired = True
        items.append(obj)

    return items, repaired


def _serialize_json_section(items: list[dict]) -> str:
    return "\n".join(f"- {json.dumps(item, ensure_ascii=False)}" for item in items)


def _dedup_transactions(transactions: list[dict]) -> tuple[list[dict], bool]:
    seen = set()
    unique = []
    changed = False
    for tx in transactions:
        key = _transaction_key(tx)
        if key in seen:
            changed = True
            continue
        seen.add(key)
        unique.append(tx)
    return unique, changed


def _dedup_tasks(tasks: list[dict]) -> tuple[list[dict], bool]:
    unique = []
    changed = False
    for task in tasks:
        if _is_low_quality_task(task):
            changed = True
            continue
        duplicate = False
        for existing in unique:
            if _is_similar_task(task, existing):
                duplicate = True
                break
        if duplicate:
            changed = True
            continue
        unique.append(task)
    return unique, changed


def cleanup_memory() -> bool:
    """
    Repair malformed JSON entries and normalize key sections.
    Returns True if MEMORY.md was modified.
    """
    content = _read_memory()
    if not content:
        return False

    changed = False
    section_specs = [
        (SECTION_TASKS, "task"),
        (SECTION_TRANSACTIONS, "transaction"),
        (SECTION_FOOD_DEALS, "generic"),
    ]

    for section, kind in section_specs:
        section_content = _get_section_content(content, section)
        items, repaired = _parse_json_section(section_content, kind=kind)

        if section == SECTION_TASKS:
            items, deduped = _dedup_tasks(items)
            repaired = repaired or deduped
        elif section == SECTION_TRANSACTIONS:
            items, deduped = _dedup_transactions(items)
            repaired = repaired or deduped

        serialized = _serialize_json_section(items)
        if repaired or section_content.strip() != serialized.strip():
            changed = True
            content = _replace_section_content(content, section, serialized)

    if changed:
        content = _update_timestamp(content)
        _write_memory(content)
    return changed


def init_memory():
    """Initialize MEMORY.md with empty sections if it doesn't exist."""
    if MEMORY_PATH.exists():
        cleanup_memory()
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

    existing_section = _get_section_content(content, SECTION_TASKS)
    existing_tasks, _ = _parse_json_section(existing_section, kind="task")
    for raw_task in tasks:
        if not isinstance(raw_task, dict):
            continue
        task = _normalize_task(raw_task)
        title = task.get("title")
        if not isinstance(title, str) or not title.strip():
            continue

        if _is_low_quality_task(task):
            continue

        duplicate = False
        for existing in existing_tasks:
            if _is_similar_task(task, existing):
                duplicate = True
                break
        if duplicate:
            continue

        existing_tasks.append(task)

    new_section = _serialize_json_section(existing_tasks)
    content = _replace_section_content(content, SECTION_TASKS, new_section)
    content = _update_timestamp(content)
    _write_memory(content)


def replace_synced_tasks(tasks: list[dict]):
    """
    Replace non-manual tasks with a fresh sync snapshot.
    Manual tasks are preserved. Completed state is carried forward when keys match.
    """
    content = _read_memory()
    if not content:
        init_memory()
        content = _read_memory()

    existing_section = _get_section_content(content, SECTION_TASKS)
    existing_tasks, _ = _parse_json_section(existing_section, kind="task")

    preserved_manual = [
        task for task in existing_tasks if str(task.get("source", "")).strip().lower() == "manual"
    ]
    done_by_key = {
        _task_key(task): task
        for task in existing_tasks
        if task.get("done") and task.get("title")
    }

    refreshed = []
    for raw_task in tasks:
        if not isinstance(raw_task, dict):
            continue
        task = _normalize_task(raw_task)
        title = task.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        if _is_low_quality_task(task):
            continue

        old = done_by_key.get(_task_key(task))
        if old and old.get("done"):
            task["done"] = True
            if old.get("done_at"):
                task["done_at"] = old.get("done_at")

        duplicate = False
        for existing in refreshed:
            if _is_similar_task(task, existing):
                duplicate = True
                break
        if duplicate:
            continue
        refreshed.append(task)

    merged = preserved_manual + refreshed
    merged, _ = _dedup_tasks(merged)

    new_section = _serialize_json_section(merged)
    content = _replace_section_content(content, SECTION_TASKS, new_section)
    content = _update_timestamp(content)
    _write_memory(content)


def get_all_tasks() -> list[dict]:
    """Read all tasks from MEMORY.md."""
    content = _read_memory()
    if not content:
        return []
    section = _get_section_content(content, SECTION_TASKS)
    tasks, _ = _parse_json_section(section, kind="task")
    tasks, _ = _dedup_tasks(tasks)
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
    tasks, _ = _parse_json_section(section, kind="task")
    updated = False
    query = title.lower()

    for task in tasks:
        task_title = task.get("title", "")
        if isinstance(task_title, str) and query in task_title.lower():
            task["done"] = True
            task["done_at"] = datetime.now(timezone.utc).isoformat()
            updated = True

    if updated:
        new_section = _serialize_json_section(tasks)
        content = _replace_section_content(content, SECTION_TASKS, new_section)
        content = _update_timestamp(content)
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


def add_transaction(transaction: dict) -> bool:
    """Append a financial transaction if it's not already recorded."""
    if not isinstance(transaction, dict):
        return False

    content = _read_memory()
    if not content:
        init_memory()
        content = _read_memory()

    transaction = _normalize_transaction(transaction)
    section = _get_section_content(content, SECTION_TRANSACTIONS)
    transactions, _ = _parse_json_section(section, kind="transaction")
    transactions, _ = _dedup_transactions(transactions)

    existing_keys = {_transaction_key(t) for t in transactions}
    if _transaction_key(transaction) in existing_keys:
        return False

    transactions.append(transaction)
    new_section = _serialize_json_section(transactions)
    content = _replace_section_content(content, SECTION_TRANSACTIONS, new_section)
    content = _update_timestamp(content)
    _write_memory(content)
    return True


def get_transactions() -> list[dict]:
    """Read all transactions from memory (deduplicated)."""
    content = _read_memory()
    if not content:
        return []
    section = _get_section_content(content, SECTION_TRANSACTIONS)
    transactions, _ = _parse_json_section(section, kind="transaction")
    transactions, _ = _dedup_transactions(transactions)
    return transactions


def add_food_deals(deals: list[dict]):
    """Save food deals to memory."""
    content = _read_memory()
    if not content:
        init_memory()
        content = _read_memory()

    lines = []
    for deal in deals:
        if isinstance(deal, dict):
            lines.append(f"- {json.dumps(deal, ensure_ascii=False)}")

    new_section = "\n".join(lines)
    content = _replace_section_content(content, SECTION_FOOD_DEALS, new_section)
    content = _update_timestamp(content)
    _write_memory(content)


def get_food_deals() -> list[dict]:
    """Read food deals from memory."""
    content = _read_memory()
    if not content:
        return []
    section = _get_section_content(content, SECTION_FOOD_DEALS)
    deals, _ = _parse_json_section(section, kind="generic")
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
