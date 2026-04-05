# Canvas LMS Skill

## Purpose
Fetch academic data from NUS Canvas LMS: assignments, events, courses, and grades.

## Triggers
- User asks about assignments, deadlines, or upcoming events
- Scheduled sync (HEARTBEAT)
- `/sync` command

## Actions
1. **Get Todo Items**: Fetch upcoming assignments with due dates
2. **Get Upcoming Events**: Fetch calendar events (lectures, exams, tutorials)
3. **Get Courses**: List enrolled courses

## API
- Base URL: `https://canvas.nus.edu.sg`
- Auth: Bearer token
- Mock fallback: `mock_data/canvas_todo.json`, `mock_data/canvas_events.json`

## Output
Standard task format: `{title, course, due_date, type, urgency, source: "canvas"}`
