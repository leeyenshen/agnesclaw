# Finance Tracker Skill

## Purpose
Track student spending by parsing transaction emails and receipts.

## Triggers
- Receipt/transaction email detected
- User forwards a receipt
- `/spend` command

## Process
1. Detect transaction patterns: "Total: $X.XX", receipt formats (GrabFood, PayLah, etc.)
2. Extract: merchant, amount, date, category
3. Categorize: food, transport, academic, entertainment, other
4. Store in MEMORY.md under `## Transactions`
5. Maintain running weekly/monthly totals

## Budget Alerts
- Default weekly budget: $70
- Alert at 80% threshold
- Summary includes category breakdown

## Supported Formats
- GrabFood / GrabPay receipts
- PayLah confirmations
- Bank transaction emails
- Manual text input ("spent $5 on coffee")
