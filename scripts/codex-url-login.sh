#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Codex URL login helper (Hermes auth flow)

Usage:
  scripts/codex-url-login.sh [--verify]

What it does:
  1) Starts OAuth device-code login for openai-codex (no browser auto-open)
  2) Prints URL + code in terminal
  3) Waits for browser sign-in completion
  4) Optionally verifies with a real chat call (--verify)
EOF
  exit 0
fi

if [[ -f "venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source venv/bin/activate
fi

echo "[1/2] Starting OpenAI Codex device login (URL + code will be shown)"
python -m hermes_cli.main auth add openai-codex --type oauth --no-browser

echo "[2/2] Current credential pool"
python -m hermes_cli.main auth list

if [[ "${1:-}" == "--verify" ]]; then
  echo "[verify] Running a live codex provider check"
  python -m hermes_cli.main chat -Q \
    --provider openai-codex \
    -m gpt-5.3-codex \
    -q "정상 인증이면 VERIFIED만 출력"
fi

echo "Done."
