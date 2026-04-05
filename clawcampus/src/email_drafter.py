"""
Email draft automation using Agnes-1.5-Pro.
Identifies emails needing replies and drafts contextual responses.
"""

from agnes_client import call_agnes_pro
from outlook_client import get_unread_emails, send_email

DRAFT_PROMPT = """You are a polite NUS student drafting an email reply. The tone should be:
- Professional but not stiff
- Respectful (use "Prof." or "Dr." for faculty, first name for peers)
- Concise — students are busy

Given the original email below, draft a suitable reply. If it's:
- A professor's email: acknowledge, confirm understanding, ask clarification if needed
- An event/volunteer email: RSVP or express interest politely
- A peer's email: confirm attendance/action, be friendly

Output ONLY the reply body text. No subject line, no "Dear X" — just the body.
Start with an appropriate greeting like "Hi Prof. Tan," or "Hey Jun Hao,".
End with "Best regards," followed by a newline and "[Your Name]"."""


def draft_reply(email: dict) -> str:
    """Draft a reply to a specific email using Agnes."""
    email_text = (
        f"From: {email.get('from', 'unknown')}\n"
        f"Subject: {email.get('subject', 'No Subject')}\n"
        f"Date: {email.get('date', '')}\n\n"
        f"{email.get('body', '')}"
    )

    try:
        reply = call_agnes_pro([
            {"role": "system", "content": DRAFT_PROMPT},
            {"role": "user", "content": email_text},
        ])
        return reply.strip()
    except Exception as e:
        return _fallback_draft(email)


def _fallback_draft(email: dict) -> str:
    """Simple rule-based fallback if Agnes is unavailable."""
    sender = email.get("from", "")
    subject = email.get("subject", "")

    # Determine greeting
    if "prof" in sender.lower() or "edu.sg" in sender and "@u." not in sender:
        # Faculty email
        name = sender.split("@")[0]
        # Try to extract surname
        greeting = f"Hi Prof. {name.title()},"
        body = (
            f"Thank you for the update regarding \"{subject}\". "
            "Noted with thanks — I will follow up accordingly.\n\n"
            "Please let me know if there's anything else I should be aware of."
        )
    elif "@u.nus.edu" in sender:
        # Peer email
        name = sender.split("@")[0]
        greeting = f"Hey {name.title()},"
        body = (
            f"Thanks for reaching out about \"{subject}\". "
            "Sounds good — I'll be there.\n\n"
            "Let me know if anything changes!"
        )
    else:
        # Generic
        greeting = "Hi,"
        body = (
            f"Thank you for the email regarding \"{subject}\". "
            "Noted — I'll follow up as needed."
        )

    return f"{greeting}\n\n{body}\n\nBest regards,\n[Your Name]"


def draft_reply_for_latest() -> str:
    """Find the most recent unread email and draft a reply."""
    unread = get_unread_emails()
    if not unread:
        return "No unread emails to reply to!"

    email = unread[0]
    draft = draft_reply(email)

    return (
        f"Replying to: {email.get('subject', 'No Subject')}\n"
        f"From: {email.get('from', 'unknown')}\n"
        f"{'=' * 40}\n\n"
        f"{draft}\n\n"
        f"{'=' * 40}\n"
        "Send this reply? (This is a draft — not sent yet)"
    )


def send_draft(email: dict, draft_body: str) -> dict:
    """Send an approved draft reply."""
    to = email.get("from", "")
    subject = f"Re: {email.get('subject', '')}"
    return send_email(to, subject, draft_body, draft_only=True)


if __name__ == "__main__":
    print("=== Email Drafter Test ===\n")
    emails = get_unread_emails()
    for email in emails:
        print(f"--- Drafting reply to: {email['subject']} ---")
        draft = draft_reply(email)
        print(draft)
        print()
