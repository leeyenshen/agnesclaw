# Assignment Coach Skill

## Purpose
Download or ingest assignment briefs and generate a practical study plan:
- which lecture slides/topics to prioritize
- what other sources to read
- what deliverables/unknowns to verify

## Triggers
- User asks: "what should I read for this assignment?"
- `/brief` command
- User pastes assignment brief text

## Actions
1. Resolve assignment brief from Canvas by title/id (or use pasted text).
2. Run Agnes analysis to extract required topics and recommended readings.
3. Return a structured guide with:
   - slide topics
   - external sources
   - deliverables checklist
   - uncertainty/missing info

## Inputs
- Canvas assignment metadata (`title`, `course_name`, `due_at`, `html_url`)
- Assignment brief text (from Canvas description or user-pasted text)

## Output
Study guide with sections:
- Summary
- What to Review
- Lecture Slides to Read
- Other Relevant Sources
- Deliverables Checklist
- Suggested Study Plan
- Missing Info / Uncertainty
