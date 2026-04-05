"""
Telegram bot for ClawCampus.
Commands: /start, /digest, /tasks, /done, /draft, /deals, /spend, /help
Also handles forwarded messages → extract tasks.
"""

import os
import logging
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from memory_manager import init_memory, add_tasks, mark_task_done, get_pending_tasks
from task_extractor import extract_from_text, extract_all_sources
from digest_builder import build_digest, build_task_list
from email_drafter import draft_reply_for_latest
from food_scanner import get_todays_deals_message
from finance_tracker import parse_transaction_text, get_spending_summary

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clawcampus")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    init_memory()
    await update.message.reply_text(
        "Hey! I'm ClawCampus, your student life agent.\n\n"
        "Here's what I can do:\n"
        "/digest — Get your daily summary\n"
        "/tasks — See all pending tasks\n"
        "/done <task> — Mark a task as done\n"
        "/draft — Draft a reply to your latest email\n"
        "/deals — Today's food deals near you\n"
        "/spend — Weekly spending summary\n"
        "/sync — Sync Canvas + emails\n"
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded messages or plain text — extract tasks."""
    text = update.message.text
    if not text:
        await update.message.reply_text("Send me some text and I'll extract tasks from it!")
        return

    await update.message.reply_text("Analyzing your message...")

    # Check if it looks like a receipt/transaction
    transaction = parse_transaction_text(text)
    if transaction:
        from memory_manager import add_transaction
        add_transaction(transaction)
        await update.message.reply_text(
            f"Recorded: ${transaction['amount']:.2f} at {transaction['merchant']}"
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
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("deals", cmd_deals))
    app.add_handler(CommandHandler("spend", cmd_spend))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

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

    print("Simulating /digest:")
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
