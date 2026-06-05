#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m py_compile \
  deepseek_agent.py \
  deepseek_delegate.py \
  deepseek_room.py \
  deepseek_transcript.py \
  skills/deepseek-token-saver/scripts/deepseek_agent.py \
  skills/deepseek-token-saver/scripts/deepseek_delegate.py \
  skills/deepseek-token-saver/scripts/deepseek_room.py \
  skills/deepseek-token-saver/scripts/deepseek_transcript.py

python3 -m unittest discover -s tests
python3 -m unittest discover -s skills/deepseek-token-saver/tests

python3 deepseek_delegate.py \
  --route-only \
  --phase final \
  "Final review should stay with GPT-5.5"

if command -v rg >/dev/null 2>&1; then
  if rg -n "sk-[A-Za-z0-9_-]{8,}|Bearer [A-Za-z0-9._-]+|DEEPSEEK_API_KEY=\"|DEEPSEEK_API_KEY='" \
    . \
    -g '!__pycache__/**' \
    -g '!*.pyc' \
    -g '!.deepseek-token-saver/**' \
    -g '!scripts/preflight.sh'; then
    echo "Potential secret pattern found; inspect before publishing." >&2
    exit 1
  fi
fi

echo "Preflight OK"
