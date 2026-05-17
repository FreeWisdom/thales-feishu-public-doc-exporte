from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .client import DocumentRef, FeishuAPIError, FeishuClient, parse_document_ref
from .public_web import PublicExportError, export_public_document, write_public_export
from .rendering import ensure_extension, extract_document_title, extract_raw_text, render_markdown, safe_filename


JsonObject = Dict[str, Any]


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "export":
        return export_command(args)
    if args.command == "export-public":
        return export_public_command(args)

    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu-doc-export", description="Export Feishu/Lark document content.")
    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser("export", help="Export a Feishu document by URL or token.")
    export_parser.add_argument("document", help="Feishu doc URL or document token.")
    export_parser.add_argument("--env-file", default=".env", help="Optional dotenv file. Default: .env")
    export_parser.add_argument("--output-dir", default="outputs", help="Directory for export artifacts.")
    export_parser.add_argument("--base-url", default=None, help="Open API base URL. Default: FEISHU_OPEN_BASE_URL or open.feishu.cn")
    export_parser.add_argument("--app-id", default=None, help="Feishu app id. Default: FEISHU_APP_ID")
    export_parser.add_argument("--app-secret", default=None, help="Feishu app secret. Default: FEISHU_APP_SECRET")
    export_parser.add_argument("--access-token", default=None, help="Existing tenant/user access token. Default: FEISHU_ACCESS_TOKEN")
    export_parser.add_argument("--export-type", default=None, help="Drive export type. Auto-detected from URL; docx links use docx.")
    export_parser.add_argument(
        "--export-extension",
        action="append",
        default=None,
        help="Drive export file extension to download. Can be repeated. Default: docx",
    )
    export_parser.add_argument("--skip-blocks", action="store_true", help="Skip fetching document blocks JSON.")
    export_parser.add_argument("--skip-drive-export", action="store_true", help="Skip Drive export/download task.")
    export_parser.add_argument("--strict", action="store_true", help="Exit non-zero if any optional export step fails.")
    export_parser.add_argument("--timeout", type=int, default=120, help="Drive export polling timeout in seconds.")
    export_parser.add_argument("--poll-interval", type=float, default=2.0, help="Drive export polling interval in seconds.")

    public_parser = subparsers.add_parser(
        "export-public",
        help="Export a public Feishu document from its SSR web page without OpenAPI credentials.",
    )
    public_parser.add_argument("document", help="Public Feishu doc URL.")
    public_parser.add_argument("--output-dir", default="outputs", help="Directory for export artifacts.")
    public_parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")

    return parser


def export_public_command(args: argparse.Namespace) -> int:
    doc_ref = parse_document_ref(args.document)
    output_root = Path(args.output_dir).expanduser().resolve()
    output_dir = output_root / doc_ref.token
    manifest: JsonObject = {
        "source_url": doc_ref.url,
        "document_id": doc_ref.token,
        "url_type": doc_ref.url_type,
        "export_type": "public_web",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "files": {},
        "errors": [],
    }

    try:
        export = export_public_document(args.document, timeout=args.timeout)
        output_dir = title_output_dir(output_root, export.title, export.document_ref.token)
        result = write_public_export(export, output_dir)
        manifest["files"].update(
            {key: value for key, value in result.items() if key not in {"line_count", "image_count"}}
        )
        manifest["title"] = export.title
        manifest["line_count"] = result["line_count"]
        manifest["image_count"] = result["image_count"]
        print(f"public_web: ok ({result['line_count']} text/image lines, {result['image_count']} images)")
    except Exception as exc:
        record_error(manifest, "public_web", exc)
        print(f"public_web: failed: {exc}", file=sys.stderr)
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "public_manifest.json", manifest)
        return 1

    write_json(output_dir / "public_manifest.json", manifest)
    print(f"manifest: {output_dir / 'public_manifest.json'}")
    return 0


def title_output_dir(output_root: Path, title: str, document_id: str) -> Path:
    name = safe_filename(title, fallback=document_id, limit=120)
    candidate = output_root / name
    manifest_path = candidate / "public_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if manifest.get("document_id") and manifest.get("document_id") != document_id:
            return output_root / safe_filename(f"{name} {document_id[:8]}", fallback=document_id, limit=140)
    return candidate


def export_command(args: argparse.Namespace) -> int:
    load_env_file(Path(args.env_file))

    doc_ref = parse_document_ref(args.document, export_type=args.export_type)
    output_root = Path(args.output_dir).expanduser().resolve()
    output_dir = output_root / doc_ref.token
    output_dir.mkdir(parents=True, exist_ok=True)

    client = FeishuClient(
        base_url=args.base_url or os.getenv("FEISHU_OPEN_BASE_URL", "https://open.feishu.cn"),
        access_token=args.access_token or os.getenv("FEISHU_ACCESS_TOKEN"),
        app_id=args.app_id or os.getenv("FEISHU_APP_ID"),
        app_secret=args.app_secret or os.getenv("FEISHU_APP_SECRET"),
    )

    exported_at = datetime.now(timezone.utc)
    manifest: JsonObject = {
        "source_url": doc_ref.url,
        "document_id": doc_ref.token,
        "url_type": doc_ref.url_type,
        "export_type": doc_ref.export_type,
        "exported_at": exported_at.isoformat(),
        "files": {},
        "errors": [],
    }

    successes = 0
    title = doc_ref.token

    try:
        meta_payload = client.get_document_meta(doc_ref.token)
        write_json(output_dir / "metadata.json", meta_payload)
        manifest["files"]["metadata"] = str(output_dir / "metadata.json")
        title = extract_document_title(meta_payload, fallback=doc_ref.token)
        successes += 1
        print(f"metadata: ok ({title})")
    except Exception as exc:
        record_error(manifest, "metadata", exc)
        print(f"metadata: failed: {exc}", file=sys.stderr)

    try:
        raw_payload = client.get_document_raw_content(doc_ref.token)
        write_json(output_dir / "raw_content.response.json", raw_payload)
        raw_text = extract_raw_text(raw_payload)
        (output_dir / "raw_content.txt").write_text(raw_text, encoding="utf-8")
        (output_dir / "content.md").write_text(
            render_markdown(
                title=title,
                source_url=doc_ref.url,
                document_id=doc_ref.token,
                raw_text=raw_text,
                exported_at=exported_at,
            ),
            encoding="utf-8",
        )
        manifest["files"]["raw_response"] = str(output_dir / "raw_content.response.json")
        manifest["files"]["raw_text"] = str(output_dir / "raw_content.txt")
        manifest["files"]["markdown"] = str(output_dir / "content.md")
        successes += 1
        print(f"raw_content: ok ({len(raw_text)} chars)")
    except Exception as exc:
        record_error(manifest, "raw_content", exc)
        print(f"raw_content: failed: {exc}", file=sys.stderr)

    if not args.skip_blocks:
        try:
            blocks_payload = client.list_document_blocks(doc_ref.token)
            write_json(output_dir / "blocks.json", blocks_payload)
            manifest["files"]["blocks"] = str(output_dir / "blocks.json")
            successes += 1
            print(f"blocks: ok ({blocks_payload.get('count', 0)} blocks)")
        except Exception as exc:
            record_error(manifest, "blocks", exc)
            print(f"blocks: failed: {exc}", file=sys.stderr)

    if not args.skip_drive_export:
        extensions = args.export_extension or ["docx"]
        for extension in extensions:
            try:
                path = run_drive_export(
                    client=client,
                    doc_ref=doc_ref,
                    title=title,
                    output_dir=output_dir,
                    extension=extension,
                    timeout_seconds=args.timeout,
                    poll_interval=args.poll_interval,
                )
                manifest["files"][f"drive_export_{extension}"] = str(path)
                successes += 1
                print(f"drive_export[{extension}]: ok ({path})")
            except Exception as exc:
                record_error(manifest, f"drive_export_{extension}", exc)
                print(f"drive_export[{extension}]: failed: {exc}", file=sys.stderr)

    write_json(output_dir / "manifest.json", manifest)
    print(f"manifest: {output_dir / 'manifest.json'}")

    if manifest["errors"] and (args.strict or successes == 0):
        return 1
    return 0


def run_drive_export(
    *,
    client: FeishuClient,
    doc_ref: DocumentRef,
    title: str,
    output_dir: Path,
    extension: str,
    timeout_seconds: int,
    poll_interval: float,
) -> Path:
    create_payload = client.create_export_task(
        token=doc_ref.token,
        export_type=doc_ref.export_type,
        file_extension=extension,
    )
    write_json(output_dir / f"export_{extension}.create.json", create_payload)
    ticket = ((create_payload.get("data") or {}).get("ticket") or "").strip()
    if not ticket:
        raise FeishuAPIError("export ticket not found", payload=create_payload)

    result_payload = client.wait_for_export(
        ticket=ticket,
        token=doc_ref.token,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
    )
    write_json(output_dir / f"export_{extension}.result.json", result_payload)
    result = (result_payload.get("data") or {}).get("result") or {}
    file_token = result.get("file_token")
    if not isinstance(file_token, str) or not file_token:
        raise FeishuAPIError("export file_token not found", payload=result_payload)

    file_name = result.get("file_name")
    if not isinstance(file_name, str) or not file_name.strip():
        file_name = title
    filename = ensure_extension(safe_filename(file_name, fallback=doc_ref.token), extension)
    return client.download_export_file(file_token=file_token, output_path=output_dir / filename)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_error(manifest: JsonObject, step: str, exc: Exception) -> None:
    error: JsonObject = {"step": step, "message": str(exc), "type": exc.__class__.__name__}
    if isinstance(exc, FeishuAPIError):
        error["status"] = exc.status
        error["payload"] = exc.payload
    manifest["errors"].append(error)


if __name__ == "__main__":
    raise SystemExit(main())
