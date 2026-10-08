#!/usr/bin/env bash
set -euo pipefail

task_id=""
until_checkpoint=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id) task_id="$2"; shift 2 ;;
    --until-checkpoint) until_checkpoint=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
: "${OPENHANDS_BIN:?set OPENHANDS_BIN to the pinned OpenHands headless entrypoint}"
: "${OPENHANDS_CONFIG:?set OPENHANDS_CONFIG to the pinned config}"
: "${OPENHANDS_VLLM_BASE_URL:?set OPENHANDS_VLLM_BASE_URL to the Slurm model endpoint}"
: "${OPENHANDS_ACTION_LOG:?set OPENHANDS_ACTION_LOG to a run-local JSON action log}"
[[ -n "$task_id" ]] || { echo "--task-id is required" >&2; exit 2; }
[[ "$until_checkpoint" == 1 ]] || { echo "pilot requires an explicit until-checkpoint boundary" >&2; exit 2; }
mkdir -p "$(dirname "$OPENHANDS_ACTION_LOG")"
exec "$OPENHANDS_BIN" \
  --config "$OPENHANDS_CONFIG" \
  --task-id "$task_id" \
  --model-base-url "$OPENHANDS_VLLM_BASE_URL" \
  --checkpoint-boundary tool-idle \
  --action-log "$OPENHANDS_ACTION_LOG" \
  --real-guest-only
