"""
Assignment brief analysis helper.
Uses Agnes to suggest lecture slides and relevant study sources from a brief.
"""
from __future__ import annotations

from time_utils import parse_iso_datetime, now_local
from agnes_client import call_agnes_pro, extract_json


ASSIGNMENT_COACH_PROMPT = """You are an academic assignment planning copilot.

Given an assignment brief, extract what the student should study.

Return ONLY JSON with this schema:
{
  "assignment_summary": "short summary",
  "required_topics": ["topic1", "topic2"],
  "recommended_slides": [
    {"title": "slide deck/topic name", "why": "why needed", "priority": "high|medium|low"}
  ],
  "recommended_sources": [
    {"type": "textbook|paper|documentation|tutorial|reference", "title": "name", "query": "search query or URL", "why": "reason"}
  ],
  "deliverables": ["what must be submitted"],
  "gaps_or_unknowns": ["missing details student should verify"],
  "study_plan": ["ordered checklist actions"]
}

Rules:
- If lecture slide titles are unknown, propose likely slide topics based on the brief and label uncertainty in 'gaps_or_unknowns'.
- Never invent course-specific facts that are not implied by the brief.
- Prioritize practical prep for completing the assignment.
"""


def _contains(text: str, *keywords: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in keywords)


def _fallback_analysis(
    brief_text: str,
    *,
    assignment_title: str = "",
    course_name: str = "",
    due_at: str | None = None,
) -> dict:
    text = f"{assignment_title}\n{course_name}\n{brief_text}".lower()

    required_topics: list[str] = []
    slides: list[dict] = []
    sources: list[dict] = []

    if _contains(text, "graph", "bfs", "dfs", "shortest path", "dijkstra"):
        required_topics.extend(["Graph representations", "BFS/DFS traversal", "Complexity analysis"])
        slides.extend([
            {"title": "Graphs Fundamentals", "why": "Core concepts and terminology used in graph assignments.", "priority": "high"},
            {"title": "BFS and DFS", "why": "Directly supports traversal-based questions.", "priority": "high"},
            {"title": "Shortest Paths and Weighted Graphs", "why": "Useful if the assignment includes path optimization.", "priority": "medium"},
        ])
        sources.extend([
            {"type": "textbook", "title": "Course textbook chapter on graphs", "query": "graph traversal BFS DFS chapter", "why": "Structured explanation with proofs and examples."},
            {"type": "tutorial", "title": "BFS/DFS worked examples", "query": "BFS DFS worked example", "why": "Helps validate implementation details quickly."},
        ])

    if _contains(text, "linear algebra", "eigen", "matrix", "vector", "svd"):
        required_topics.extend(["Matrix operations", "Eigenvalues and eigenvectors", "Linear transformations"])
        slides.extend([
            {"title": "Matrices and Linear Transformations", "why": "Foundational tools for linear algebra applications.", "priority": "high"},
            {"title": "Eigenvalues and Eigenvectors", "why": "Frequently required for analysis-heavy project sections.", "priority": "high"},
        ])
        sources.extend([
            {"type": "textbook", "title": "Linear Algebra chapters on eigen decomposition", "query": "eigenvalues eigenvectors textbook chapter", "why": "Provides rigorous methods and notation."},
            {"type": "tutorial", "title": "Applied linear algebra examples", "query": "linear algebra applied project examples", "why": "Bridges theory to project-style use cases."},
        ])

    if _contains(text, "er diagram", "entity-relationship", "database", "normalization"):
        required_topics.extend(["Entity-Relationship modeling", "Relational schema design", "Normalization basics"])
        slides.extend([
            {"title": "ER Modeling", "why": "Direct coverage of entities, relationships, and cardinality.", "priority": "high"},
            {"title": "Schema Mapping and Normalization", "why": "Needed for translating ER diagrams into table schemas.", "priority": "high"},
        ])
        sources.extend([
            {"type": "reference", "title": "Database design cheatsheet", "query": "ER diagram normalization cheatsheet", "why": "Fast reference while drafting diagrams."},
        ])

    if _contains(text, "ethic", "ai", "fairness", "bias", "privacy"):
        required_topics.extend(["AI fairness and bias", "Privacy and data governance", "Ethical frameworks"])
        slides.extend([
            {"title": "Ethics in AI Systems", "why": "Likely foundational lecture content for argument framing.", "priority": "high"},
            {"title": "Fairness, Accountability, Transparency", "why": "Provides criteria to evaluate case studies.", "priority": "medium"},
        ])
        sources.extend([
            {"type": "paper", "title": "Foundational fairness or ethics reading from course list", "query": "AI ethics fairness foundational paper", "why": "Strengthens evidence in essay arguments."},
            {"type": "documentation", "title": "Policy/guideline references", "query": "AI governance guidelines higher education", "why": "Useful for practical implications section."},
        ])

    if not slides:
        required_topics.append("Core concepts explicitly named in the assignment prompt")
        slides.append({
            "title": "Lecture slides matching assignment keywords",
            "why": "No exact topic match from fallback rules; start from assignment nouns/verbs.",
            "priority": "high",
        })
        sources.append({
            "type": "tutorial",
            "title": "Concept tutorial based on assignment keywords",
            "query": "assignment topic tutorial",
            "why": "Build baseline understanding before implementation.",
        })

    # Preserve order while removing duplicates.
    dedup_topics: list[str] = []
    seen = set()
    for topic in required_topics:
        key = topic.strip().lower()
        if key and key not in seen:
            seen.add(key)
            dedup_topics.append(topic)

    due_note = ""
    due = parse_iso_datetime(due_at)
    if due:
        local_due = due.astimezone(now_local().tzinfo)
        due_note = local_due.strftime("%a %d %b %I:%M %p")

    return {
        "assignment_summary": "Fallback analysis generated from assignment metadata and brief keywords.",
        "required_topics": dedup_topics[:8],
        "recommended_slides": slides[:8],
        "recommended_sources": sources[:8],
        "deliverables": [
            "Identify required output format from the brief (report/code/slides).",
            "Prepare final submission checklist (naming, files, rubric alignment).",
        ],
        "gaps_or_unknowns": [
            "Exact lecture slide deck names were not provided by source metadata.",
            "Confirm grading rubric and submission constraints on Canvas.",
        ] + ([f"Due date interpreted as {due_note} (local time)."] if due_note else []),
        "study_plan": [
            "Read the brief once end-to-end and highlight explicit requirements.",
            "Review the high-priority slide topics first.",
            "Use recommended sources to fill concept gaps.",
            "Draft solution outline mapped to rubric/deliverables.",
            "Implement/write and run a final checklist before submission.",
        ],
    }


def _normalize_result(data: dict) -> dict:
    def _list_str(key: str) -> list[str]:
        value = data.get(key, [])
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    def _list_dict(key: str) -> list[dict]:
        value = data.get(key, [])
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(item)
        return out

    return {
        "assignment_summary": str(data.get("assignment_summary", "")).strip(),
        "required_topics": _list_str("required_topics"),
        "recommended_slides": _list_dict("recommended_slides"),
        "recommended_sources": _list_dict("recommended_sources"),
        "deliverables": _list_str("deliverables"),
        "gaps_or_unknowns": _list_str("gaps_or_unknowns"),
        "study_plan": _list_str("study_plan"),
    }


def analyze_assignment_brief(
    brief_text: str,
    *,
    assignment_title: str = "",
    course_name: str = "",
    due_at: str | None = None,
) -> dict:
    """Return structured study guidance from an assignment brief."""
    if not isinstance(brief_text, str) or not brief_text.strip():
        return _fallback_analysis(
            "",
            assignment_title=assignment_title,
            course_name=course_name,
            due_at=due_at,
        )

    user_text = (
        f"Assignment title: {assignment_title or 'Unknown'}\n"
        f"Course: {course_name or 'Unknown'}\n"
        f"Due: {due_at or 'Unknown'}\n\n"
        "Assignment brief:\n"
        f"{brief_text.strip()}"
    )

    try:
        response = call_agnes_pro(
            [
                {"role": "system", "content": ASSIGNMENT_COACH_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.2,
        )
        parsed = extract_json(response)
        if isinstance(parsed, dict):
            normalized = _normalize_result(parsed)
            if normalized.get("required_topics") or normalized.get("recommended_slides"):
                return normalized
    except Exception:
        pass

    return _fallback_analysis(
        brief_text,
        assignment_title=assignment_title,
        course_name=course_name,
        due_at=due_at,
    )


def format_assignment_study_guide(
    analysis: dict,
    *,
    assignment_title: str = "",
    course_name: str = "",
    due_at: str | None = None,
    source_url: str | None = None,
    attachments: list[dict] | None = None,
) -> str:
    """Convert structured analysis into chat-friendly text."""
    lines = []
    title = assignment_title or "Assignment"
    lines.append(f"Assignment: {title}")
    if course_name:
        lines.append(f"Course: {course_name}")
    if due_at:
        due = parse_iso_datetime(due_at)
        if due:
            due_local = due.astimezone(now_local().tzinfo)
            lines.append(f"Due: {due_local.strftime('%a %d %b %Y %I:%M %p')}")
        else:
            lines.append(f"Due: {due_at}")
    if source_url:
        lines.append(f"Canvas link: {source_url}")
    attachment_list = attachments if isinstance(attachments, list) else []
    if attachment_list:
        lines.append("")
        lines.append("Canvas Attachments")
        for att in attachment_list[:5]:
            filename = str(att.get("filename", "attachment"))
            status = str(att.get("status", "unknown"))
            url = str(att.get("url", "")).strip()
            local_path = str(att.get("saved_path", "")).strip()
            lines.append(f"- {filename} ({status})")
            if url:
                lines.append(f"  Link: {url}")
            if local_path:
                lines.append(f"  Saved: {local_path}")
    lines.append("")

    summary = str(analysis.get("assignment_summary", "")).strip()
    if summary:
        lines.append("Summary")
        lines.append(summary)
        lines.append("")

    topics = analysis.get("required_topics") or []
    if topics:
        lines.append("What to Review")
        for topic in topics:
            lines.append(f"- {topic}")
        lines.append("")

    slides = analysis.get("recommended_slides") or []
    if slides:
        lines.append("Lecture Slides to Read")
        for slide in slides:
            title = slide.get("title", "Slide topic")
            why = slide.get("why", "")
            priority = str(slide.get("priority", "")).lower()
            priority_tag = f"[{priority}]" if priority else ""
            lines.append(f"- {title} {priority_tag}".strip())
            if why:
                lines.append(f"  Why: {why}")
        lines.append("")

    sources = analysis.get("recommended_sources") or []
    if sources:
        lines.append("Other Relevant Sources")
        for src in sources:
            stype = src.get("type", "source")
            stitle = src.get("title", "Untitled")
            query = src.get("query", "")
            why = src.get("why", "")
            lines.append(f"- {stitle} ({stype})")
            if query:
                lines.append(f"  Search/Link: {query}")
            if why:
                lines.append(f"  Why: {why}")
        lines.append("")

    deliverables = analysis.get("deliverables") or []
    if deliverables:
        lines.append("Deliverables Checklist")
        for item in deliverables:
            lines.append(f"- {item}")
        lines.append("")

    plan = analysis.get("study_plan") or []
    if plan:
        lines.append("Suggested Study Plan")
        for idx, step in enumerate(plan, start=1):
            lines.append(f"{idx}. {step}")
        lines.append("")

    gaps = analysis.get("gaps_or_unknowns") or []
    if gaps:
        lines.append("Missing Info / Uncertainty")
        for gap in gaps:
            lines.append(f"- {gap}")

    return "\n".join(lines).strip()


if __name__ == "__main__":
    sample = analyze_assignment_brief(
        "Build a graph search assignment that compares BFS and DFS runtime and submit code + report.",
        assignment_title="Lab 5: Graphs & BFS",
        course_name="CS2040S",
        due_at="2026-04-10T15:59:00Z",
    )
    print(format_assignment_study_guide(sample, assignment_title="Lab 5: Graphs & BFS"))
