# ClawCampus Tools

## Canvas LMS
- **Source**: `src/canvas_client.py`
- **Endpoints**: `/api/v1/users/self/todo`, `/api/v1/users/self/upcoming_events`, `/api/v1/courses`
- **Auth**: Bearer token via `CANVAS_TOKEN`
- **Mock fallback**: `mock_data/canvas_todo.json`, `mock_data/canvas_events.json`

## Gmail Email (via Google Gmail API)
- **Source**: `src/gmail_client.py`
- **Endpoints**: Inbox messages
- **Auth**: OAuth 2.0 via `credentials.json` and `token.json`
- **Mock fallback**: `mock_data/emails.json`

## Agnes-1.5-Pro (via ZenMux)
- **Source**: `src/agnes_client.py`
- **Endpoint**: `https://zenmux.ai/api/v1` (OpenAI-compatible)
- **Models**: `agnes/agnes-1.5-pro` (heavy), `agnes/agnes-1.5-lite` (light)
- **Auth**: `AGNES_API_KEY`

## Telegram Bot
- **Source**: `src/telegram_bot.py`
- **Library**: python-telegram-bot
- **Auth**: `TELEGRAM_BOT_TOKEN`

## Memory
- **Source**: `src/memory_manager.py`
- **Storage**: `MEMORY.md` (structured markdown with JSON bullet points)
