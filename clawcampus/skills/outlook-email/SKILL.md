# Outlook Email Skill

## Purpose
Read and draft emails via Maton Gateway connected to Microsoft Outlook.

## Triggers
- User asks about emails or wants to draft a reply
- Scheduled sync (HEARTBEAT)
- `/draft` command

## Actions
1. **Get Inbox**: Fetch recent emails (default: 10)
2. **Get Unread**: Filter for unread emails only
3. **Draft Reply**: Use Agnes to compose a contextual reply
4. **Send Email**: Send approved draft (requires user confirmation)

## API
- Gateway: `https://gateway.maton.ai`
- Auth: Bearer token via Maton API key
- Mock fallback: `mock_data/emails.json`

## Safety
- Emails are DRAFTED only — never sent without explicit user approval
- All drafts shown to user for review before any action
