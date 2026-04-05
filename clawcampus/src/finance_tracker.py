"""
Finance tracker — parses transaction emails and tracks spending.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from memory_manager import add_transaction, get_transactions


def parse_transaction_text(text: str) -> dict | None:
    """
    Try to parse a financial transaction from text.
    Looks for patterns like "$12.29", "Total: $X.XX", receipt-like content.
    Returns a transaction dict or None if no transaction found.
    """
    # Look for total amount pattern
    total_match = re.search(r"[Tt]otal[:\s]*\$?([\d,]+\.?\d*)", text)
    amount = None
    if total_match:
        amount = float(total_match.group(1).replace(",", ""))
    else:
        # Look for any dollar amount
        amounts = re.findall(r"\$([\d,]+\.\d{2})", text)
        if amounts:
            # Take the largest amount as the total
            amount = max(float(a.replace(",", "")) for a in amounts)

    if amount is None or amount <= 0:
        return None

    # Extract merchant name
    merchant = "Unknown"
    # Check for common patterns
    for pattern in [
        r"(?:from|at|@)\s+([A-Za-z\s&']+?)(?:\s*[-—(]|\n|$)",
        r"Order.*?(?:from|at)\s+([A-Za-z\s&']+)",
        r"^([A-Za-z\s&']{3,30})\s*(?:\(|—|-)",
    ]:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            merchant = match.group(1).strip()
            break

    # Extract date
    date_match = re.search(
        r"(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})",
        text,
    )
    date_str = date_match.group(1) if date_match else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Categorize
    category = _categorize(text, merchant)

    return {
        "merchant": merchant,
        "amount": amount,
        "date": date_str,
        "category": category,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _categorize(text: str, merchant: str) -> str:
    """Simple rule-based spending categorization."""
    text_lower = (text + " " + merchant).lower()
    if any(w in text_lower for w in ["food", "restaurant", "cafe", "grab", "foodpanda", "biryani", "coffee", "tea", "lunch", "dinner"]):
        return "food"
    if any(w in text_lower for w in ["transport", "bus", "mrt", "taxi", "grab ride"]):
        return "transport"
    if any(w in text_lower for w in ["book", "textbook", "stationery", "print"]):
        return "academic"
    if any(w in text_lower for w in ["spotify", "netflix", "subscription", "premium"]):
        return "entertainment"
    return "other"


def parse_transaction_email(email: dict) -> dict | None:
    """Parse a transaction from an email dict."""
    text = f"{email.get('subject', '')}\n{email.get('body', '')}"
    return parse_transaction_text(text)


def get_spending_summary() -> str:
    """Generate a spending summary from memory."""
    transactions = get_transactions()
    if not transactions:
        return "\U0001f4b0 No spending recorded yet.\nForward me receipts or transaction emails to track spending!"

    total = sum(t.get("amount", 0) for t in transactions)

    # Group by category
    by_category: dict[str, float] = {}
    for t in transactions:
        cat = t.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + t.get("amount", 0)

    lines = [
        f"\U0001f4ca Spending Summary\n",
        f"Total: ${total:.2f}",
        f"Transactions: {len(transactions)}\n",
        "By category:",
    ]

    category_emoji = {
        "food": "\U0001f354",
        "transport": "\U0001f68c",
        "academic": "\U0001f4da",
        "entertainment": "\U0001f3ac",
        "other": "\U0001f4e6",
    }

    for cat, amt in sorted(by_category.items(), key=lambda x: -x[1]):
        emoji = category_emoji.get(cat, "\U0001f4e6")
        lines.append(f"  {emoji} {cat.title()}: ${amt:.2f}")

    # Budget check
    weekly_budget = 70.0  # Default budget
    if total > weekly_budget * 0.8:
        lines.append(f"\n\u26a0\ufe0f Heads up: you've spent ${total:.2f} of your ${weekly_budget:.2f} weekly budget!")
    else:
        remaining = weekly_budget - total
        lines.append(f"\n\u2705 ${remaining:.2f} remaining of ${weekly_budget:.2f} weekly budget")

    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Finance Tracker Test ===\n")

    # Test parsing a GrabFood receipt
    test_receipt = """Your GrabFood receipt — Al Amaan Express

Order #GF-88291034
Al Amaan Express (Clementi)

1x Chicken Biryani Set — $7.50
1x Teh Tarik — $2.00
Delivery fee — $2.49
Platform fee — $0.30

Total: $12.29
Paid via GrabPay Wallet

Date: 4 April 2026, 7:45 PM"""

    result = parse_transaction_text(test_receipt)
    if result:
        print(f"Parsed transaction: {result}")
        add_transaction(result)
    else:
        print("Could not parse transaction.")

    print(f"\n{get_spending_summary()}")
