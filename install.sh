#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="thales-feishu-public-doc-exporte"
SKILL_SOURCE="$PROJECT_ROOT/skills/$SKILL_NAME"
SKILL_TARGET="$HOME/.codex/skills/$SKILL_NAME"

if [[ ! -f "$SKILL_SOURCE/SKILL.md" ]]; then
  echo "Skill source not found: $SKILL_SOURCE" >&2
  exit 1
fi

mkdir -p "$HOME/.codex/skills"
ln -sfn "$SKILL_SOURCE" "$SKILL_TARGET"

echo "Installed Codex skill: $SKILL_TARGET -> $SKILL_SOURCE"
echo "Try: 飞书导出：<feishu-link>"
