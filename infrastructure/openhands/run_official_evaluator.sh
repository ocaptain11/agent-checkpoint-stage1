#!/usr/bin/env bash
set -euo pipefail

task_id=""
agent_output=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id) task_id="$2"; shift 2 ;;
    --agent-output) agent_output="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
: "${SWE_EVALUATOR_BIN:?set SWE_EVALUATOR_BIN to the pinned official evaluator}"
: "${SWE_EVALUATOR_RESULT_FILE:?set SWE_EVALUATOR_RESULT_FILE to a run-local JSON result path}"
[[ -n "$task_id" && -n "$agent_output" ]] || { echo "--task-id and --agent-output are required" >&2; exit 2; }
[[ -d "$agent_output" ]] || { echo "Agent output directory is missing: $agent_output" >&2; exit 1; }
mkdir -p "$(dirname "$SWE_EVALUATOR_RESULT_FILE")"
# The evaluator receives Agent output only. No gold patch is copied into the
# Guest or exposed as an evaluator input.
exec "$SWE_EVALUATOR_BIN" \
  --task-id "$task_id" \
  --agent-output "$agent_output" \
  --result-json "$SWE_EVALUATOR_RESULT_FILE" \
  --no-gold-patch-injection
