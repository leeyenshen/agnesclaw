# Job Matching + Resume Tailoring Skill

## Purpose
Extract roles from multi-listing job alert emails, rank suitability against a candidate profile, and generate truthful tailored resume drafts.

## Triggers
- User sends `/jobmatch` with resume + job email + preferences
- User sends `/jobmatch` without payload (scan unread inbox)
- User pastes a structured job-alert analysis request
- Scheduled/manual sync when unread job-related emails exist
- Batch CLI run with `python main.py --jobmatch ...`

## Core Workflow (2 Stages)
1. **Stage 1 - Extraction + Ranking**
   - Parse all job listings from the email
   - Normalize fields: role, company, mode, type, eligibility hints
   - Score suitability against resume/profile and goals
   - Return structured ranking with fit reasons, gaps, confidence, recommendation

2. **Stage 2 - Tailored Resume Generation**
   - For top 3 to 5 roles, generate truthful role-specific resume tailoring
   - Prioritize relevant skills/projects/coursework
   - Rewrite emphasis/order only, no fabricated content
   - Surface missing information explicitly

## Safety Rules
- Never hallucinate qualifications, projects, tools, or achievements.
- If resume is missing, do not generate a full tailored resume draft.
- If role details are vague, mark confidence lower and explain uncertainty.
- Prefer technically aligned roles unless profile indicates otherwise.

## Output Contract
Use sectioned output:
- A. Extracted Job Postings
- B. Suitability Ranking
- C. Best Matches Summary
- D. Tailored Resume Strategy for Each Top Pick
- E. Tailored Resume Draft
