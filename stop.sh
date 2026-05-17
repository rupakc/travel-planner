#!/usr/bin/env bash
# stop.sh — Cleanly shut down the Travel Planner backend and frontend dev servers.
#
# Usage:
#   ./stop.sh            # stop both servers
#   ./stop.sh --backend  # backend only
#   ./stop.sh --frontend # frontend only
#   ./stop.sh --force    # SIGKILL immediately

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$ROOT/.pids"

BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"

BACKEND_PORT=8001
FRONTEND_PORT=5174
GRACEFUL_TIMEOUT=10

if [[ -t 1 ]]; then
  BOLD='\033[1m'; RESET='\033[0m'
  GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'
else
  BOLD=''; RESET=''; GREEN=''; YELLOW=''; RED=''; CYAN=''
fi

log()  { echo -e "${CYAN}[travel-planner]${RESET} $*"; }
ok()   { echo -e "${GREEN}[✓]${RESET} $*"; }
warn() { echo -e "${YELLOW}[!]${RESET} $*"; }
die()  { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }

STOP_BACKEND=true
STOP_FRONTEND=true
FORCE=false

for arg in "$@"; do
  case "$arg" in
    --backend)  STOP_FRONTEND=false ;;
    --frontend) STOP_BACKEND=false  ;;
    --force)    FORCE=true          ;;
    --help|-h)
      echo "Usage: $0 [--backend|--frontend] [--force]"
      exit 0
      ;;
    *) die "Unknown argument: $arg" ;;
  esac
done

stop_server() {
  local label="$1" pid_file="$2" port="$3"
  local pid=""

  if [[ -f "$pid_file" ]]; then
    pid=$(cat "$pid_file")
  fi

  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    local port_pid
    port_pid=$(lsof -ti tcp:"$port" 2>/dev/null | head -1 || true)
    if [[ -n "$port_pid" ]]; then
      warn "$label: PID file stale; found process $port_pid on port $port"
      pid="$port_pid"
    else
      warn "$label: not running (no PID file and port $port is free)"
      [[ -f "$pid_file" ]] && rm -f "$pid_file"
      return
    fi
  fi

  log "Stopping ${BOLD}$label${RESET} (PID $pid) …"

  if $FORCE; then
    kill -9 "$pid" 2>/dev/null || true
    ok "$label stopped (SIGKILL)"
  else
    kill -TERM "$pid" 2>/dev/null || true

    local elapsed=0
    while kill -0 "$pid" 2>/dev/null; do
      sleep 1
      (( elapsed++ )) || true
      if (( elapsed >= GRACEFUL_TIMEOUT )); then
        warn "$label did not exit within ${GRACEFUL_TIMEOUT}s — sending SIGKILL"
        kill -9 "$pid" 2>/dev/null || true
        break
      fi
    done

    if ! kill -0 "$pid" 2>/dev/null; then
      ok "$label stopped"
    else
      warn "$label may still be running; check manually: kill -9 $pid"
    fi
  fi

  local orphans
  orphans=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [[ -n "$orphans" ]]; then
    warn "Cleaning up orphaned process(es) on port $port: $orphans"
    echo "$orphans" | xargs kill -9 2>/dev/null || true
  fi

  [[ -f "$pid_file" ]] && rm -f "$pid_file"
}

echo ""
echo -e "${BOLD}  Travel Planner — stopping dev servers${RESET}"
echo "  ────────────────────────────────────"
echo ""

$STOP_BACKEND  && stop_server "Backend"  "$BACKEND_PID_FILE"  "$BACKEND_PORT"
$STOP_FRONTEND && stop_server "Frontend" "$FRONTEND_PID_FILE" "$FRONTEND_PORT"

echo ""

all_clear=true
if $STOP_BACKEND  && lsof -ti tcp:"$BACKEND_PORT"  &>/dev/null; then
  warn "Port $BACKEND_PORT is still in use"
  all_clear=false
fi
if $STOP_FRONTEND && lsof -ti tcp:"$FRONTEND_PORT" &>/dev/null; then
  warn "Port $FRONTEND_PORT is still in use"
  all_clear=false
fi

if $all_clear; then
  ok "All ports free — shutdown complete"
fi
echo ""
