"""
Food deal scanner — surfaces deals near NUS campus.
Reads from mock_data/food_deals.json and memory.
"""
from __future__ import annotations

import json
from pathlib import Path

from memory_manager import add_food_deals, get_food_deals
from time_utils import now_local

MOCK_DIR = Path(__file__).parent.parent / "mock_data"


def load_all_deals() -> list[dict]:
    """Load deals from mock data file."""
    path = MOCK_DIR / "food_deals.json"
    with open(path) as f:
        return json.load(f)


def get_todays_deals() -> list[dict]:
    """Filter deals valid today."""
    today = now_local().strftime("%Y-%m-%d")
    all_deals = load_all_deals()
    return [d for d in all_deals if d.get("valid_date", "") == today]


def sync_deals_to_memory():
    """Save today's deals to memory."""
    deals = get_todays_deals()
    if deals:
        add_food_deals(deals)
    return deals


def get_todays_deals_message() -> str:
    """Format today's deals as a Telegram message."""
    deals = get_todays_deals()
    if not deals:
        # Check all upcoming deals
        all_deals = load_all_deals()
        if all_deals:
            lines = ["\U0001f37d\ufe0f No deals today, but coming up:\n"]
            for deal in all_deals[:3]:
                lines.append(
                    f"  \u2022 {deal.get('deal', '')} @ {deal.get('merchant', '')} "
                    f"— {deal.get('valid_date', '')}"
                )
            return "\n".join(lines)
        return "No food deals found. Check back later!"

    lines = ["\U0001f37d\ufe0f Today's Deals Near NUS\n"]
    for deal in deals:
        lines.append(f"\u2022 {deal.get('deal', '')}")
        lines.append(f"  \U0001f4cd {deal.get('merchant', '')} ({deal.get('location', '')})")
        if deal.get("meal_period"):
            lines.append(f"  \u23f0 {deal['meal_period'].replace('_', ' ').title()}")
        if deal.get("notes"):
            lines.append(f"  \U0001f4ac {deal['notes']}")
        lines.append("")

    return "\n".join(lines)


def get_deals_near(building: str) -> list[dict]:
    """Find deals near a specific building."""
    deals = get_todays_deals()
    result = []
    for deal in deals:
        near = deal.get("near_buildings", [])
        if any(building.lower() in b.lower() for b in near):
            result.append(deal)
    return result


if __name__ == "__main__":
    print("=== Food Deal Scanner Test ===\n")
    print(get_todays_deals_message())
    print("\nAll available deals:")
    for deal in load_all_deals():
        print(f"  {deal['merchant']}: {deal['deal']} (valid: {deal['valid_date']})")
