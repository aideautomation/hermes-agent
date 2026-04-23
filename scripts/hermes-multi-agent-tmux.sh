#!/usr/bin/env bash
set -euo pipefail

# Multi-agent Hermes launcher for tmux
# - Uses isolated worktrees (-w)
# - Optional profile per agent (-p)
# - Creates one tmux session with multiple windows

SESSION_NAME="hermes-multi"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Hermes multi-agent tmux launcher

Usage:
  scripts/hermes-multi-agent-tmux.sh start [session-name]
  scripts/hermes-multi-agent-tmux.sh start-profiles [session-name]
  scripts/hermes-multi-agent-tmux.sh attach [session-name]
  scripts/hermes-multi-agent-tmux.sh list
  scripts/hermes-multi-agent-tmux.sh stop [session-name]

Modes:
  start            Start 3 agents with worktree isolation only
                   windows: planner, builder, reviewer

  start-profiles   Start 3 agents with profile+worktree isolation
                   profiles: planner, builder, reviewer

Examples:
  scripts/hermes-multi-agent-tmux.sh start
  scripts/hermes-multi-agent-tmux.sh start myproj
  scripts/hermes-multi-agent-tmux.sh start-profiles
  scripts/hermes-multi-agent-tmux.sh attach myproj
  scripts/hermes-multi-agent-tmux.sh stop myproj
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[ERROR] Missing command: $1" >&2
    exit 1
  }
}

start_plain() {
  local name="$1"
  if tmux has-session -t "$name" 2>/dev/null; then
    echo "[INFO] Session already exists: $name"
    echo "Attach with: tmux attach -t $name"
    return 0
  fi

  tmux new-session -d -s "$name" -n planner "cd '$ROOT_DIR' && hermes -w"
  tmux new-window  -t "$name" -n builder  "cd '$ROOT_DIR' && hermes -w"
  tmux new-window  -t "$name" -n reviewer "cd '$ROOT_DIR' && hermes -w"

  echo "[OK] Started tmux session: $name"
  echo "     windows: planner | builder | reviewer"
  echo "Attach: tmux attach -t $name"
}

start_profiles() {
  local name="$1"
  if tmux has-session -t "$name" 2>/dev/null; then
    echo "[INFO] Session already exists: $name"
    echo "Attach with: tmux attach -t $name"
    return 0
  fi

  tmux new-session -d -s "$name" -n planner  "cd '$ROOT_DIR' && hermes -p planner -w"
  tmux new-window  -t "$name" -n builder   "cd '$ROOT_DIR' && hermes -p builder -w"
  tmux new-window  -t "$name" -n reviewer  "cd '$ROOT_DIR' && hermes -p reviewer -w"

  echo "[OK] Started tmux session: $name (profile isolated)"
  echo "     windows: planner(planner) | builder(builder) | reviewer(reviewer)"
  echo "Attach: tmux attach -t $name"
}

attach_session() {
  local name="$1"
  tmux attach -t "$name"
}

stop_session() {
  local name="$1"
  if tmux has-session -t "$name" 2>/dev/null; then
    tmux kill-session -t "$name"
    echo "[OK] Stopped session: $name"
  else
    echo "[INFO] Session not found: $name"
  fi
}

list_sessions() {
  tmux ls || true
}

main() {
  require_cmd tmux
  require_cmd hermes

  local action="${1:-}"
  local name="${2:-$SESSION_NAME}"

  case "$action" in
    start)
      start_plain "$name"
      ;;
    start-profiles)
      start_profiles "$name"
      ;;
    attach)
      attach_session "$name"
      ;;
    list)
      list_sessions
      ;;
    stop)
      stop_session "$name"
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "[ERROR] Unknown action: $action" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
