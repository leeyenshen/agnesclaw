"""
Job matching and resume tailoring pipeline.

This module implements a practical 2-stage flow:
1) Extraction + suitability ranking
2) Role-specific resume tailoring
"""
from __future__ import annotations

import json
import re
from typing import Any
from pathlib import Path

from agnes_client import call_agnes_pro, extract_json


OPENCLAW_MAIN_PROMPT = """You are an AI job-matching and resume-tailoring agent.

Your task:
1. Read the incoming job alert email.
2. Extract every job posting mentioned in the email.
3. For each job, identify role title, company, mode, type, and eligibility hints if present.
4. Compare each role against the user's profile and master resume.
5. Rank all roles by suitability.
6. Explain fit, gaps, and score out of 10 for each role.
7. Pick top 3 to 5 best roles.
8. Generate tailored resume drafts using only truthful profile data.
9. If details are missing, explicitly say what is missing.
10. Output in clean structured format.

Rules:
- Do not hallucinate experience, skills, tools, projects, or achievements.
- You may reframe and prioritize existing experience, but do not fabricate.
- Penalize clearly misaligned roles.
- Use cautious inference when only title/company are available.
"""


OPENCLAW_USER_TEMPLATE = """Here is my master resume/profile:
[PASTE YOUR MASTER RESUME HERE]

Here is the email to analyze:
[PASTE THE JOB ALERT EMAIL HERE]

My goals and preferences:
- Preferred roles:
- Preferred industries:
- Preferred internship period:
- Roles I do NOT want:
- Strongest skills:
- Weakest areas:
- Anything else relevant:
"""


STAGE1_PROMPT = """You are an AI internship copilot.

Inputs:
1) Job alert email with multiple listings
2) Candidate master resume/profile
3) Candidate goals/preferences

Tasks:
- Extract all listed roles from the email.
- Estimate role suitability against profile/resume and preferences.
- Penalize clear mismatch roles.
- If role details are missing, mark confidence lower and explain uncertainty.

Return STRICT JSON only with this schema:
{
  "roles": [
    {
      "role_title": "string",
      "company": "string",
      "mode": "Onsite|Hybrid|Remote|Unknown",
      "type": "Internship|Full-time|Part-time|Contract|Unknown",
      "eligibility_notes": "string",
      "notes": "string"
    }
  ],
  "ranking": [
    {
      "role_title": "string",
      "company": "string",
      "suitability_score": 0,
      "confidence": "Low|Medium|High",
      "fit_reasons": ["string"],
      "gap_reasons": ["string"],
      "recommendation": "Apply|Maybe|Skip"
    }
  ],
  "best_matches_summary": {
    "top_picks": [
      {"role_title": "string", "company": "string"}
    ],
    "why_these_stand_out": "string",
    "strongest_for_background": "string"
  },
  "missing_information": ["string"]
}
"""


STAGE2_PROMPT = """You are an AI resume tailoring assistant.

You will be given:
- candidate master resume/profile
- a shortlisted role
- candidate goals/preferences

Rules:
- Never invent any experience, project, tool, metric, or achievement.
- Reframe and reorder existing facts only.
- If details are insufficient, state what is missing.
- Optimize for relevance, clarity, and ATS-friendliness.

Return STRICT JSON only with this schema:
{
  "resume_headline": "string",
  "summary_to_emphasize": "string",
  "skills_to_prioritize": ["string"],
  "projects_coursework_to_highlight": ["string"],
  "experiences_to_reorder_or_rewrite": ["string"],
  "keywords_to_include": ["string"],
  "tailored_resume_draft": "string",
  "missing_information": ["string"]
}
"""


_HEADING_ALIASES = {
    "resume": [
        "here is my master resume/profile:",
        "master resume/profile:",
        "master resume:",
        "resume:",
    ],
    "email": [
        "here is the email to analyze:",
        "email to analyze:",
        "job alert email:",
        "email:",
    ],
    "goals": [
        "my goals and preferences:",
        "goals and preferences:",
        "preferences:",
    ],
}

DEFAULT_PROFILE_PATH = Path(__file__).parent.parent / "USER.md"

JOB_POSITIVE_KEYWORDS = (
    "internship",
    "intern",
    "job opening",
    "open role",
    "position",
    "vacancy",
    "hiring",
    "we are hiring",
    "career",
    "careers",
    "graduate program",
    "analyst program",
    "apply now",
    "application deadline",
    "recruitment",
)

JOB_NEGATIVE_KEYWORDS = (
    "receipt",
    "invoice",
    "order",
    "payment",
    "assignment",
    "tutorial",
    "lecture",
    "exam",
    "canvas",
    "lab",
    "meeting minutes",
)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean_text(v) for v in value if _clean_text(v)]
    if isinstance(value, str) and value.strip():
        return [_clean_text(value)]
    return []


def _to_score(value: Any, default: float = 5.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(10.0, score))


def _normalize_confidence(value: str) -> str:
    text = _clean_text(value).lower()
    if text in {"high", "h"}:
        return "High"
    if text in {"medium", "med", "m"}:
        return "Medium"
    return "Low"


def _normalize_recommendation(value: str, score: float) -> str:
    text = _clean_text(value).lower()
    if text in {"apply", "maybe", "skip"}:
        return text.title()
    if score >= 7.0:
        return "Apply"
    if score >= 5.0:
        return "Maybe"
    return "Skip"


def parse_jobmatch_sections(text: str) -> dict[str, str] | None:
    """Parse template sections from a user message."""
    if not text or not text.strip():
        return None

    lowered = text.lower()

    def find_first(aliases: list[str]) -> tuple[int, str] | None:
        hits = []
        for alias in aliases:
            idx = lowered.find(alias)
            if idx != -1:
                hits.append((idx, alias))
        if not hits:
            return None
        return min(hits, key=lambda item: item[0])

    positions: list[tuple[int, str, str]] = []
    for section_name, aliases in _HEADING_ALIASES.items():
        found = find_first(aliases)
        if found:
            positions.append((found[0], section_name, found[1]))

    if not positions:
        return None
    positions.sort(key=lambda item: item[0])

    extracted = {"master_resume": "", "email_text": "", "goals_preferences": ""}
    for i, (start_idx, section_name, heading_text) in enumerate(positions):
        content_start = start_idx + len(heading_text)
        content_end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        content = text[content_start:content_end].strip()
        if section_name == "resume":
            extracted["master_resume"] = content
        elif section_name == "email":
            extracted["email_text"] = content
        elif section_name == "goals":
            extracted["goals_preferences"] = content

    if not extracted["email_text"]:
        return None
    return extracted


def looks_like_jobmatch_request(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return (
        "job alert" in lowered
        or "tailored resume" in lowered
        or ("master resume" in lowered and "email" in lowered)
    )


def load_default_profile_text() -> str:
    """
    Load default profile/resume text from disk for inbox-driven job matching.

    Priority:
    1) path from env MASTER_RESUME_FILE (if readable)
    2) USER.md fallback
    """
    import os

    preferred_path = os.environ.get("MASTER_RESUME_FILE", "").strip()
    if preferred_path:
        project_root = DEFAULT_PROFILE_PATH.parent
        candidates = [Path(preferred_path)]
        preferred = Path(preferred_path)
        if not preferred.is_absolute():
            candidates.append(project_root / preferred)

        for candidate in candidates:
            try:
                return candidate.read_text(encoding="utf-8").strip()
            except Exception:
                continue

    try:
        return DEFAULT_PROFILE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def email_to_jobmatch_text(email: dict[str, Any]) -> str:
    """Convert an email object to text payload for extraction/ranking."""
    subject = _clean_text(email.get("subject"))
    sender = _clean_text(email.get("from") or email.get("from_email"))
    date = _clean_text(email.get("date") or email.get("receivedDateTime"))
    body = str(email.get("body", "") or "")
    return (
        f"Subject: {subject}\n"
        f"From: {sender}\n"
        f"Date: {date}\n\n"
        f"{body}"
    ).strip()


def is_job_related_text(text: str) -> bool:
    """Heuristic job-email detector used for inbox auto-processing."""
    lowered = (text or "").lower()
    if not lowered.strip():
        return False
    positive = sum(1 for kw in JOB_POSITIVE_KEYWORDS if kw in lowered)
    negative = sum(1 for kw in JOB_NEGATIVE_KEYWORDS if kw in lowered)
    # Need a meaningful positive signal and avoid obvious non-job emails.
    if positive == 0:
        return False
    if negative >= 2 and positive <= 1:
        return False
    return positive >= 1 and positive > negative


def is_job_related_email(email: dict[str, Any]) -> bool:
    """Detect if an email likely contains job/internship listings."""
    return is_job_related_text(email_to_jobmatch_text(email))


def filter_job_related_emails(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only emails that look job-related."""
    return [email for email in emails if is_job_related_email(email)]


def _role_key(role: dict[str, Any]) -> tuple[str, str]:
    return (_clean_text(role.get("role_title")).lower(), _clean_text(role.get("company")).lower())


def _normalize_role(role: dict[str, Any]) -> dict[str, str]:
    mode = _clean_text(role.get("mode")) or "Unknown"
    role_type = _clean_text(role.get("type")) or "Unknown"

    if mode.lower() not in {"onsite", "hybrid", "remote", "unknown"}:
        mode = "Unknown"
    else:
        mode = mode.title()

    known_types = {"internship", "full-time", "part-time", "contract", "unknown"}
    if role_type.lower() not in known_types:
        role_type = "Unknown"
    else:
        if role_type.lower() == "full-time":
            role_type = "Full-time"
        elif role_type.lower() == "part-time":
            role_type = "Part-time"
        else:
            role_type = role_type.title()

    return {
        "role_title": _clean_text(role.get("role_title")) or "Unknown Role",
        "company": _clean_text(role.get("company")) or "Unknown Company",
        "mode": mode,
        "type": role_type,
        "eligibility_notes": _clean_text(role.get("eligibility_notes")),
        "notes": _clean_text(role.get("notes")),
    }


def _normalize_ranking_item(item: dict[str, Any], fallback_role: dict[str, str] | None = None) -> dict[str, Any]:
    role_title = _clean_text(item.get("role_title"))
    company = _clean_text(item.get("company"))
    if fallback_role:
        role_title = role_title or fallback_role.get("role_title", "")
        company = company or fallback_role.get("company", "")

    score = _to_score(item.get("suitability_score"), default=5.0)
    confidence = _normalize_confidence(_clean_text(item.get("confidence")))
    fit_reasons = _coerce_list(item.get("fit_reasons"))
    gap_reasons = _coerce_list(item.get("gap_reasons"))
    recommendation = _normalize_recommendation(_clean_text(item.get("recommendation")), score)

    return {
        "role_title": role_title or "Unknown Role",
        "company": company or "Unknown Company",
        "suitability_score": round(score, 1),
        "confidence": confidence,
        "fit_reasons": fit_reasons,
        "gap_reasons": gap_reasons,
        "recommendation": recommendation,
    }


def _extract_roles_from_line(line: str) -> tuple[str, str] | None:
    patterns = [
        r"^(?P<role>.+?)\s+at\s+(?P<company>.+)$",
        r"^(?P<role>.+?)\s+-\s+(?P<company>.+)$",
        r"^(?P<company>.+?)\s+\|\s+(?P<role>.+)$",
        r"^(?P<role>.+?)\s+\((?P<company>.+)\)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, line, flags=re.IGNORECASE)
        if match:
            role = _clean_text(match.groupdict().get("role"))
            company = _clean_text(match.groupdict().get("company"))
            if role and company:
                return role, company
    return None


def _extract_roles_fallback(email_text: str) -> list[dict[str, str]]:
    role_keywords = (
        "intern",
        "engineer",
        "developer",
        "analyst",
        "scientist",
        "associate",
        "product",
        "software",
        "data",
    )

    roles: list[dict[str, str]] = []
    seen = set()
    for raw_line in email_text.splitlines():
        line = raw_line.strip(" -*\t|")
        if not line:
            continue
        lowered = line.lower()
        if not any(keyword in lowered for keyword in role_keywords):
            continue

        parsed = _extract_roles_from_line(line)
        if parsed:
            role_title, company = parsed
        else:
            role_title, company = line, "Unknown Company"

        role = {
            "role_title": role_title,
            "company": company,
            "mode": "Unknown",
            "type": "Internship" if "intern" in lowered else "Unknown",
            "eligibility_notes": "",
            "notes": "Fallback extraction from email text.",
        }
        key = _role_key(role)
        if key in seen:
            continue
        seen.add(key)
        roles.append(role)

    if roles:
        return roles

    # Last fallback: use first few non-empty lines as vague postings.
    for raw_line in email_text.splitlines():
        line = raw_line.strip()
        if len(line) < 6:
            continue
        role = {
            "role_title": line[:90],
            "company": "Unknown Company",
            "mode": "Unknown",
            "type": "Unknown",
            "eligibility_notes": "",
            "notes": "Very limited details; inferred from sparse email content.",
        }
        roles.append(role)
        if len(roles) >= 3:
            break
    return roles


def _extract_goal_preferences(goals_text: str) -> dict[str, str]:
    prefs = {
        "preferred_roles": "",
        "preferred_industries": "",
        "preferred_internship_period": "",
        "avoid_roles": "",
        "strongest_skills": "",
        "weakest_areas": "",
    }
    if not goals_text:
        return prefs

    mapping = {
        "preferred roles": "preferred_roles",
        "preferred industries": "preferred_industries",
        "preferred internship period": "preferred_internship_period",
        "roles i do not want": "avoid_roles",
        "strongest skills": "strongest_skills",
        "weakest areas": "weakest_areas",
    }
    for line in goals_text.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        key = left.strip().lower().lstrip("- ").strip()
        if key in mapping:
            prefs[mapping[key]] = right.strip()
    return prefs


def _fallback_rank_roles(
    roles: list[dict[str, str]],
    master_resume: str,
    goals_preferences: str,
) -> list[dict[str, Any]]:
    technical_keywords = {
        "python", "java", "c++", "sql", "machine learning", "data", "backend",
        "frontend", "api", "cloud", "aws", "docker", "react", "node", "analytics",
    }
    misaligned_keywords = {
        "sales", "operations", "hr", "recruit", "marketing", "customer service",
    }

    resume_lower = master_resume.lower()
    goals_lower = goals_preferences.lower()
    prefs = _extract_goal_preferences(goals_preferences)
    avoid_lower = prefs["avoid_roles"].lower()
    preferred_roles_lower = prefs["preferred_roles"].lower()

    ranking = []
    for role in roles:
        role_text = " ".join(
            [
                role.get("role_title", ""),
                role.get("company", ""),
                role.get("type", ""),
                role.get("mode", ""),
                role.get("notes", ""),
            ]
        ).lower()

        score = 5.0
        fit_reasons: list[str] = []
        gap_reasons: list[str] = []

        if master_resume.strip():
            overlap = [kw for kw in technical_keywords if kw in role_text and kw in resume_lower]
            if overlap:
                score += min(2.5, 0.7 * len(overlap))
                fit_reasons.append(
                    f"Role keywords overlap with your profile: {', '.join(overlap[:5])}."
                )
            else:
                gap_reasons.append("Limited explicit keyword overlap with your current resume.")
        else:
            score -= 1.0
            gap_reasons.append("No master resume provided, so fit is estimated from title only.")

        if preferred_roles_lower and any(token.strip() and token.strip() in role_text for token in preferred_roles_lower.split(",")):
            score += 1.0
            fit_reasons.append("Matches your stated preferred roles.")

        if "intern" in role_text and ("intern" in goals_lower or "internship" in goals_lower):
            score += 0.5
            fit_reasons.append("Role type appears aligned with your internship preference.")

        if avoid_lower and any(token.strip() and token.strip() in role_text for token in avoid_lower.split(",")):
            score -= 2.0
            gap_reasons.append("Role appears in your 'do not want' preferences.")

        if any(keyword in role_text for keyword in misaligned_keywords):
            score -= 1.5
            gap_reasons.append("Role appears less technical and may be misaligned with technical goals.")

        score = max(0.0, min(10.0, score))
        if not fit_reasons:
            fit_reasons.append("Potentially relevant based on role title, but details are limited.")
        if not gap_reasons:
            gap_reasons.append("Full job description not provided; hidden requirements may exist.")

        ranking.append(
            {
                "role_title": role["role_title"],
                "company": role["company"],
                "suitability_score": round(score, 1),
                "confidence": "Low",
                "fit_reasons": fit_reasons,
                "gap_reasons": gap_reasons,
                "recommendation": _normalize_recommendation("", score),
            }
        )

    ranking.sort(key=lambda item: item.get("suitability_score", 0), reverse=True)
    return ranking


def _extract_roles_and_ranking_from_model_response(parsed: Any) -> tuple[list[dict[str, str]], list[dict[str, Any]], dict[str, Any], list[str]]:
    if not isinstance(parsed, dict):
        return [], [], {}, ["Model response was not a JSON object."]

    roles_raw = parsed.get("roles", [])
    ranking_raw = parsed.get("ranking", [])
    summary_raw = parsed.get("best_matches_summary", {})
    missing_raw = parsed.get("missing_information", [])

    roles: list[dict[str, str]] = []
    if isinstance(roles_raw, list):
        for item in roles_raw:
            if isinstance(item, dict):
                roles.append(_normalize_role(item))

    ranking: list[dict[str, Any]] = []
    if isinstance(ranking_raw, list):
        for item in ranking_raw:
            if isinstance(item, dict):
                ranking.append(_normalize_ranking_item(item))

    summary = summary_raw if isinstance(summary_raw, dict) else {}
    missing = _coerce_list(missing_raw)
    return roles, ranking, summary, missing


def extract_and_rank_jobs(
    master_resume: str,
    email_text: str,
    goals_preferences: str = "",
) -> dict[str, Any]:
    """Stage 1: extract all roles and rank suitability."""
    master_resume = master_resume or ""
    email_text = email_text or ""
    goals_preferences = goals_preferences or ""

    if not email_text.strip():
        return {
            "roles": [],
            "ranking": [],
            "best_matches_summary": {},
            "missing_information": ["Job alert email content is missing."],
            "source": "validation",
        }

    user_payload = (
        "Candidate Resume/Profile:\n"
        f"{master_resume or '[NOT PROVIDED]'}\n\n"
        "Job Alert Email:\n"
        f"{email_text}\n\n"
        "Goals and Preferences:\n"
        f"{goals_preferences or '[NOT PROVIDED]'}"
    )

    try:
        response = call_agnes_pro(
            [
                {"role": "system", "content": STAGE1_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.2,
        )
        parsed = extract_json(response)
        roles, ranking, summary, missing = _extract_roles_and_ranking_from_model_response(parsed)
        if roles and ranking:
            ranking.sort(key=lambda item: item.get("suitability_score", 0), reverse=True)
            return {
                "roles": roles,
                "ranking": ranking,
                "best_matches_summary": summary,
                "missing_information": missing,
                "source": "model",
            }
    except Exception as exc:
        fallback_note = f"Stage 1 model call failed: {exc}"
    else:
        fallback_note = "Stage 1 model output was incomplete or not parseable JSON."

    roles = _extract_roles_fallback(email_text)
    ranking = _fallback_rank_roles(roles, master_resume, goals_preferences)
    return {
        "roles": roles,
        "ranking": ranking,
        "best_matches_summary": {},
        "missing_information": [fallback_note, "Used fallback extraction/ranking logic."],
        "source": "fallback",
    }


def _shortlist_roles(ranking: list[dict[str, Any]], max_picks: int = 5) -> list[dict[str, Any]]:
    if not ranking:
        return []
    max_picks = max(1, min(5, int(max_picks)))
    min_picks = min(3, len(ranking))
    picks = ranking[: max(max_picks, min_picks)]
    return picks[:max_picks]


def generate_tailored_resume(
    master_resume: str,
    role: dict[str, Any],
    goals_preferences: str = "",
) -> dict[str, Any]:
    """Stage 2: generate role-specific tailoring plan + truthful draft."""
    role_title = _clean_text(role.get("role_title")) or "Unknown Role"
    company = _clean_text(role.get("company")) or "Unknown Company"

    default_output = {
        "resume_headline": f"{role_title} candidate",
        "summary_to_emphasize": "Highlight only directly relevant, truthful experience from your master resume.",
        "skills_to_prioritize": [],
        "projects_coursework_to_highlight": [],
        "experiences_to_reorder_or_rewrite": [],
        "keywords_to_include": [role_title, company],
        "tailored_resume_draft": "Could not auto-generate a reliable tailored draft. Please provide more role details and retry.",
        "missing_information": [],
    }

    if not master_resume.strip():
        default_output["missing_information"] = [
            "Master resume/profile is required for truthful tailoring.",
            "Provide your resume content to generate role-specific drafts.",
        ]
        return default_output

    user_payload = (
        f"Shortlisted Role:\n{json.dumps(role, ensure_ascii=False, indent=2)}\n\n"
        f"Master Resume/Profile:\n{master_resume}\n\n"
        f"Goals and Preferences:\n{goals_preferences or '[NOT PROVIDED]'}"
    )

    try:
        response = call_agnes_pro(
            [
                {"role": "system", "content": STAGE2_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.2,
        )
        parsed = extract_json(response)
        if isinstance(parsed, dict):
            return {
                "resume_headline": _clean_text(parsed.get("resume_headline")) or default_output["resume_headline"],
                "summary_to_emphasize": _clean_text(parsed.get("summary_to_emphasize")) or default_output["summary_to_emphasize"],
                "skills_to_prioritize": _coerce_list(parsed.get("skills_to_prioritize")),
                "projects_coursework_to_highlight": _coerce_list(parsed.get("projects_coursework_to_highlight")),
                "experiences_to_reorder_or_rewrite": _coerce_list(parsed.get("experiences_to_reorder_or_rewrite")),
                "keywords_to_include": _coerce_list(parsed.get("keywords_to_include")),
                "tailored_resume_draft": str(parsed.get("tailored_resume_draft", "")).strip() or default_output["tailored_resume_draft"],
                "missing_information": _coerce_list(parsed.get("missing_information")),
            }
        default_output["tailored_resume_draft"] = response.strip() or default_output["tailored_resume_draft"]
        default_output["missing_information"] = [
            "Model did not return strict JSON for stage 2. Included raw draft output."
        ]
        return default_output
    except Exception as exc:
        default_output["missing_information"] = [f"Stage 2 model call failed: {exc}"]
        return default_output


def run_job_matching(
    master_resume: str,
    email_text: str,
    goals_preferences: str = "",
    top_k: int = 5,
) -> dict[str, Any]:
    """Run full 2-stage job matching + resume tailoring pipeline."""
    stage1 = extract_and_rank_jobs(master_resume, email_text, goals_preferences)
    roles = stage1.get("roles", [])
    ranking = stage1.get("ranking", [])
    summary = stage1.get("best_matches_summary", {})
    missing_info = _coerce_list(stage1.get("missing_information", []))
    ranking.sort(key=lambda item: item.get("suitability_score", 0), reverse=True)

    top_roles = _shortlist_roles(ranking, max_picks=top_k)

    tailored_outputs: list[dict[str, Any]] = []
    if master_resume.strip():
        for ranked_role in top_roles:
            tailored = generate_tailored_resume(master_resume, ranked_role, goals_preferences)
            tailored_outputs.append(
                {
                    "role_title": ranked_role.get("role_title", "Unknown Role"),
                    "company": ranked_role.get("company", "Unknown Company"),
                    "plan_and_draft": tailored,
                }
            )
    else:
        missing_info.append(
            "Master resume/profile not provided. Full tailored resume drafts were skipped."
        )

    return {
        "roles": roles,
        "ranking": ranking,
        "top_roles": top_roles,
        "best_matches_summary": summary,
        "tailored_outputs": tailored_outputs,
        "missing_information": missing_info,
        "resume_provided": bool(master_resume.strip()),
    }


def format_job_matching_report(result: dict[str, Any]) -> str:
    """Format final output into requested sections A-E."""
    roles = result.get("roles", [])
    ranking = result.get("ranking", [])
    top_roles = result.get("top_roles", [])
    tailored_outputs = result.get("tailored_outputs", [])
    summary = result.get("best_matches_summary", {})
    missing_info = _coerce_list(result.get("missing_information", []))
    resume_provided = bool(result.get("resume_provided"))

    lines = []

    lines.append("A. Extracted Job Postings")
    if roles:
        for posting in roles:
            lines.append(f"- Role: {posting.get('role_title', 'Unknown')}")
            lines.append(f"  Company: {posting.get('company', 'Unknown')}")
            lines.append(f"  Type: {posting.get('type', 'Unknown')}")
            lines.append(f"  Mode: {posting.get('mode', 'Unknown')}")
            notes = posting.get("eligibility_notes") or posting.get("notes") or "N/A"
            lines.append(f"  Notes: {notes}")
    else:
        lines.append("- No roles could be extracted from the email.")

    lines.append("")
    lines.append("B. Suitability Ranking")
    if ranking:
        for idx, item in enumerate(ranking, start=1):
            lines.append(f"- Rank: {idx}")
            lines.append(f"  Role: {item.get('role_title', 'Unknown')}")
            lines.append(f"  Company: {item.get('company', 'Unknown')}")
            lines.append(f"  Suitability Score: {item.get('suitability_score', 0)}/10")
            lines.append(f"  Confidence: {item.get('confidence', 'Low')}")
            fits = "; ".join(_coerce_list(item.get("fit_reasons"))) or "N/A"
            gaps = "; ".join(_coerce_list(item.get("gap_reasons"))) or "N/A"
            lines.append(f"  Why it fits: {fits}")
            lines.append(f"  Risks / gaps: {gaps}")
            lines.append(f"  Recommendation: {item.get('recommendation', 'Maybe')}")
    else:
        lines.append("- No ranking available.")

    lines.append("")
    lines.append("C. Best Matches Summary")
    if top_roles:
        picks = [f"{role.get('role_title')} @ {role.get('company')}" for role in top_roles]
        lines.append(f"- Top picks: {', '.join(picks)}")
    else:
        lines.append("- Top picks: None")
    lines.append(
        f"- Why these stand out: {summary.get('why_these_stand_out', 'Based on highest suitability scores and role alignment.')}"
    )
    lines.append(
        f"- Which ones are strongest for my background: {summary.get('strongest_for_background', 'See top picks and fit reasons above.')}"
    )

    lines.append("")
    lines.append("D. Tailored Resume Strategy for Each Top Pick")
    if resume_provided and tailored_outputs:
        for item in tailored_outputs:
            draft = item.get("plan_and_draft", {})
            lines.append(f"- Role: {item.get('role_title')} @ {item.get('company')}")
            lines.append(f"  Resume headline to use: {draft.get('resume_headline', 'N/A')}")
            lines.append(f"  Summary to emphasize: {draft.get('summary_to_emphasize', 'N/A')}")
            lines.append(f"  Skills to prioritize: {', '.join(_coerce_list(draft.get('skills_to_prioritize'))) or 'N/A'}")
            lines.append(
                "  Projects/coursework to highlight: "
                + (", ".join(_coerce_list(draft.get("projects_coursework_to_highlight"))) or "N/A")
            )
            lines.append(
                "  Experiences to reorder or rewrite: "
                + ("; ".join(_coerce_list(draft.get("experiences_to_reorder_or_rewrite"))) or "N/A")
            )
            lines.append(
                "  Keywords to include: "
                + (", ".join(_coerce_list(draft.get("keywords_to_include"))) or "N/A")
            )
    else:
        lines.append("- Resume not provided. Tailored strategy is limited.")
        lines.append("- Needed information: full resume, project details, quantified impact, preferred role target.")

    lines.append("")
    lines.append("E. Tailored Resume Draft")
    if resume_provided and tailored_outputs:
        for item in tailored_outputs:
            draft = item.get("plan_and_draft", {})
            lines.append(f"- Draft for {item.get('role_title')} @ {item.get('company')}:")
            lines.append(draft.get("tailored_resume_draft", "No draft generated."))
            missing = _coerce_list(draft.get("missing_information"))
            if missing:
                lines.append("  Missing info: " + "; ".join(missing))
            lines.append("")
    else:
        lines.append("- Full tailored resume draft skipped because master resume/profile was not provided.")
        lines.append("- Checklist per top role: key projects, metrics, tools, internship dates, domain interests.")

    if missing_info:
        lines.append("")
        lines.append("Missing Information / Notes")
        for note in missing_info:
            lines.append(f"- {note}")

    return "\n".join(lines).strip()


if __name__ == "__main__":
    print("Job matcher module loaded.")
