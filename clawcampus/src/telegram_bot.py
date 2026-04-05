"""
Telegram bot for ClawCampus.
Commands: /start, /digest, /tasks, /done, /draft, /deals, /spend, /jobmatch, /brief, /help
Also handles forwarded messages → extract tasks.
"""

import os
import logging
from dotenv import load_dotenv

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from memory_manager import init_memory, add_tasks, mark_task_done, get_pending_tasks
from task_extractor import extract_from_text, extract_all_sources
from canvas_client import (
    get_courses,
    get_todo_items,
    get_upcoming_events,
    get_assignment_brief,
    list_assignment_titles,
)
from outlook_client import get_unread_emails
from digest_builder import build_digest, build_task_list
from email_drafter import draft_reply_for_latest
from food_scanner import get_todays_deals_message
from finance_tracker import parse_transaction_text, get_spending_summary
from assignment_coach import analyze_assignment_brief, format_assignment_study_guide
from job_matcher import (
    parse_jobmatch_sections,
    looks_like_jobmatch_request,
    is_job_related_text,
    filter_job_related_emails,
    email_to_jobmatch_text,
    load_default_profile_text,
    run_job_matching,
    format_job_matching_report,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clawcampus")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _chunk_message(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _jobmatch_template() -> str:
    return (
        "Run /jobmatch with no arguments to scan unread job-related emails.\n\n"
        "Or send /jobmatch followed by this template:\n\n"
        "Here is my master resume/profile:\n"
        "[PASTE YOUR MASTER RESUME HERE]\n\n"
        "Here is the email to analyze:\n"
        "[PASTE THE JOB ALERT EMAIL HERE]\n\n"
        "My goals and preferences:\n"
        "- Preferred roles:\n"
        "- Preferred industries:\n"
        "- Preferred internship period:\n"
        "- Roles I do NOT want:\n"
        "- Strongest skills:\n"
        "- Weakest areas:\n"
        "- Anything else relevant:"
    )


async def _run_jobmatch_and_reply(
    message,
    *,
    master_resume: str,
    email_text: str,
    goals_preferences: str,
):
    await message.reply_text("Analyzing listings and tailoring resume drafts. This may take up to a minute...")
    result = run_job_matching(
        master_resume=master_resume,
        email_text=email_text,
        goals_preferences=goals_preferences,
        top_k=5,
    )
    report = format_job_matching_report(result)
    for part in _chunk_message(report):
        await message.reply_text(part)


async def _run_jobmatch_for_inbox_emails(
    message,
    *,
    announce_if_none: bool = True,
    max_emails: int = 3,
):
    unread = get_unread_emails()
    job_emails = filter_job_related_emails(unread)
    if not job_emails:
        if announce_if_none:
            await message.reply_text(
                "No job-related unread emails found right now.\n\n"
                "You can still use /jobmatch with pasted email content."
            )
        return

    profile_text = load_default_profile_text()
    limited = job_emails[: max(1, max_emails)]
    await message.reply_text(
        f"Found {len(job_emails)} job-related unread email(s). "
        f"Processing {len(limited)} most recent now..."
    )

    for idx, email in enumerate(limited, start=1):
        subject = email.get("subject", "No Subject")
        sender = email.get("from", "unknown")
        header = f"Job Email {idx}/{len(limited)}\nSubject: {subject}\nFrom: {sender}\n"
        result = run_job_matching(
            master_resume=profile_text,
            email_text=email_to_jobmatch_text(email),
            goals_preferences="",
            top_k=5,
        )
        report = header + "\n" + format_job_matching_report(result)
        for part in _chunk_message(report):
            await message.reply_text(part)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    init_memory()
    message = update.effective_message or update.message
    if not message:
        return
    await message.reply_text(
        "Hey! I'm ClawCampus, your student life agent.\n\n"
        "Here's what I can do:\n"
        "/digest — Get your daily summary\n"
        "/tasks — See all pending tasks\n"
        "/done <task> — Mark a task as done\n"
        "/draft — Draft a reply to your latest email\n"
        "/deals — Today's food deals near you\n"
        "/spend — Weekly spending summary\n"
        "/jobmatch — Scan unread job emails or paste one manually\n"
        "/brief — Analyze assignment brief + reading plan\n"
        "/sync — Sync Canvas + emails\n"
        "/canvas — View current Canvas assignments and events\n"
        "/courses — List your Canvas courses\n"
        "/help — Show this message\n\n"
        "You can also forward me any message and I'll extract tasks from it!"
    )


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the daily digest."""
    digest = build_digest()
    await update.message.reply_text(digest)


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all pending tasks."""
    task_list = build_task_list()
    await update.message.reply_text(task_list)


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark a task as done."""
    if not context.args:
        await update.message.reply_text("Usage: /done <task name or keyword>")
        return
    query = " ".join(context.args)
    if mark_task_done(query):
        await update.message.reply_text(f"Done! Marked '{query}' as completed.")
    else:
        await update.message.reply_text(f"Couldn't find a task matching '{query}'.")


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sync tasks from Canvas and Outlook."""
    await update.message.reply_text("Syncing Canvas + emails...")
    tasks = extract_all_sources()
    add_tasks(tasks)
    await update.message.reply_text(
        f"Synced! Found {len(tasks)} items.\n\n" + build_task_list()
    )
    await _run_jobmatch_for_inbox_emails(update.message, announce_if_none=False, max_emails=2)


async def cmd_canvas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current Canvas assignments and events."""
    todos = get_todo_items()
    events = get_upcoming_events()
    lines = []

    if todos:
        lines.append("\U0001f4dd Canvas Assignments:")
        for item in todos:
            assignment = item.get("assignment", {})
            title = assignment.get("name", "Untitled")
            due = assignment.get("due_at") or "no deadline"
            course = item.get("context_name", "Unknown course")
            lines.append(f"  \u2022 {title} ({course}) — due {due}")
            if assignment.get("html_url"):
                lines.append(f"    {assignment.get('html_url')}")
        lines.append("")
    else:
        lines.append("No Canvas assignments found.")

    if events:
        lines.append("\U0001f4c5 Canvas Events:")
        for event in events:
            title = event.get("title", "Untitled event")
            start = event.get("start_at") or "TBA"
            course = event.get("context_name", "Unknown course")
            location = event.get("location_name", "TBA")
            lines.append(f"  \u2022 {title} ({course}) — {start} @ {location}")
        lines.append("")
    else:
        lines.append("No upcoming Canvas events found.")

    await update.message.reply_text("\n".join(lines))


async def cmd_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List enrolled Canvas courses."""
    courses = get_courses()
    if not courses:
        await update.message.reply_text("No Canvas courses found.")
        return

    lines = ["\U0001f393 Enrolled Canvas Courses:"]
    for course in courses:
        lines.append(f"  \u2022 {course.get('name')} (ID: {course.get('id')})")
    await update.message.reply_text("\n".join(lines))


async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Analyze an assignment brief and suggest lecture slides/sources to read.

    Usage:
      /brief <assignment keyword>    # fetch brief from Canvas by title/id
      /brief text: <brief text...>   # analyze pasted brief directly
    """
    message = update.effective_message or update.message
    if not message or not message.text:
        return

    raw = message.text
    payload = raw.split(maxsplit=1)[1].strip() if " " in raw.strip() else ""

    if not payload:
        titles = list_assignment_titles(limit=8)
        lines = [
            "Usage: /brief <assignment keyword>",
            "Or: /brief text: <paste assignment brief>",
        ]
        if titles:
            lines.append("")
            lines.append("Current Canvas assignments:")
            for title in titles:
                lines.append(f"  • {title}")
        await message.reply_text("\n".join(lines))
        return

    lower_payload = payload.lower()
    manual_prefixes = ("text:", "brief:", "manual:")
    manual_mode = any(lower_payload.startswith(prefix) for prefix in manual_prefixes)
    likely_full_text = (len(payload) > 220 and "\n" in payload) or len(payload) > 500

    if manual_mode or likely_full_text:
        brief_text = payload.split(":", 1)[1].strip() if manual_mode and ":" in payload else payload.strip()
        assignment_meta = {
            "title": "Manual assignment brief",
            "course_name": "",
            "due_at": None,
            "source_url": None,
        }
    else:
        await message.reply_text("Downloading assignment brief from Canvas...")
        assignment_meta = get_assignment_brief(payload)
        if not assignment_meta:
            titles = list_assignment_titles(limit=8)
            lines = [
                f"I couldn't find a Canvas assignment matching '{payload}'.",
                "Try using a more specific keyword or assignment ID.",
            ]
            if titles:
                lines.append("")
                lines.append("Available assignments:")
                for title in titles:
                    lines.append(f"  • {title}")
            await message.reply_text("\n".join(lines))
            return
        brief_text = assignment_meta.get("brief_text", "")

    if not brief_text.strip():
        await message.reply_text(
            "I found the assignment metadata, but no brief text was available. "
            "Paste the brief directly with /brief text: ..."
        )
        return

    await message.reply_text("Analyzing brief and building your reading plan...")
    analysis = analyze_assignment_brief(
        brief_text,
        assignment_title=assignment_meta.get("title", ""),
        course_name=assignment_meta.get("course_name", ""),
        due_at=assignment_meta.get("due_at"),
    )
    report = format_assignment_study_guide(
        analysis,
        assignment_title=assignment_meta.get("title", ""),
        course_name=assignment_meta.get("course_name", ""),
        due_at=assignment_meta.get("due_at"),
        source_url=assignment_meta.get("source_url"),
    )
    for chunk in _chunk_message(report):
        await message.reply_text(chunk)


async def cmd_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Draft an email reply."""
    await update.message.reply_text("Drafting a reply to your latest email...")
    result = draft_reply_for_latest()
    await update.message.reply_text(result)


async def cmd_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's food deals."""
    msg = get_todays_deals_message()
    await update.message.reply_text(msg)


async def cmd_spend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show spending summary."""
    msg = get_spending_summary()
    await update.message.reply_text(msg)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help."""
    await cmd_start(update, context)


async def cmd_jobmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Run job matching + resume tailoring.
    Expects the message payload to include:
    - master resume/profile
    - email to analyze
    - goals and preferences
    """
    message = update.effective_message or update.message
    if not message or not message.text:
        return

    raw = message.text
    payload = raw.split(maxsplit=1)[1].strip() if " " in raw.strip() else ""

    if not payload:
        await _run_jobmatch_for_inbox_emails(message, announce_if_none=True, max_emails=3)
        return

    if payload.lower() in {"inbox", "emails", "scan"}:
        await _run_jobmatch_for_inbox_emails(message, announce_if_none=True, max_emails=3)
        return

    parsed = parse_jobmatch_sections(payload)
    if parsed:
        await _run_jobmatch_and_reply(
            message,
            master_resume=parsed.get("master_resume", ""),
            email_text=parsed.get("email_text", ""),
            goals_preferences=parsed.get("goals_preferences", ""),
        )
        return

    # Fallback mode: treat payload as email-only request.
    await _run_jobmatch_and_reply(
        message,
        master_resume="",
        email_text=payload,
        goals_preferences="",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded messages or plain text — extract tasks."""
    text = update.message.text
    if not text:
        await update.message.reply_text("Send me some text and I'll extract tasks from it!")
        return

    parsed = parse_jobmatch_sections(text)
    if parsed:
        await _run_jobmatch_and_reply(
            update.message,
            master_resume=parsed.get("master_resume", ""),
            email_text=parsed.get("email_text", ""),
            goals_preferences=parsed.get("goals_preferences", ""),
        )
        return

    if is_job_related_text(text) and len(text) >= 120:
        await _run_jobmatch_and_reply(
            update.message,
            master_resume=load_default_profile_text(),
            email_text=text,
            goals_preferences="",
        )
        return

    if looks_like_jobmatch_request(text) and len(text) > 300:
        await _run_jobmatch_and_reply(
            update.message,
            master_resume="",
            email_text=text,
            goals_preferences="",
        )
        return

    await update.message.reply_text("Analyzing your message...")

    # Check if it looks like a receipt/transaction
    transaction = parse_transaction_text(text)
    if transaction:
        from memory_manager import add_transaction
        added = add_transaction(transaction)
        status = "Recorded" if added else "Already recorded"
        await update.message.reply_text(
            f"{status}: ${transaction['amount']:.2f} at {transaction['merchant']}"
        )
        return

    # Otherwise extract tasks
    tasks = extract_from_text(text, source="manual")
    if tasks:
        add_tasks(tasks)
        task_lines = []
        for t in tasks:
            due = f" — due {t['due_date']}" if t.get("due_date") else ""
            task_lines.append(f"  \u2022 {t['title']}{due}")
        await update.message.reply_text(
            f"Found {len(tasks)} task(s):\n" + "\n".join(task_lines) + "\n\nSaved to memory!"
        )
    else:
        await update.message.reply_text("Couldn't find any tasks in that message.")


def run_bot():
    """Start the Telegram bot."""
    if not BOT_TOKEN:
        print("[telegram_bot] No TELEGRAM_BOT_TOKEN set. Running in mock mode.")
        print("[telegram_bot] Set TELEGRAM_BOT_TOKEN in .env to connect to Telegram.")
        _run_mock_demo()
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("canvas", cmd_canvas))
    app.add_handler(CommandHandler("courses", cmd_courses))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("deals", cmd_deals))
    app.add_handler(CommandHandler("spend", cmd_spend))
    app.add_handler(CommandHandler("jobmatch", cmd_jobmatch))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.bot.set_my_commands([
        BotCommand("start", "Show welcome/help"),
        BotCommand("digest", "Get your daily summary"),
        BotCommand("tasks", "See all pending tasks"),
        BotCommand("sync", "Sync Canvas + emails"),
        BotCommand("canvas", "View current Canvas assignments/events"),
        BotCommand("courses", "List your Canvas courses"),
        BotCommand("jobmatch", "Scan job emails / run matching"),
        BotCommand("brief", "Analyze assignment brief + reading plan"),
    ])
    logger.info("ClawCampus bot started! Listening for messages...")
    app.run_polling()


def _run_mock_demo():
    """Run a mock demo showing what the bot would output."""
    print("\n=== ClawCampus Mock Demo ===\n")
    print("Simulating /start:")
    print("  Hey! I'm ClawCampus, your student life agent.\n")

    print("Simulating /sync:")
    tasks = extract_all_sources()
    add_tasks(tasks)
    print(f"  Synced! Found {len(tasks)} items.\n")

    print("Simulating /canvas:")
    todos = get_todo_items()
    events = get_upcoming_events()
    print(f"  Canvas assignments: {len(todos)}")
    print(f"  Canvas events: {len(events)}\n")

    print("Simulating /courses:")
    courses = get_courses()
    for course in courses:
        print(f"  - {course.get('name')} (ID: {course.get('id')})")
    print("\nSimulating /digest:")
    print(build_digest())

    print("\nSimulating /tasks:")
    print(build_task_list())

    print("\nSimulating /deals:")
    print(get_todays_deals_message())

    print("\nSimulating /spend:")
    print(get_spending_summary())


if __name__ == "__main__":
    init_memory()
    run_bot()
