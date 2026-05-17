# Feishu Doc Exporter

This project exports a Feishu/Lark document link into local artifacts for later AI or manual work:

- `raw_content.txt`: plain text from the document API
- `content.md`: lightly organized Markdown wrapper with title/source metadata
- `blocks.json`: structured block data, when the API allows it
- `metadata.json` and `manifest.json`: reproducible export metadata
- optional `.docx`/`.pdf`/other Drive export files

## Agent or Skill?

An **agent** is the runtime worker: it decides steps, calls tools/APIs, handles retries, and can run as a service or MCP server.

A **skill** is a packaged instruction/workflow/resource bundle for an agent. It is not a running service by itself. For this task, a skill is the right abstraction because the repeated job is: given a Feishu doc link, use the same export workflow and scripts.

This repo includes both:

- a reusable CLI in `feishu_doc_exporter/`
- a local Codex skill in `skills/thales-feishu-public-doc-exporte/`

## Public Web Export

If a Feishu document is publicly readable in a browser, use the public SSR exporter. It follows Feishu's guest redirect flow and extracts text from the server-rendered page data, so it does not need OpenAPI credentials.

```bash
python3 -m feishu_doc_exporter export-public \
  "https://my.feishu.cn/docx/CnPQdk671oL5wSxDV7YchA2dnpf" \
  --output-dir outputs
```

This writes into `outputs/<article title>/` by default: `public_content.md`, `public_content.txt`, `public_records.json`, `public_raw.html`, downloaded images under `images/`, and `public_manifest.json`.

## Setup

Create a Feishu custom app, grant it document read/export permissions, and make sure the target document is accessible to that app or to the token user.

```bash
cp .env.example .env
# edit .env with your app credentials or FEISHU_ACCESS_TOKEN
```

Install the local Codex skill:

```bash
./install.sh
```

## Export This Document

```bash
python3 -m feishu_doc_exporter export \
  "https://my.feishu.cn/docx/CnPQdk671oL5wSxDV7YchA2dnpf" \
  --env-file .env \
  --output-dir outputs
```

By default the CLI tries to:

1. fetch document metadata
2. fetch plain text content
3. fetch all blocks as JSON
4. create a Drive export task and download a `.docx`

If you only want API text/JSON and no binary export:

```bash
python3 -m feishu_doc_exporter export \
  "https://my.feishu.cn/docx/CnPQdk671oL5wSxDV7YchA2dnpf" \
  --env-file .env \
  --skip-drive-export
```

API export output goes to `outputs/<document_id>/`. Public web export output goes to `outputs/<article title>/`.
