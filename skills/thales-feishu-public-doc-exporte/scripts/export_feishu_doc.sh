#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <feishu-doc-or-wiki-url> [output-dir]" >&2
  exit 2
fi

DOC_URL="$1"
OUTPUT_DIR="${2:-outputs}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

cd "$PROJECT_ROOT"
python3 -m feishu_doc_exporter export-public "$DOC_URL" --output-dir "$OUTPUT_DIR"
