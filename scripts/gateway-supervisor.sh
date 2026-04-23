#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hermes/hermes-agent"
BIN="$ROOT/venv/bin/hermes"
LOG_DIR="/home/hermes/.hermes/logs"
PID_FILE="/home/hermes/.hermes/gateway.pid"

mkdir -p "$LOG_DIR"

# 이미 실행 중이면 종료
if pgrep -fu "$USER" -f "$BIN gateway run" >/dev/null 2>&1; then
  exit 0
fi

nohup "$BIN" gateway run >> "$LOG_DIR/gateway.out.log" 2>> "$LOG_DIR/gateway.err.log" &
echo $! > "$PID_FILE"
