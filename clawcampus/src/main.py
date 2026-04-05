#!/usr/bin/env python3
"""
ClawCampus — Student Life Agent
Entry point: bootstraps the OpenClaw agent, initializes memory, and starts the Telegram bot.

Usage:
    python main.py              # Start Telegram bot (or mock demo if no token)
    python main.py --sync       # Run one-time sync from Canvas + Outlook
    python main.py --digest     # Generate and print daily digest
    python main.py --jobmatch [--email-file email.txt] [--resume-file resume.txt] [--prefs-file prefs.txt]
    python main.py --demo       # Run full demo flow with mock data
"""

import sys
import os

# Add src to path for local imports
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from memory_manager import init_memory, add_tasks, add_food_deals, add_transaction
from task_extractor import extract_all_sources
from digest_builder import build_digest, build_task_list
from email_drafter import draft_reply_for_latest
from food_scanner import sync_deals_to_memory, get_todays_deals_message
from finance_tracker import parse_transaction_email, get_spending_summary
from job_matcher import (
    run_job_matching,
    format_job_matching_report,
    filter_job_related_emails,
    email_to_jobmatch_text,
    load_default_profile_text,
)
from outlook_client import get_inbox, get_unread_emails
from telegram_bot import run_bot


def run_sync():
    """Sync all sources: Canvas assignments, events, emails → memory."""
    print("Syncing Canvas + Outlook...")
    tasks = extract_all_sources()
    add_tasks(tasks)
    print(f"  Extracted {len(tasks)} tasks.")

    # Sync food deals
    deals = sync_deals_to_memory()
    print(f"  Found {len(deals)} food deals for today.")

    # Parse financial transactions from emails
    tx_count = 0
    for email in get_inbox():
        tx = parse_transaction_email(email)
        if tx and add_transaction(tx):
            tx_count += 1
    print(f"  Recorded {tx_count} transactions.")

    return tasks


def run_digest():
    """Generate and print the daily digest."""
    print(build_digest())


def _arg_value(flag: str) -> str | None:
    if flag not in sys.argv:
        return None
    idx = sys.argv.index(flag)
    if idx + 1 >= len(sys.argv):
        return None
    return sys.argv[idx + 1]


def _read_text_file(path: str | None) -> str:
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        print(f"Could not read file '{path}': {exc}")
        return ""


def run_jobmatch():
    """
    Run job matching + resume tailoring from local files.

    Usage:
        python main.py --jobmatch [--email-file email.txt] [--resume-file resume.txt] [--prefs-file prefs.txt] [--top 5]
    """
    email_file = _arg_value("--email-file")
    resume_file = _arg_value("--resume-file")
    prefs_file = _arg_value("--prefs-file")
    top_text = _arg_value("--top") or "5"

    try:
        top_k = max(1, min(5, int(top_text)))
    except ValueError:
        top_k = 5

    resume_text = _read_text_file(resume_file)
    goals_text = _read_text_file(prefs_file)
    if not resume_text.strip():
        resume_text = load_default_profile_text()

    if not email_file:
        unread = get_unread_emails()
        job_emails = filter_job_related_emails(unread)
        if not job_emails:
            print("No job-related unread emails found.")
            print("Tip: use --email-file to analyze a specific job alert.")
            return

        print(f"Found {len(job_emails)} job-related unread email(s). Processing top {min(3, len(job_emails))}...")
        for idx, email in enumerate(job_emails[:3], start=1):
            subject = email.get("subject", "No Subject")
            sender = email.get("from", "unknown")
            email_text = email_to_jobmatch_text(email)
            result = run_job_matching(
                master_resume=resume_text,
                email_text=email_text,
                goals_preferences=goals_text,
                top_k=top_k,
            )
            print()
            print("=" * 80)
            print(f"[{idx}] Subject: {subject}")
            print(f"    From: {sender}")
            print("=" * 80)
            print(format_job_matching_report(result))
        return

    email_text = _read_text_file(email_file)

    if not email_text.strip():
        print("Email content is empty. Check --email-file input.")
        return

    print("Running job extraction, ranking, and tailoring...")
    result = run_job_matching(
        master_resume=resume_text,
        email_text=email_text,
        goals_preferences=goals_text,
        top_k=top_k,
    )
    print()
    print(format_job_matching_report(result))


def run_demo():
    """Full demo flow with mock data."""
    print("=" * 50)
    print("  ClawCampus Demo — Student Life Agent")
    print("=" * 50)

    # Step 1: Initialize
    print("\n[1/5] Initializing memory...")
    init_memory()

    # Step 2: Sync all sources
    print("\n[2/5] Syncing Canvas + Outlook...")
    tasks = run_sync()

    # Step 3: Daily digest
    print("\n[3/5] Daily Digest:")
    print("-" * 40)
    print(build_digest())

    # Step 4: Email drafting
    print("\n[4/5] Email Draft:")
    print("-" * 40)
    print(draft_reply_for_latest())

    # Step 5: Food deals + spending
    print("\n[5/5] Food Deals & Spending:")
    print("-" * 40)
    print(get_todays_deals_message())
    print()
    print(get_spending_summary())

    print("\n" + "=" * 50)
    print("  Demo complete! All features working.")
    print("=" * 50)


def main():
    init_memory()

    if "--sync" in sys.argv:
        run_sync()
    elif "--digest" in sys.argv:
        run_digest()
    elif "--jobmatch" in sys.argv:
        run_jobmatch()
    elif "--demo" in sys.argv:
        run_demo()
    else:
        # Default: start Telegram bot
        run_bot()


if __name__ == "__main__":
    main()
