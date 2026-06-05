#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
SKILLS_DIR="$CODEX_HOME/skills"
TARGET="$SKILLS_DIR/deepseek-token-saver"

mkdir -p "$SKILLS_DIR"
rm -rf "$TARGET"
cp -R "$ROOT/skills/deepseek-token-saver" "$TARGET"

echo "Installed deepseek-token-saver skill to:"
echo "$TARGET"
echo
echo "Restart Codex so the skill metadata is loaded."
