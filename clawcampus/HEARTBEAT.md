# Morning Digest — Runs daily at 07:30 SGT

1. Fetch new Canvas assignments and events (last 24h)
2. Fetch unread Gmail emails via Gmail API (or mock_data/emails.json if USE_MOCK=true)
3. Run task extraction on any new items
4. Update MEMORY.md with extracted tasks
5. Check for tasks due today or tomorrow → mark urgent
6. Check for food deals valid today near user's classes
7. Calculate weekly spending so far
8. Compose and send daily digest via Telegram
9. If any email needs a reply, draft it and notify user
