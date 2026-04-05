# Deadline Extraction Skill

## Purpose
Extract structured tasks and deadlines from unstructured text using Agnes-1.5-Pro.

## Triggers
- New email received
- User forwards a message
- User pastes text into chat
- Canvas data synced

## Process
1. Receive raw text (email body, assignment description, user message)
2. Send to Agnes-1.5-Pro with extraction prompt
3. Parse JSON response: `[{title, course, due_date, type, urgency, source}]`
4. Deduplicate against existing tasks in MEMORY.md
5. Store new tasks with timestamp

## Urgency Classification
- **urgent**: due within 48 hours or marked important
- **soon**: due within 1 week
- **later**: due beyond 1 week
- **info**: no deadline, informational only

## Fallback
If Agnes API is unavailable, uses rule-based extraction (regex for dates, keywords for urgency).
