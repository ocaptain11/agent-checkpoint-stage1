#!/usr/bin/env bash
set -euo pipefail

checkpoint_dir=""
socket=""
new_pid_file=""
evidence_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --checkpoint-dir) checkpoint_dir="$2"; shift 2 ;;
    --socket) socket="$2"; shift 2 ;;
    --new-pid-file) new_pid_file="$2"; shift 2 ;;
    --evidence-file) evidence_file="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
: "${FIRECRACKER_BIN:?set FIRECRACKER_BIN}"
: "${FIRECRACKER_RESTORE_CONFIG:?set FIRECRACKER_RESTORE_CONFIG to the verified restore VM config}"
: "${FC_CURL:?set FC_CURL}"
: "${HOST_PREFIX_RESTORE_CMD:?set command that restores the recorded Host Agent prefix}"
: "${TOOL_RECONNECT_CHECK_CMD:?set command that verifies a fresh Host-Guest tool connection}"
[[ -n "$checkpoint_dir" && -n "$socket" && -n "$new_pid_file" && -n "$evidence_file" ]] || { echo "all restore arguments are required" >&2; exit 2; }
for artifact in memory.snap vmstate.snap disk.img; do
  [[ -f "$checkpoint_dir/$artifact" ]] || { echo "missing checkpoint artifact: $checkpoint_dir/$artifact" >&2; exit 1; }
done
mkdir -p "$(dirname "$socket")" "$(dirname "$new_pid_file")" "$(dirname "$evidence_file")"
"$FIRECRACKER_BIN" --api-sock "$socket" --config-file "$FIRECRACKER_RESTORE_CONFIG" >/dev/null 2>&1 &
pid=$!
echo "$pid" > "$new_pid_file"
for _ in $(seq 1 120); do
  [[ -S "$socket" || -e "$socket" ]] && break
  kill -0 "$pid" 2>/dev/null || { echo "restored VMM exited" >&2; exit 1; }
  sleep 0.25
done
[[ -S "$socket" || -e "$socket" ]] || { echo "restored API socket did not appear" >&2; exit 1; }
"$FC_CURL" --fail --silent --show-error --unix-socket "$socket" -X PUT http://localhost/snapshot/load \
  -H 'Content-Type: application/json' \
  -d "{\"snapshot_path\":\"$checkpoint_dir/vmstate.snap\",\"mem_backend\":{\"backend_type\":\"File\",\"backend_path\":\"$checkpoint_dir/memory.snap\"},\"enable_diff_snapshots\":false}"
bash -lc "$HOST_PREFIX_RESTORE_CMD"
bash -lc "$TOOL_RECONNECT_CHECK_CMD"
printf '%s\n' "{\"host_prefix_restored\":true,\"tool_reconnected\":true,\"new_vmm_pid\":${pid}}" > "$evidence_file"
