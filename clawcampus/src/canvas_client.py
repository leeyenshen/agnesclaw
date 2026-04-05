"""
Canvas LMS REST client.
Mock data is used only when USE_MOCK=true.
"""
from __future__ import annotations

import os
import json
import io
import html
import re
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

CANVAS_URL = os.environ.get("CANVAS_URL", "https://canvas.nus.edu.sg")
CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "")
USE_MOCK = os.environ.get("USE_MOCK", "true").lower() == "true"

MOCK_DIR = Path(__file__).parent.parent / "mock_data"
BRIEF_DOWNLOAD_DIR = Path(__file__).parent.parent / "downloads" / "assignment_briefs"

HEADERS = {"Authorization": f"Bearer {CANVAS_TOKEN}"} if CANVAS_TOKEN else {}
MAX_ATTACHMENTS_PER_BRIEF = 5
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS_PER_ATTACHMENT = 12000
MAX_ZIP_ENTRIES_TO_SCAN = 20
MAX_ZIP_ENTRY_BYTES = 2 * 1024 * 1024
TEXT_ATTACHMENT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".json",
    ".csv",
    ".yaml",
    ".yml",
    ".py",
    ".java",
    ".c",
    ".cpp",
    ".js",
    ".ts",
    ".html",
    ".htm",
    ".xml",
}
DOCX_EXTENSION = ".docx"


def _load_mock(filename: str) -> list[dict]:
    path = MOCK_DIR / filename
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _api_get_json(endpoint: str) -> list[dict] | dict | None:
    """Try a real Canvas API call. Returns None on failure."""
    if USE_MOCK or not CANVAS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{CANVAS_URL}{endpoint}",
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _http_get(url: str) -> requests.Response | None:
    """Authenticated GET for full responses (needed for attachment download)."""
    if USE_MOCK or not CANVAS_TOKEN:
        return None
    try:
        response = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        response.raise_for_status()
        return response
    except Exception:
        return None


def _api_get(endpoint: str) -> list[dict] | None:
    """Compatibility wrapper for list endpoints."""
    data = _api_get_json(endpoint)
    return data if isinstance(data, list) else None


def get_todo_items() -> list[dict]:
    """Fetch upcoming assignments from Canvas (or mock only in mock mode)."""
    result = _api_get("/api/v1/users/self/todo")
    if result is not None:
        return result
    if USE_MOCK:
        return _load_mock("canvas_todo.json")
    return []


def get_upcoming_events() -> list[dict]:
    """Fetch upcoming calendar events from Canvas (or mock only in mock mode)."""
    result = _api_get("/api/v1/users/self/upcoming_events")
    if result is not None:
        return result
    if USE_MOCK:
        return _load_mock("canvas_events.json")
    return []


def get_courses() -> list[dict]:
    """Fetch enrolled courses. Mock derives course names from mock todo items."""
    result = _api_get("/api/v1/courses")
    if result is not None:
        return result
    if not USE_MOCK:
        return []
    # Derive courses from mock todo data
    todos = _load_mock("canvas_todo.json")
    seen = set()
    courses = []
    for item in todos:
        name = item.get("context_name", "")
        if name and name not in seen:
            seen.add(name)
            courses.append({
                "id": item["assignment"]["course_id"],
                "name": name,
            })
    return courses


def list_assignment_titles(limit: int = 10) -> list[str]:
    """Return assignment names from current todo list."""
    titles = []
    for item in get_todo_items()[: max(1, limit)]:
        assignment = item.get("assignment", {})
        title = assignment.get("name")
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return titles


def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(no_tags.split())


def _load_mock_briefs() -> list[dict]:
    path = MOCK_DIR / "canvas_assignment_briefs.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "")
    cleaned = cleaned.strip("._")
    return cleaned or "attachment.bin"


def _filename_from_response(response: requests.Response, fallback_url: str) -> str:
    content_disp = response.headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disp, flags=re.I)
    if match:
        candidate = match.group(1).strip().strip('"')
        if candidate:
            return _safe_filename(candidate)

    path_name = Path(urlparse(fallback_url).path).name
    if path_name:
        return _safe_filename(path_name)
    return "attachment.bin"


def _extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(io.BytesIO(data))
        chunks = []
        total = 0
        for page in reader.pages:
            page_text = (page.extract_text() or "").strip()
            if not page_text:
                continue
            total += len(page_text)
            chunks.append(page_text)
            if total >= MAX_TEXT_CHARS_PER_ATTACHMENT:
                break
        return "\n".join(chunks)[:MAX_TEXT_CHARS_PER_ATTACHMENT]
    except Exception:
        return ""


def _extract_docx_text(data: bytes) -> str:
    """
    Best-effort DOCX text extraction without extra dependencies.
    DOCX is a ZIP; we read word/document.xml and strip XML tags.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except Exception:
        return ""

    xml_text = xml_bytes.decode("utf-8", errors="ignore")
    # Keep paragraph/line breaks roughly readable before stripping tags.
    xml_text = re.sub(r"</w:p>", "\n", xml_text)
    xml_text = re.sub(r"</w:tr>", "\n", xml_text)
    plain = re.sub(r"<[^>]+>", " ", xml_text)
    plain = html.unescape(" ".join(plain.split()))
    return plain[:MAX_TEXT_CHARS_PER_ATTACHMENT]


def _extract_zip_text(data: bytes) -> str:
    """Extract useful text snippets from supported files inside a ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
            infos = infos[:MAX_ZIP_ENTRIES_TO_SCAN]

            chunks: list[str] = []
            total = 0
            for info in infos:
                if info.file_size <= 0 or info.file_size > MAX_ZIP_ENTRY_BYTES:
                    continue
                name = str(info.filename)
                suffix = Path(name).suffix.lower()
                if suffix not in TEXT_ATTACHMENT_EXTENSIONS and suffix not in {".pdf", DOCX_EXTENSION}:
                    continue

                try:
                    blob = zf.read(info)
                except Exception:
                    continue

                if suffix == ".pdf":
                    text = _extract_pdf_text(blob)
                elif suffix == DOCX_EXTENSION:
                    text = _extract_docx_text(blob)
                else:
                    text = blob.decode("utf-8", errors="ignore")

                text = (text or "").strip()
                if not text:
                    continue

                excerpt = text[: max(0, MAX_TEXT_CHARS_PER_ATTACHMENT - total)]
                if not excerpt:
                    break
                chunks.append(f"[ZIP:{name}]\n{excerpt}")
                total += len(excerpt)
                if total >= MAX_TEXT_CHARS_PER_ATTACHMENT:
                    break

            return "\n\n".join(chunks)[:MAX_TEXT_CHARS_PER_ATTACHMENT]
    except Exception:
        return ""


def _extract_text_from_attachment(content: bytes, *, filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    lowered_ct = (content_type or "").lower()

    if suffix == ".zip" or "application/zip" in lowered_ct or "compressed" in lowered_ct:
        return _extract_zip_text(content)

    if suffix == ".pdf" or "application/pdf" in lowered_ct:
        return _extract_pdf_text(content)

    if suffix == DOCX_EXTENSION or "officedocument.wordprocessingml.document" in lowered_ct:
        return _extract_docx_text(content)

    is_text_mime = lowered_ct.startswith("text/") or "json" in lowered_ct or "xml" in lowered_ct
    if suffix in TEXT_ATTACHMENT_EXTENSIONS or is_text_mime:
        try:
            return content.decode("utf-8", errors="ignore")[:MAX_TEXT_CHARS_PER_ATTACHMENT]
        except Exception:
            return ""

    return ""


def _extract_attachment_links(description_html: str) -> list[str]:
    if not isinstance(description_html, str) or not description_html.strip():
        return []
    links = re.findall(r'href=["\']([^"\']+)["\']', description_html, flags=re.I)
    normalized = []
    seen = set()
    for link in links:
        absolute = urljoin(CANVAS_URL, link)
        if absolute in seen:
            continue
        seen.add(absolute)
        normalized.append(absolute)
    return normalized


def _collect_attachment_candidates(details: dict, description_html: str) -> list[dict]:
    candidates = []
    seen = set()

    attachments = details.get("attachments", [])
    if isinstance(attachments, list):
        for att in attachments:
            if not isinstance(att, dict):
                continue
            url = att.get("url") or att.get("download_url") or att.get("preview_url")
            if not isinstance(url, str) or not url.strip():
                continue
            absolute = urljoin(CANVAS_URL, url)
            if absolute in seen:
                continue
            seen.add(absolute)
            candidates.append({
                "url": absolute,
                "filename": str(att.get("filename") or Path(urlparse(absolute).path).name or "attachment.bin"),
                "source": "api_attachments",
            })

    for link in _extract_attachment_links(description_html):
        looks_like_file = "/files/" in link or "download" in link or Path(urlparse(link).path).suffix
        if not looks_like_file or link in seen:
            continue
        seen.add(link)
        candidates.append({
            "url": link,
            "filename": Path(urlparse(link).path).name or "linked_attachment.bin",
            "source": "description_link",
        })

    return candidates[:MAX_ATTACHMENTS_PER_BRIEF]


def _download_assignment_attachments(
    *,
    assignment_id: int | str | None,
    course_id: int | str | None,
    details: dict,
    description_html: str,
) -> list[dict]:
    if USE_MOCK:
        return []

    candidates = _collect_attachment_candidates(details, description_html)
    if not candidates:
        return []

    target_dir = BRIEF_DOWNLOAD_DIR / f"{course_id or 'unknown'}_{assignment_id or 'unknown'}"
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for item in candidates:
        url = item.get("url", "")
        if not isinstance(url, str) or not url:
            continue

        response = _http_get(url)
        if response is None:
            downloaded.append({
                "url": url,
                "filename": _safe_filename(str(item.get("filename", "attachment.bin"))),
                "saved_path": "",
                "text_excerpt": "",
                "status": "download_failed",
            })
            continue

        raw = response.content or b""
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raw = raw[:MAX_ATTACHMENT_BYTES]

        filename = _filename_from_response(response, url)
        save_path = target_dir / filename
        try:
            save_path.write_bytes(raw)
        except Exception:
            downloaded.append({
                "url": url,
                "filename": filename,
                "saved_path": "",
                "text_excerpt": "",
                "status": "save_failed",
            })
            continue

        text_excerpt = _extract_text_from_attachment(
            raw,
            filename=filename,
            content_type=response.headers.get("content-type", ""),
        )

        downloaded.append({
            "url": url,
            "filename": filename,
            "saved_path": str(save_path),
            "text_excerpt": text_excerpt,
            "status": "downloaded",
        })

    return downloaded


def _compose_assignment_brief_text(description_text: str, attachments: list[dict]) -> str:
    sections = []
    if description_text.strip():
        sections.append("Assignment description:\n" + description_text.strip())

    for att in attachments:
        filename = att.get("filename", "attachment")
        excerpt = str(att.get("text_excerpt", "")).strip()
        if excerpt:
            sections.append(f"Attachment ({filename}) extracted text:\n{excerpt}")
        else:
            sections.append(
                f"Attachment ({filename}) was downloaded, but no text could be extracted automatically."
            )

    return "\n\n".join(s for s in sections if s.strip())


def find_assignment_todo(query: str) -> dict | None:
    """
    Find a Canvas todo assignment by id or fuzzy title match.
    Returns the todo item.
    """
    query_norm = str(query or "").strip().lower()
    if not query_norm:
        return None

    todos = get_todo_items()
    for item in todos:
        assignment = item.get("assignment", {})
        assignment_id = str(assignment.get("id", "")).strip().lower()
        if assignment_id and query_norm == assignment_id:
            return item

    # Fuzzy match on assignment name
    for item in todos:
        assignment = item.get("assignment", {})
        title = str(assignment.get("name", "")).strip().lower()
        if query_norm and query_norm in title:
            return item

    return None


def get_assignment_brief(assignment_query: str) -> dict | None:
    """
    Download/resolve an assignment brief by id or title.

    Returns:
    {
      assignment_id, course_id, title, course_name, due_at, source_url,
      brief_text, confidence
    }
    """
    query_norm = str(assignment_query or "").strip()
    if not query_norm:
        return None

    todo_item = find_assignment_todo(query_norm)
    assignment = todo_item.get("assignment", {}) if todo_item else {}
    assignment_id = assignment.get("id")
    course_id = assignment.get("course_id")
    title = assignment.get("name")
    course_name = todo_item.get("context_name") if todo_item else None
    due_at = assignment.get("due_at")
    source_url = assignment.get("html_url")

    if assignment_id and course_id:
        # Real Canvas assignment endpoint often includes HTML description and attachments.
        details = _api_get_json(f"/api/v1/courses/{course_id}/assignments/{assignment_id}")
        if isinstance(details, dict):
            description_html = str(details.get("description", ""))
            description = _strip_html(description_html)
            attachments = _download_assignment_attachments(
                assignment_id=assignment_id,
                course_id=course_id,
                details=details,
                description_html=description_html,
            )
            combined_text = _compose_assignment_brief_text(description, attachments)
            if combined_text:
                return {
                    "assignment_id": details.get("id", assignment_id),
                    "course_id": details.get("course_id", course_id),
                    "title": details.get("name") or title,
                    "course_name": course_name,
                    "due_at": details.get("due_at") or due_at,
                    "source_url": details.get("html_url") or source_url,
                    "brief_text": combined_text,
                    "attachments": attachments,
                    "confidence": "high",
                }

    # Mock brief lookup by assignment id or title (mock mode only).
    if USE_MOCK:
        for brief in _load_mock_briefs():
            bid = str(brief.get("assignment_id", "")).strip().lower()
            btitle = str(brief.get("title", "")).strip().lower()
            if (assignment_id and str(assignment_id).lower() == bid) or (
                query_norm.lower() and query_norm.lower() in btitle
            ):
                return {
                    "assignment_id": brief.get("assignment_id", assignment_id),
                    "course_id": brief.get("course_id", course_id),
                    "title": brief.get("title") or title,
                    "course_name": brief.get("course_name") or course_name,
                    "due_at": brief.get("due_at") or due_at,
                    "source_url": brief.get("source_url") or source_url,
                    "brief_text": brief.get("brief_text", ""),
                    "attachments": [],
                    "confidence": "medium",
                }

    # Final fallback: synthesize minimal brief from todo metadata.
    if todo_item and title:
        synthesized = (
            f"Assignment: {title}\n"
            f"Course: {course_name or 'Unknown'}\n"
            f"Due: {due_at or 'Not provided'}\n"
            "No full brief text was retrieved. Use the Canvas URL for full instructions."
        )
        return {
            "assignment_id": assignment_id,
            "course_id": course_id,
            "title": title,
            "course_name": course_name,
            "due_at": due_at,
            "source_url": source_url,
            "brief_text": synthesized,
            "attachments": [],
            "confidence": "low",
        }

    return None


if __name__ == "__main__":
    print("=== Canvas Client Test ===")
    print(f"Mock mode: {USE_MOCK}")
    print(f"\nTodo items ({len(get_todo_items())}):")
    for item in get_todo_items():
        a = item["assignment"]
        print(f"  - {a['name']} (due: {a['due_at']})")
    print(f"\nUpcoming events ({len(get_upcoming_events())}):")
    for ev in get_upcoming_events():
        print(f"  - {ev['title']} @ {ev.get('location_name', 'TBA')}")
    print(f"\nCourses ({len(get_courses())}):")
    for c in get_courses():
        print(f"  - {c['name']}")

    print("\nBrief test:")
    sample = get_assignment_brief("lab 5")
    if sample:
        print(f"  - {sample.get('title')} ({sample.get('confidence')})")
