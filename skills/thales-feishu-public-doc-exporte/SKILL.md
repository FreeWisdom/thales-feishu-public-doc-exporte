---
name: thales-feishu-public-doc-exporte
description: Export publicly readable Feishu/Lark docx or wiki article links into local title-named folders with Markdown, plain text, structured JSON, raw HTML, and downloaded images. Use when the user provides a Feishu/Lark document or wiki URL and asks to save, export, download, archive, summarize, or work from the full article content.
---

# Thales Feishu Public Doc Exporte

Use this skill for public Feishu/Lark article links that can be opened without private API credentials.

## Workflow

1. Run the local exporter from the project root:

```bash
cd <feishu-exporter-repo>
python3 -m feishu_doc_exporter export-public "<feishu_or_lark_url>" --output-dir outputs
```

On Thales' machine the project root is usually `/Users/Thales/feishu`.

2. Read the generated manifest:

```bash
cat "outputs/<article title>/public_manifest.json"
```

3. Use the exported artifacts:
   - `public_content.md`: primary Markdown for follow-up work
   - `public_content.txt`: plain text
   - `public_records.json`: structured Feishu block data
   - `public_raw.html`: original public page HTML
   - `images/`: downloaded article images

## Rules

- Public export folders are named `outputs/<article title>/`.
- If export succeeds, report the title, folder path, line count, and image count.
- If public export fails, explain whether it looks like a private document, unsupported document type, or parser issue.
- For private documents, use API/OAuth/browser-login approaches instead of this public exporter.
