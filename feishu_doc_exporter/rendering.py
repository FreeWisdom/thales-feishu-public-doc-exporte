from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def extract_document_title(meta_payload: Dict[str, Any], fallback: str) -> str:
    data = meta_payload.get("data") or {}
    document = data.get("document") or {}
    title = document.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return fallback


def extract_raw_text(raw_payload: Dict[str, Any]) -> str:
    data = raw_payload.get("data")
    candidates = []
    if isinstance(data, dict):
        candidates.extend([data.get("content"), data.get("raw_content"), data.get("text")])
        document = data.get("document")
        if isinstance(document, dict):
            candidates.extend([document.get("content"), document.get("raw_content"), document.get("text")])
    candidates.extend([raw_payload.get("content"), raw_payload.get("raw_content"), raw_payload.get("text")])

    for value in candidates:
        if isinstance(value, str):
            return value

    return ""


def render_markdown(
    *,
    title: str,
    source_url: str,
    document_id: str,
    raw_text: str,
    exported_at: Optional[datetime] = None,
) -> str:
    exported_at = exported_at or datetime.now(timezone.utc)
    body = raw_text.strip()
    if not body:
        body = "_No plain text content returned by Feishu raw_content API._"

    return (
        f"# {title}\n\n"
        f"- Source: {source_url}\n"
        f"- Document ID: `{document_id}`\n"
        f"- Exported at: {exported_at.isoformat()}\n\n"
        "---\n\n"
        f"{body}\n"
    )


def safe_filename(value: str, *, fallback: str = "document", limit: int = 90) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = fallback
    return cleaned[:limit].rstrip()


def ensure_extension(filename: str, extension: str) -> str:
    extension = extension.lstrip(".")
    if filename.lower().endswith(f".{extension.lower()}"):
        return filename
    return f"{filename}.{extension}"
