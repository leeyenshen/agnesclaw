# Food Deal Scanner Skill

## Purpose
Surface food deals and promotions near NUS campus, timed around the user's class schedule.

## Triggers
- Daily digest (HEARTBEAT)
- `/deals` command
- User mentions lunch, food, or eating

## Process
1. Load deals from data source (mock_data/food_deals.json)
2. Filter for today's valid deals
3. Cross-reference with user's class schedule (location-aware)
4. Format and present deals with location, timing, and conditions

## Data Format
```json
{
  "merchant": "Koufu (UTown)",
  "deal": "1-for-1 Chicken Cutlet",
  "valid_date": "2026-04-05",
  "meal_period": "lunch",
  "location": "University Town",
  "near_buildings": ["SRC", "ERC"]
}
```

## Future
- Parse forwarded Telegram messages for deals
- Crowdsource deals from student community
