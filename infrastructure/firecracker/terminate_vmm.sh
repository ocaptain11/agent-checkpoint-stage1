#!/usr/bin/env bash
set -euo pipefail

pid_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pid-file) pid_file="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$pid_file" && -f "$pid_file" ]] || { echo "a valid --pid-file is required" >&2; exit 2; }
pid="$(cat "$pid_file")"
[[ "$pid" =~ ^[0-9]+$ ]] || { echo "invalid PID in $pid_file" >&2; exit 1; }
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  for _ in $(seq 1 100); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
  done
fi
if kill -0 "$pid" 2>/dev/null; then
  echo "VMM did not terminate: $pid" >&2
  exit 1
fi
printf '%s\n' "{\"terminated_pid\":${pid},\"terminated\":true}"
