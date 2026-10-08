#!/usr/bin/env bash
set -euo pipefail

# Start a real Firecracker VMM. All image paths are supplied by the caller;
# this script never creates a synthetic Guest or falls back to a host workspace.
socket=""
pid_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --socket) socket="$2"; shift 2 ;;
    --pid-file) pid_file="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
: "${FIRECRACKER_BIN:?set FIRECRACKER_BIN to the verified Firecracker binary}"
: "${KERNEL_IMAGE:?set KERNEL_IMAGE to the immutable Guest kernel}"
: "${ROOTFS_IMAGE:?set ROOTFS_IMAGE to the immutable Guest rootfs}"
: "${GUEST_DISK_IMAGE:?set GUEST_DISK_IMAGE to the per-run writable disk copy}"
: "${BOOT_ARGS:?set BOOT_ARGS to the fixed Guest boot arguments}"
[[ -n "$socket" ]] || { echo "--socket is required" >&2; exit 2; }
[[ -n "$pid_file" ]] || pid_file="${socket}.pid"
mkdir -p "$(dirname "$socket")" "$(dirname "$pid_file")"
[[ -e /dev/kvm ]] || { echo "/dev/kvm is unavailable" >&2; exit 1; }

exec 9>"$pid_file.lock"
flock -n 9 || { echo "pid lock is already held: $pid_file" >&2; exit 1; }
if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file")"
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "a VMM is already running with pid $old_pid" >&2
    exit 1
  fi
fi

"$FIRECRACKER_BIN" --api-sock "$socket" \
  --config-file <(cat <<JSON
{
  "boot-source": {"kernel_image_path": "${KERNEL_IMAGE}", "boot_args": "${BOOT_ARGS}"},
  "drives": [{"drive_id": "rootfs", "path_on_host": "${ROOTFS_IMAGE}", "is_root_device": true, "is_read_only": true}, {"drive_id": "guest-disk", "path_on_host": "${GUEST_DISK_IMAGE}", "is_root_device": false, "is_read_only": false}]
}
JSON
) &
pid=$!
echo "$pid" > "$pid_file"
echo "${pid}"
wait "$pid"
