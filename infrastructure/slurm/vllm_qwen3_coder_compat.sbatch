#!/usr/bin/env bash
# Bounded, isolated Qwen3-Coder/vLLM compatibility gate.
# This is an engineering gate only; it never creates formal semantic samples.
#SBATCH --job-name=stage1-qwen3-compat
#SBATCH --partition=ai
#SBATCH --gres=gpu:nvidia_h20:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=160G
#SBATCH --time=01:30:00
#SBATCH --signal=B:TERM@120
#SBATCH --output=/scratch/yishi/stage1-slurm-logs/stage1-qwen3-compat-%j.out
#SBATCH --error=/scratch/yishi/stage1-slurm-logs/stage1-qwen3-compat-%j.err

set -Eeuo pipefail

ROOT=/fact_home/yishi/agent-checkpoint-stage1
SCRATCH_ROOT=${STAGE1_SCRATCH_ROOT:-/scratch/yishi/agent-checkpoint-stage1}
FACT_DATA_ROOT=${STAGE1_FACT_DATA_ROOT:-/fact_data/yishi/agent-checkpoint-stage1}
ENV=${STAGE1_VLLM_ENV:-/scratch/yishi/stage1-vllm-py39}
PROBES=${STAGE1_PROBE_DIR:-$ROOT/infrastructure/slurm}
PUBLISHER=${STAGE1_PUBLISHER:-$ROOT/infrastructure/storage/publish_evidence.py}
OPENHANDS_PY=${STAGE1_OPENHANDS_PY:-/fact_home/yishi/.conda/envs/agent-checkpoint/bin/python}
MODEL=${STAGE1_MODEL_PATH:-/scratch/yishi/stage1-model/Qwen3-Coder-30B-A3B-Instruct}
MODEL_NAME=Qwen/Qwen3-Coder-30B-A3B-Instruct
PORT=$((20000 + SLURM_JOB_ID % 10000))
BASE_URL="http://$SLURMD_NODENAME:$PORT/v1"
RUN_DIR="$SCRATCH_ROOT/runs/pilot/vllm/qwen3-compat-$SLURM_JOB_ID"
CACHE_DIR="$SCRATCH_ROOT/cache/qwen3-compat-$SLURM_JOB_ID"
mkdir -p "$RUN_DIR" "$CACHE_DIR" /scratch/yishi/stage1-slurm-logs
export HF_HOME="$CACHE_DIR/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export TRANSFORMERS_CACHE="$HF_HOME/transformers"
export HF_HUB_OFFLINE=1
export XDG_CACHE_HOME="$CACHE_DIR/xdg"
export PIP_CACHE_DIR="$CACHE_DIR/pip"
export CONDA_PKGS_DIRS="$CACHE_DIR/conda-pkgs"
export TMPDIR="$CACHE_DIR/tmp"
export TORCH_HOME="$CACHE_DIR/torch"
export TRITON_CACHE_DIR="$CACHE_DIR/triton"
export VLLM_CACHE_ROOT="$CACHE_DIR/vllm"
export TORCH_EXTENSIONS_DIR="$CACHE_DIR/torch-extensions"
export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR/torchinductor"
export CUDA_CACHE_PATH="$CACHE_DIR/cuda"
export PYTHONPYCACHEPREFIX="$CACHE_DIR/pycache"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$HF_HOME" "$HF_HUB_CACHE" "$TRANSFORMERS_CACHE" "$XDG_CACHE_HOME" "$PIP_CACHE_DIR" "$CONDA_PKGS_DIRS" "$TMPDIR" "$TORCH_HOME" "$TRITON_CACHE_DIR" "$VLLM_CACHE_ROOT" "$TORCH_EXTENSIONS_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$CUDA_CACHE_PATH" "$PYTHONPYCACHEPREFIX"
VLLM_LOG="$RUN_DIR/vllm.log"
PROBE_JSON="$RUN_DIR/qwen3_compat_probe.json"
OPENHANDS_JSON="$RUN_DIR/openhands_endpoint_probe.json"
MANIFEST="$RUN_DIR/environment_manifest.json"
STATUS=INVALID_INFRA
VLLM_PID=""
SIGNAL_NAME=""

record_stage() {
  local name=$1 code=$2 detail=${3:-}
  /usr/bin/python3 - "$RUN_DIR/stage_results.jsonl" "$name" "$code" "$detail" <<'PY'
import json, sys, time
out, name, code, detail = sys.argv[1:]
with open(out, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"stage": name, "exit_code": int(code), "detail": detail, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, sort_keys=True) + "\n")
PY
}

on_signal() { SIGNAL_NAME=$1; record_stage signal 143 "$1"; exit 143; }
trap 'on_signal TERM' TERM
trap 'on_signal USR1' USR1

finish() {
  local code=$?
  set +e
  trap - EXIT TERM USR1
  if [[ -n "$VLLM_PID" ]] && kill -0 "$VLLM_PID" 2>/dev/null; then
    kill -TERM -- "-$VLLM_PID" 2>/dev/null || kill -TERM "$VLLM_PID" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$VLLM_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL -- "-$VLLM_PID" 2>/dev/null || kill -KILL "$VLLM_PID" 2>/dev/null || true
    wait "$VLLM_PID" 2>/dev/null || true
  fi
  /usr/bin/python3 - "$MANIFEST" "$STATUS" "$code" "$BASE_URL" "$RUN_DIR" "$SIGNAL_NAME" <<'PY'
import json, sys, time
path, status, code, endpoint, run_dir, signal_name = sys.argv[1:]
try:
    data = json.loads(open(path, encoding="utf-8").read())
except Exception:
    data = {}
data.update({"status": status if int(code) == 0 else "INVALID_INFRA", "exit_code": int(code), "signal": signal_name or None, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "endpoint": endpoint, "run_dir": run_dir})
temporary = path + ".tmp"
open(temporary, "w", encoding="utf-8").write(json.dumps(data, indent=2, sort_keys=True) + "\n")
import os
  os.replace(temporary, path)
PY
  sacct -j "$SLURM_JOB_ID" --format=JobID,Partition,State,Elapsed,ExitCode,NodeList,Reason -P > "$RUN_DIR/sacct_final.txt" 2>&1 || true
  if [[ -f "$PUBLISHER" ]]; then
    /usr/bin/python3 "$PUBLISHER" --source "$RUN_DIR" --fact-data-root "$FACT_DATA_ROOT" --relative-destination "runs/pilot/vllm/qwen3-compat-$SLURM_JOB_ID" --job-id "$SLURM_JOB_ID" --artifact-id "qwen3-compat-$SLURM_JOB_ID" --regenerable --rebuild-step "re-run the locked Slurm compatibility script" > "$CACHE_DIR/publish_receipt.stdout" 2> "$CACHE_DIR/publish_receipt.stderr"
    local publish_code=$?
    cp "$CACHE_DIR/publish_receipt.stdout" "$RUN_DIR/publish_receipt.stdout" 2>/dev/null || true
    cp "$CACHE_DIR/publish_receipt.stderr" "$RUN_DIR/publish_receipt.stderr" 2>/dev/null || true
    record_stage fact_data_publish "$publish_code" "$FACT_DATA_ROOT/runs/pilot/vllm/qwen3-compat-$SLURM_JOB_ID"
    if [[ "$publish_code" == 0 ]]; then
      /usr/bin/python3 - "$CACHE_DIR/persistence_status.json" "$SLURM_JOB_ID" "$STATUS" "$FACT_DATA_ROOT/runs/pilot/vllm/qwen3-compat-$SLURM_JOB_ID" <<'PY2'
import json, sys, time
out, job_id, status, evidence = sys.argv[1:]
with open(out, "w", encoding="utf-8") as handle:
    json.dump({"job_id": job_id, "status": status, "persistence_status": "VERIFIED", "authoritative_evidence": evidence, "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY2
      /usr/bin/python3 "$PUBLISHER" --source "$CACHE_DIR/persistence_status.json" --fact-data-root "$FACT_DATA_ROOT" --relative-destination "runs/pilot/vllm/qwen3-compat-$SLURM_JOB_ID-status" --job-id "$SLURM_JOB_ID" --artifact-id "qwen3-compat-$SLURM_JOB_ID-status" --regenerable --rebuild-step "re-run the compatibility gate and persistence publisher" > "$CACHE_DIR/status_publish.stdout" 2> "$CACHE_DIR/status_publish.stderr"
      local status_publish_code=$?
      [[ "$status_publish_code" == 0 ]] || code=1
      record_stage fact_data_status_publish "$status_publish_code" "$FACT_DATA_ROOT/runs/pilot/vllm/qwen3-compat-$SLURM_JOB_ID-status"
    else
      code=1
    fi
  else
    echo "publisher unavailable; raw evidence remains in scratch only" > "$RUN_DIR/publish_failure.txt"
    code=1
  fi
  exit "$code"
}
trap finish EXIT

date -Is | tee "$RUN_DIR/start.txt"
hostname | tee "$RUN_DIR/hostname.txt"
scontrol show job "$SLURM_JOB_ID" > "$RUN_DIR/scontrol_job.txt" 2>&1 || true
sacct -j "$SLURM_JOB_ID" --format=JobID,Partition,State,Elapsed,ExitCode,NodeList,Reason -P > "$RUN_DIR/sacct_start.txt" 2>&1 || true
nvidia-smi > "$RUN_DIR/nvidia-smi.txt" 2>&1
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv > "$RUN_DIR/nvidia-query.txt" 2>&1
env | sort | grep -E '^(HF_HOME|HF_HUB_CACHE|TRANSFORMERS_CACHE|HF_HUB_OFFLINE|XDG_CACHE_HOME|PIP_CACHE_DIR|CONDA_PKGS_DIRS|TMPDIR|TORCH_HOME|TRITON_CACHE_DIR|VLLM_CACHE_ROOT|TORCH_EXTENSIONS_DIR|TORCHINDUCTOR_CACHE_DIR|CUDA_CACHE_PATH|PYTHONPYCACHEPREFIX)=' > "$RUN_DIR/storage_paths.env"
realpath "$ENV" > "$RUN_DIR/env.realpath" 2>&1 || true
realpath "$MODEL" > "$RUN_DIR/model.realpath" 2>&1 || true
findmnt -T "$CACHE_DIR" -o TARGET,SOURCE,FSTYPE,OPTIONS > "$RUN_DIR/cache.mount" 2>&1 || true
findmnt -T "$MODEL" -o TARGET,SOURCE,FSTYPE,OPTIONS > "$RUN_DIR/model.mount" 2>&1 || true
"$ENV/bin/python" -m pip cache dir > "$RUN_DIR/pip-cache-dir.txt" 2>&1 || true
du -sh "$CACHE_DIR" "$RUN_DIR" > "$RUN_DIR/storage_usage.txt" 2>&1 || true
record_stage storage_paths 0

if [[ ! -x "$ENV/bin/python" || ! -x "$ENV/bin/vllm" ]]; then
  echo "candidate environment is absent or incomplete" > "$RUN_DIR/failure.txt"
  record_stage preflight 1 "candidate environment absent or incomplete"
  exit 1
fi
if [[ ! -f "$ENV/.stage1-ready.json" ]]; then
  echo "candidate environment lacks immutable READY marker: $ENV/.stage1-ready.json" > "$RUN_DIR/failure.txt"
  record_stage preflight 1 "candidate environment lacks READY marker"
  exit 1
fi
if [[ ! -d "$MODEL" ]]; then
  echo "fixed model directory is absent: $MODEL" > "$RUN_DIR/failure.txt"
  record_stage preflight 1 "fixed model directory absent"
  exit 1
fi
if [[ ! -f "$MODEL/config.json" || ! -f "$MODEL/qwen3coder_tool_parser.py" ]]; then
  echo "fixed model config or parser is absent: $MODEL" > "$RUN_DIR/failure.txt"
  record_stage preflight 1 "model config/parser absent"
  exit 1
fi
if [[ "$MODEL" == /data || "$MODEL" == /data/* ]]; then
  echo "forbidden /data model path" > "$RUN_DIR/failure.txt"
  record_stage preflight 1 "forbidden /data model path"
  exit 1
fi

"$ENV/bin/python" -m pip freeze > "$RUN_DIR/pip-freeze.txt"
"$ENV/bin/python" -m pip check > "$RUN_DIR/pip-check.txt" 2>&1 || { record_stage pip_check 1; exit 1; }
"$ENV/bin/python" -m pip show vllm torch transformers openai > "$RUN_DIR/pip-show.txt" 2>&1 || true
"$ENV/bin/python" - "$MANIFEST" "$ENV" "$MODEL" "$MODEL_NAME" "$PORT" <<'PY'
import hashlib, json, os, subprocess, sys, time
out, env, model, model_name, port = sys.argv[1:]
def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
def run(cmd):
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:
        return f"ERROR: {exc}"
data = {
    "run_id": os.environ.get("SLURM_JOB_ID"),
    "run_kind": "compatibility_gate",
    "host": os.uname().nodename,
    "slurm_node": os.environ.get("SLURMD_NODENAME"),
    "partition": os.environ.get("SLURM_JOB_PARTITION"),
    "gpu_type": "nvidia_h20",
    "gpu_count": 1,
    "candidate_env": env,
    "python": run([env + "/bin/python", "--version"]),
    "model_path": model,
    "model_name": model_name,
    "model_revision": "UNRESOLVED_LOCAL_SOURCE",
    "model_config_sha256": sha(model + "/config.json"),
    "model_parser_sha256": sha(model + "/qwen3coder_tool_parser.py"),
    "vllm_command": [env + "/bin/vllm", "serve", model, "--host", "0.0.0.0", "--port", port, "--served-model-name", model_name, "--tensor-parallel-size", "1", "--max-model-len", "32768", "--gpu-memory-utilization", "0.90", "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder", "--seed", "20261008", "--trust-remote-code"],
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
}
open(out, "w", encoding="utf-8").write(json.dumps(data, indent=2, sort_keys=True))
PY
record_stage preflight 0

setsid "$ENV/bin/vllm" serve "$MODEL" --host 0.0.0.0 --port "$PORT" --served-model-name "$MODEL_NAME" \
  --tensor-parallel-size 1 --max-model-len 32768 --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --seed 20261008 --trust-remote-code \
  > "$VLLM_LOG" 2>&1 &
VLLM_PID=$!
echo "$VLLM_PID" > "$RUN_DIR/vllm.pid"

ready=0
for _ in $(seq 1 180); do
  if curl --fail --silent --show-error --max-time 3 "http://127.0.0.1:$PORT/health" > "$RUN_DIR/health.response" 2> "$RUN_DIR/health.error"; then
    ready=1
    break
  fi
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "vLLM exited before warm-up" > "$RUN_DIR/failure.txt"
    record_stage server_ready 1 "vLLM exited before warm-up"
    exit 1
  fi
  sleep 5
done
if [[ "$ready" != 1 ]]; then
  echo "vLLM health timeout after 900 seconds" > "$RUN_DIR/failure.txt"
  record_stage server_ready 1 "health timeout"
  exit 1
fi
record_stage server_ready 0

set +e
timeout 300 "$ENV/bin/python" "$PROBES/qwen3_compat_probe.py" \
  --base-url "$BASE_URL" --model "$MODEL_NAME" --model-parser "$MODEL/qwen3coder_tool_parser.py" \
  --output "$PROBE_JSON" > "$RUN_DIR/qwen3_compat_probe.stdout" 2>&1
probe_code=$?
timeout 300 "$OPENHANDS_PY" \
  "$PROBES/openhands_endpoint_probe.py" \
  --base-url "$BASE_URL" --model "$MODEL_NAME" --output "$OPENHANDS_JSON" \
  > "$RUN_DIR/openhands_endpoint_probe.stdout" 2>&1
openhands_code=$?
set -e
if [[ "$probe_code" != 0 || "$openhands_code" != 0 ]]; then
  echo "qwen3 probe exit=$probe_code; OpenHands probe exit=$openhands_code" > "$RUN_DIR/failure.txt"
  record_stage probes 1 "qwen3=$probe_code openhands=$openhands_code"
  exit 1
fi
record_stage probes 0
STATUS=PASS
exit 0
