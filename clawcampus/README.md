# ClawCampus — Your 24/7 Student Life Agent

> **AgnesClaw Hackathon 2026** | Track 1: Academic Agent + Track 2: Personal Productivity Agent  
> Built on **OpenClaw** framework, powered by **Agnes-1.5-Pro** via ZenMux

## The Problem

**47% of university students** cite time management as their top challenge. Student admin is scattered across Canvas LMS, Outlook email, calendar apps, and group chats. Deadlines slip through. Important emails go unread. Students spend more time *managing* their work than *doing* it.

### Before ClawCampus
- Check Canvas for assignments
- Check Outlook for prof emails
- Check calendar for events
- Mentally prioritize everything
- Miss the deadline anyway

### After ClawCampus
- Wake up → receive a prioritized daily digest on Telegram
- Forward any email → tasks extracted automatically
- Get alerted when deadlines are urgent
- Email drafts written for you
- Food deals and spending tracked as a bonus

## How It Works

```
Canvas LMS ──┐
              ├──→ Task Extractor (Agnes-1.5-Pro) ──→ MEMORY.md ──→ Daily Digest
Outlook    ──┤                                                       ↓
              ├──→ Email Drafter (Agnes-1.5-Pro)                  Telegram Bot
User Input ──┘         ↓                                            ↑
                  Draft for approval ─────────────────────────────────┘
```

### Agnes-1.5-Pro Usage (Multi-Step, Not One-Shot)

1. **NER Extraction**: Identifies deadlines, dates, course codes, and action items from unstructured email/assignment text
2. **Urgency Classification**: Categorizes each task as urgent/soon/later/info based on temporal reasoning
3. **Daily Planning**: Generates personalized, prioritized digest considering user's schedule and preferences
4. **Email Drafting**: Composes contextual replies matching the appropriate tone (prof vs. peer vs. admin)

This is **chain-of-thought reasoning across multiple tasks**, not a single chat response.

## Features

| Feature | Status | Description |
|---------|--------|-------------|
| Task Extraction | ✅ MVP | Agnes-powered NER from emails + Canvas |
| Daily Digest | ✅ MVP | Prioritized summary via Telegram |
| Persistent Memory | ✅ MVP | MEMORY.md with structured task storage |
| Email Drafting | ✅ MVP | Context-aware reply generation |
| Job Matching + Resume Tailoring | ✅ MVP | Extract job listings, rank fit, and tailor truthful resume drafts |
| Assignment Brief Coach | ✅ MVP | Analyze assignment brief and recommend slides + relevant sources |
| Food Deal Scanner | ✅ MVP | Campus deals near your classes |
| Finance Tracker | ✅ MVP | Receipt parsing + budget alerts |
| Telegram Bot | ✅ MVP | Full command interface |

## Quick Start

### 1. Install Dependencies
```bash
cd clawcampus
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your API keys (or leave USE_MOCK=true for demo)
```

### 3. Run Demo (Mock Data)
```bash
cd src
python main.py --demo
```

### 4. Run Telegram Bot
```bash
# Set TELEGRAM_BOT_TOKEN in .env first
cd src
python main.py
```

### 5. Available Commands
| Command | Description |
|---------|-------------|
| `/start` | Welcome message + help |
| `/digest` | Get your daily summary |
| `/tasks` | See all pending tasks |
| `/done <task>` | Mark a task as done |
| `/sync` | Force sync from Canvas + Outlook |
| `/draft` | Draft reply to latest email |
| `/jobmatch` | Scan unread job-related emails (or paste one manually) and generate tailored resume drafts |
| `/brief` | Analyze assignment brief and return reading plan |
| `/deals` | Today's food deals |
| `/spend` | Weekly spending summary |

**Forward any message** to the bot and it will extract tasks automatically!
`/sync` also auto-scans unread job-related emails and runs job matching.

### 6. Jobmatch CLI (Email File Optional)
```bash
# Option A: scan unread inbox emails and run job matching automatically
cd src
python main.py --jobmatch

# Option B: run on a specific job alert email file
python main.py --jobmatch --email-file ../job_email.txt --resume-file ../resume.txt --prefs-file ../prefs.txt

# Option C: analyze a Canvas assignment brief by keyword
python main.py --brief --assignment "Lab 5"

# Option D: analyze a local assignment brief text file
python main.py --brief --brief-file ../assignment_brief.txt --title "Custom Assignment"
```

## Architecture

```
clawcampus/
├── openclaw.json          # OpenClaw agent config
├── SOUL.md                # Agent personality + rules
├── AGENTS.md              # Detailed operating instructions
├── HEARTBEAT.md           # Cron-triggered morning digest
├── MEMORY.md              # Persistent memory (tasks, prefs, transactions)
├── USER.md                # User profile
├── skills/                # OpenClaw skill definitions
│   ├── canvas-lms/
│   ├── outlook-email/
│   ├── deadline-extract/
│   ├── job-matching/
│   ├── food-deals/
│   ├── finance-tracker/
│   └── assignment-coach/
├── src/
│   ├── main.py            # Entry point
│   ├── agnes_client.py    # Agnes-1.5-Pro via ZenMux
│   ├── canvas_client.py   # Canvas LMS with mock fallback
│   ├── outlook_client.py  # Outlook via Maton with mock fallback
│   ├── task_extractor.py  # Agnes-powered extraction pipeline
│   ├── memory_manager.py  # MEMORY.md structured read/write
│   ├── digest_builder.py  # Daily digest generator
│   ├── email_drafter.py   # Auto email reply drafter
│   ├── food_scanner.py    # Food deal scanner
│   ├── finance_tracker.py # Receipt parser + budget tracker
│   ├── job_matcher.py     # Job alert ranking + resume tailoring
│   ├── assignment_coach.py # Assignment brief analysis + study guidance
│   └── telegram_bot.py    # Telegram bot interface
└── mock_data/             # Realistic demo data
```

## Agent Autonomy

ClawCampus is **not a chatbot** — it's an autonomous agent:

- **Cron-driven**: Morning digest runs automatically at 7:30 AM SGT via HEARTBEAT.md
- **Event-triggered**: New urgent emails trigger immediate Telegram alerts
- **Persistent memory**: Remembers your courses, preferences, and past tasks across sessions
- **Proactive**: Surfaces food deals near your next class without being asked

## 30-Day Iteration Plan

| Week | Focus |
|------|-------|
| 1 | User feedback + fix extraction edge cases |
| 2 | Richer Canvas sync (grades, announcements) + more email templates |
| 3 | WhatsApp integration + group project coordination |
| 4 | Pilot with 5-10 students, measure missed-deadline reduction |

## Tech Stack

- **Model**: Agnes-1.5-Pro via ZenMux (OpenAI-compatible API)
- **Framework**: OpenClaw agent framework
- **Language**: Python 3.11+
- **Interface**: Telegram Bot API
- **Data Sources**: Canvas LMS REST API, Outlook via Maton Gateway
- **Storage**: MEMORY.md (structured markdown — no database needed)

## Evaluation Criteria Alignment

| Criteria (Weight) | How ClawCampus Delivers |
|---|---|
| Problem Authenticity (25%) | 47% of students cite time management as #1 challenge. This solves a real, daily, high-frequency pain point. |
| Model Integration (20%) | Agnes-1.5-Pro performs NER extraction, urgency classification, summarization, and email drafting — multi-step chain-of-thought, not one-shot chat. |
| Agent Autonomy (20%) | Cron-driven digest, event-triggered alerts, autonomous email drafting — not a chatbot. |
| Sustainability (20%) | Every student needs this daily. Scales to groups, departments, school-wide. Ongoing habit. |
| Presentation (15%) | Clear before/after story. Live Telegram demo. Working mock fallback. |

---

*Built with Agnes Claw at AgnesClaw Hackathon 2026, NUS*
