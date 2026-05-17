from __future__ import annotations

import html
import http.cookiejar
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .client import DocumentRef, parse_document_ref


JsonObject = Dict[str, Any]


class PublicExportError(RuntimeError):
    pass


@dataclass
class PublicExport:
    document_ref: DocumentRef
    title: str
    html: str
    records: JsonObject
    lines: List[str]
    opener: Any


def build_public_opener() -> Any:
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))


def fetch_public_html(url: str, *, timeout: int = 30, opener: Optional[Any] = None) -> str:
    opener = opener or build_public_opener()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def export_public_document(url_or_token: str, *, timeout: int = 30) -> PublicExport:
    doc_ref = parse_document_ref(url_or_token)
    opener = build_public_opener()
    html_text = fetch_public_html(doc_ref.url, timeout=timeout, opener=opener)
    records = extract_catalog_record_info(html_text)
    lines = render_records_to_lines(records, doc_ref.token)
    if not lines:
        raise PublicExportError("no text records found in public Feishu HTML")
    title = extract_public_title(records, doc_ref.token) or doc_ref.token
    return PublicExport(document_ref=doc_ref, title=title, html=html_text, records=records, lines=lines, opener=opener)


def extract_catalog_record_info(html_text: str) -> JsonObject:
    block_map = extract_block_map(html_text)
    if block_map:
        return {"isEmptyCatalog": False, "headingRecords": block_map}

    marker = "window.catalogRecordInfo="
    start = html_text.find(marker)
    if start == -1:
        raise PublicExportError("window.catalogRecordInfo not found in HTML")

    obj_start = html_text.find("{", start + len(marker))
    if obj_start == -1:
        raise PublicExportError("catalogRecordInfo JSON object start not found")

    obj_end = find_balanced_object_end(html_text, obj_start)
    raw = html_text[obj_start:obj_end]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublicExportError(f"could not parse catalogRecordInfo JSON: {exc}") from exc
    records = payload.get("headingRecords")
    if isinstance(records, dict) and records:
        return payload
    raise PublicExportError("no block_map or catalog records found in HTML")


def extract_block_map(html_text: str) -> JsonObject:
    marker = '"block_map":'
    start = html_text.find(marker)
    if start == -1:
        return {}

    obj_start = html_text.find("{", start + len(marker))
    if obj_start == -1:
        return {}

    try:
        obj_end = find_balanced_object_end(html_text, obj_start)
        payload = json.loads(html_text[obj_start:obj_end])
    except (PublicExportError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def find_balanced_object_end(value: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(value)):
        char = value[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1

    raise PublicExportError("catalogRecordInfo JSON object is incomplete")


def render_records_to_lines(
    records_payload: JsonObject,
    document_id: str,
    *,
    image_paths: Optional[Dict[str, str]] = None,
) -> List[str]:
    records = records_payload.get("headingRecords")
    if not isinstance(records, dict):
        raise PublicExportError("headingRecords not found in catalogRecordInfo")

    page = records.get(document_id)
    if not isinstance(page, dict):
        page = next((record for record in records.values() if get_record_type(record) == "page"), None)
    if not isinstance(page, dict):
        raise PublicExportError("page record not found")

    output: List[str] = []
    seen: Set[str] = set()
    title = get_record_text(page)
    if title:
        output.append(f"# {title}")
        output.append("")

    for child_id in get_children(page):
        append_record_lines(output, records, child_id, seen, image_paths=image_paths or {})

    return normalize_lines(output)


def extract_public_title(records_payload: JsonObject, document_id: str) -> str:
    records = records_payload.get("headingRecords")
    if not isinstance(records, dict):
        return ""

    page = records.get(document_id)
    if not isinstance(page, dict):
        page = next((record for record in records.values() if get_record_type(record) == "page"), None)
    if not isinstance(page, dict):
        return ""
    return get_record_text(page)


def append_record_lines(
    output: List[str],
    records: JsonObject,
    record_id: str,
    seen: Set[str],
    *,
    image_paths: Dict[str, str],
) -> None:
    if record_id in seen:
        return
    seen.add(record_id)

    record = records.get(record_id)
    if not isinstance(record, dict):
        return

    record_type = get_record_type(record)
    text = get_record_text(record)
    line = format_line(record_id, record_type, text, record, image_paths=image_paths)
    if line:
        output.append(line)
        output.append("")

    for child_id in get_children(record):
        append_record_lines(output, records, child_id, seen, image_paths=image_paths)


def get_record_type(record: JsonObject) -> str:
    data = record.get("data") or {}
    value = data.get("type")
    return value if isinstance(value, str) else ""


def get_children(record: JsonObject) -> List[str]:
    data = record.get("data") or {}
    children = data.get("children")
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, str)]


def get_record_text(record: JsonObject) -> str:
    data = record.get("data") or {}
    text_node = data.get("text")
    if not isinstance(text_node, dict):
        return ""
    initial = text_node.get("initialAttributedTexts")
    if not isinstance(initial, dict):
        return ""
    text_map = initial.get("text")
    if not isinstance(text_map, dict):
        return ""

    parts = []
    for key in sorted(text_map, key=sort_text_key):
        value = text_map.get(key)
        if isinstance(value, str):
            parts.append(value)
    return html.unescape("".join(parts)).replace("\u200b", "").strip()


def sort_text_key(value: Any) -> Any:
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return str(value)


def format_line(
    record_id: str,
    record_type: str,
    text: str,
    record: JsonObject,
    *,
    image_paths: Dict[str, str],
) -> str:
    if text:
        if record_type == "heading1":
            return f"# {text}"
        if record_type == "heading2":
            return f"## {text}"
        if record_type == "heading3":
            return f"### {text}"
        if record_type == "heading4":
            return f"#### {text}"
        if record_type == "heading5":
            return f"##### {text}"
        if record_type == "heading6":
            return f"###### {text}"
        if record_type == "bullet":
            return f"- {text}"
        if record_type == "task_list":
            return f"- [ ] {text}"
        return text

    if record_type == "image":
        path = image_paths.get(record_id)
        if path:
            return f"![Image]({path})"
        token = get_image_info(record).get("token")
        return f"[Image: {token}]" if token else "[Image]"
    if record_type in {"sheet", "bitable", "file", "iframe"}:
        return f"[Embedded {record_type}]"
    return ""


def get_data_value(record: JsonObject, key: str) -> Optional[str]:
    data = record.get("data") or {}
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def get_image_info(record: JsonObject) -> JsonObject:
    data = record.get("data") or {}
    image = data.get("image")
    return image if isinstance(image, dict) else {}


def iter_image_records(records_payload: JsonObject) -> Iterable[Tuple[str, JsonObject]]:
    records = records_payload.get("headingRecords")
    if not isinstance(records, dict):
        return []
    return [
        (record_id, record)
        for record_id, record in records.items()
        if isinstance(record, dict) and get_record_type(record) == "image" and get_image_info(record).get("token")
    ]


def download_public_images(export: PublicExport, output_dir: Path, *, timeout: int = 30) -> Dict[str, str]:
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    image_paths: Dict[str, str] = {}

    for index, (record_id, record) in enumerate(iter_image_records(export.records), start=1):
        image = get_image_info(record)
        token = image.get("token")
        if not isinstance(token, str) or not token:
            continue
        extension = image_extension(image)
        filename = f"{index:03d}-{record_id}.{extension}"
        output_path = images_dir / filename
        url = image_download_url(record_id, token)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Referer": export.document_ref.url,
            },
        )
        with export.opener.open(request, timeout=timeout) as response:
            output_path.write_bytes(response.read())
        image_paths[record_id] = f"images/{filename}"

    return image_paths


def image_extension(image: JsonObject) -> str:
    name = image.get("name")
    if isinstance(name, str) and "." in name:
        extension = name.rsplit(".", 1)[-1].lower()
        if re.fullmatch(r"[a-z0-9]{2,5}", extension):
            return "jpg" if extension == "jpeg" else extension
    mime_type = image.get("mimeType")
    if mime_type == "image/png":
        return "png"
    if mime_type == "image/webp":
        return "webp"
    return "jpg"


def image_download_url(record_id: str, token: str) -> str:
    return (
        "https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/v2/cover/"
        f"{token}/?fallback_source=1&height=1600&mount_node_token={record_id}"
        "&mount_point=docx_image&policy=equal&width=1600"
    )


def normalize_lines(lines: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    blank = False
    for raw_line in lines:
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if not blank and normalized:
                normalized.append("")
            blank = True
            continue
        normalized.append(line)
        blank = False
    while normalized and not normalized[-1]:
        normalized.pop()
    return normalized


def write_public_export(export: PublicExport, output_dir: Path) -> JsonObject:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths = download_public_images(export, output_dir)
    lines = render_records_to_lines(export.records, export.document_ref.token, image_paths=image_paths)
    html_path = output_dir / "public_raw.html"
    records_path = output_dir / "public_records.json"
    text_path = output_dir / "public_content.txt"
    markdown_path = output_dir / "public_content.md"

    html_path.write_text(export.html, encoding="utf-8")
    records_path.write_text(json.dumps(export.records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = "\n".join(line for line in lines if line.strip() and not line.startswith("# "))
    text_path.write_text(text + "\n", encoding="utf-8")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "public_raw_html": str(html_path),
        "public_records": str(records_path),
        "public_text": str(text_path),
        "public_markdown": str(markdown_path),
        "image_count": len(image_paths),
        "images_dir": str(output_dir / "images"),
        "line_count": len([line for line in lines if line.strip()]),
    }
