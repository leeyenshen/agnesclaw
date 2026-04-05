"""
Daily digest generator.
Reads tasks from memory, groups by urgency, formats a Telegram-friendly message.
Optionally uses Agnes for a personalized summary.
"""
from __future__ import annotations

from datetime import datetime

from memory_manager import get_pending_tasks, get_food_deals, get_transactions
from finance_tracker import get_weekly_transactions
from time_utils import now_local, parse_iso_datetime


URGENCY_EMOJI = {
    "urgent": "\U0001f534",  # red circle
    "soon": "\U0001f7e1",    # yellow circle
    "later": "\U0001f7e2",   # green circle
    "info": "\u2139\ufe0f",  # info
}

URGENCY_HEADER = {
    "urgent": "URGENT",
    "soon": "THIS WEEK",
    "later": "COMING UP",
    "info": "FYI",
}


def _format_due(due_str: str | None) -> str:
    """Format a due date into a human-readable string."""
    if not due_str:
        return "no deadline"
    due = parse_iso_datetime(due_str)
    if not due:
        return due_str

    now = now_local()
    due_local = due.astimezone(now.tzinfo)
    delta_hours = (due_local - now).total_seconds() / 3600

    if delta_hours < 0:
        return "OVERDUE"
    if delta_hours < 24:
        return f"due TODAY {due_local.strftime('%I:%M %p')}"
    if delta_hours < 48:
        return f"due TOMORROW {due_local.strftime('%I:%M %p')}"
    return f"due {due_local.strftime('%a %d %b')}"


def build_digest() -> str:
    """Build the full daily digest message."""
    tasks = get_pending_tasks()
    deals = get_food_deals()
    transactions = get_transactions()

    now = now_local()
    greeting = _get_greeting(now)

    lines = [f"{greeting}\n"]

    # Group tasks by urgency
    grouped: dict[str, list[dict]] = {"urgent": [], "soon": [], "later": [], "info": []}
    for task in tasks:
        urgency = task.get("urgency", "info")
        grouped.setdefault(urgency, []).append(task)

    for urgency in ["urgent", "soon", "later", "info"]:
        items = grouped.get(urgency, [])
        if not items:
            continue
        emoji = URGENCY_EMOJI.get(urgency, "")
        header = URGENCY_HEADER.get(urgency, urgency.upper())
        lines.append(f"{emoji} {header}")
        for task in items:
            due_text = _format_due(task.get("due_date"))
            course = f" ({task['course']})" if task.get("course") else ""
            lines.append(f"  \u2022 {task['title']}{course} \u2014 {due_text}")
        lines.append("")

    # Food deals section
    today_str = now.strftime("%Y-%m-%d")
    today_deals = [d for d in deals if d.get("valid_date", "") == today_str]
    if today_deals:
        lines.append("\U0001f37d\ufe0f DEALS NEAR YOU")
        for deal in today_deals:
            lines.append(f"  \u2022 {deal.get('deal', '')} @ {deal.get('merchant', '')}")
        lines.append("")

    # Spending summary
    weekly_transactions = get_weekly_transactions(transactions, now=now)
    if weekly_transactions:
        week_total = sum(t.get("amount", 0) for t in weekly_transactions)
        lines.append(f"\U0001f4ca SPENDING THIS WEEK: ${week_total:.2f}")
        lines.append("")

    lines.append("Need help with anything? Just ask!")

    return "\n".join(lines)


def build_task_list() -> str:
    """Build a concise task list (for /tasks command)."""
    tasks = get_pending_tasks()
    if not tasks:
        return "No pending tasks! You're all caught up."

    lines = ["\U0001f4cb Your Tasks\n"]
    for task in tasks:
        emoji = URGENCY_EMOJI.get(task.get("urgency", "info"), "")
        due_text = _format_due(task.get("due_date"))
        course = f" [{task.get('course', '')}]" if task.get("course") else ""
        lines.append(f"{emoji} {task['title']}{course} \u2014 {due_text}")

    return "\n".join(lines)


def _get_greeting(now: datetime) -> str:
    """Time-appropriate greeting."""
    hour = now.hour
    if hour < 12:
        return "\u2600\ufe0f Good morning! Here's your day:"
    elif hour < 17:
        return "\U0001f31e Good afternoon! Here's your update:"
    else:
        return "\U0001f319 Good evening! Here's your update:"


if __name__ == "__main__":
    # Initialize memory with sample data for testing
    from memory_manager import init_memory, add_tasks, add_food_deals, add_transaction

    init_memory()
    add_tasks([
        {"title": "CS2040S Lab 5", "course": "CS2040S", "due_date": "2026-04-10T15:59:00Z", "urgency": "soon", "source": "canvas"},
        {"title": "Reply to Prof. Tan's email", "course": "CS2040S", "due_date": "2026-04-06T23:59:00Z", "urgency": "urgent", "source": "email"},
        {"title": "MA2001 Group Project", "course": "MA2001", "due_date": "2026-04-11T09:00:00Z", "urgency": "soon", "source": "canvas"},
        {"title": "Bloomberg Workshop RSVP", "course": None, "due_date": "2026-04-07T23:59:00Z", "urgency": "soon", "source": "email"},
        {"title": "GEA1000 AI Ethics Essay", "course": "GEA1000", "due_date": "2026-04-18T15:59:00Z", "urgency": "later", "source": "canvas"},
    ])
    add_food_deals([
        {"merchant": "Koufu (UTown)", "deal": "1-for-1 Chicken Cutlet", "valid_date": now_local().strftime("%Y-%m-%d")},
    ])
    add_transaction({"merchant": "Al Amaan Express", "amount": 12.29, "date": "2026-04-04"})

    print("=== Daily Digest ===\n")
    print(build_digest())
    print("\n=== Task List ===\n")
    print(build_task_list())
