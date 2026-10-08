#!/usr/bin/env bash
set -euo pipefail

socket=""
output_dir=""
disk_state="${GUEST_DISK_IMAGE:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --socket) socket="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    --disk-state) disk_state="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
: "${FC_CURL:?set FC_CURL to curl with Unix-socket support}"
[[ -n "$socket" && -n "$output_dir" && -n "$disk_state" ]] || { echo "--socket, --output-dir and --disk-state are required" >&2; exit 2; }
[[ -S "$socket" || -e "$socket" ]] || { echo "Firecracker API socket not found: $socket" >&2; exit 1; }
mkdir -p "$output_dir"
memory_snap="$output_dir/memory.snap"
vmstate_snap="$output_dir/vmstate.snap"
disk_copy="$output_dir/disk.img"

"$FC_CURL" --fail --silent --show-error --unix-socket "$socket" -X PUT http://localhost/snapshot/create \
  -H 'Content-Type: application/json' \
  -d "{\"snapshot_type\":\"Full\",\"snapshot_path\":\"${vmstate_snap}\",\"mem_file_path\":\"${memory_snap}\",\"diff_snapshots\":false}"
cp --reflink=auto --sparse=always -- "$disk_state" "$disk_copy"
sha256sum "$memory_snap" "$vmstate_snap" "$disk_copy" > "$output_dir/artifact.sha256"
printf '%s\n' '{"full_snapshot":true,"snapshot_type":"Full","disk_state":"disk.img"}' > "$output_dir/snapshot_evidence.json"
