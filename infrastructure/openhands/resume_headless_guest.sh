#!/usr/bin/env bash
set -euo pipefail

prefix=""
socket=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) prefix="$2"; shift 2 ;;
    --socket) socket="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
: "${OPENHANDS_BIN:?set OPENHANDS_BIN}"
: "${OPENHANDS_CONFIG:?set OPENHANDS_CONFIG}"
: "${OPENHANDS_VLLM_BASE_URL:?set OPENHANDS_VLLM_BASE_URL}"
: "${OPENHANDS_ACTION_LOG:?set OPENHANDS_ACTION_LOG}"
[[ -f "$prefix" && -n "$socket" ]] || { echo "--prefix and --socket are required" >&2; exit 2; }
mkdir -p "$(dirname "$OPENHANDS_ACTION_LOG")"
exec "$OPENHANDS_BIN" \
  --config "$OPENHANDS_CONFIG" \
  --restore-prefix "$prefix" \
  --firecracker-socket "$socket" \
  --model-base-url "$OPENHANDS_VLLM_BASE_URL" \
  --action-log "$OPENHANDS_ACTION_LOG" \
  --real-guest-only \
  --autonomous-continuation
