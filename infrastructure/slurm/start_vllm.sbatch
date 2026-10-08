#!/usr/bin/env bash
#SBATCH --job-name=stage1-qwen30b-vllm
#SBATCH --partition=ai
#SBATCH --gres=gpu:nvidia_h20:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=02:00:00
#SBATCH --output=runs/pilot/slurm-vllm-%j.out
#SBATCH --error=runs/pilot/slurm-vllm-%j.err

set -euo pipefail

# Runs exceeding two hours require administrator approval; this template stays
# within that bound. Adjust GPU count only after inspecting current Slurm/GPU
# allocation and the pinned model's measured memory requirement.
: "${STAGE1_VLLM_ENV:?set STAGE1_VLLM_ENV to the pinned vLLM environment activate script}"
: "${QWEN_MODEL_PATH:?set QWEN_MODEL_PATH to Qwen/Qwen3-Coder-30B-A3B-Instruct weights}"
: "${QWEN_MODEL_REVISION:?set the immutable model weights revision}"
: "${VLLM_TOOL_CALL_PARSER:?set the validated tool-call parser}"
: "${VLLM_PORT:=8000}"
: "${VLLM_TENSOR_PARALLEL_SIZE:=2}"

source "$STAGE1_VLLM_ENV"
mkdir -p runs/pilot
manifest="runs/pilot/vllm-${SLURM_JOB_ID}.manifest.json"
nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total --format=csv,noheader > "runs/pilot/vllm-${SLURM_JOB_ID}.gpu.csv"
python - <<'PY' > "$manifest"
import json, os, socket, subprocess, time
def out(command):
    return subprocess.check_output(command, text=True).strip()
print(json.dumps({
    "job_id": os.environ["SLURM_JOB_ID"],
    "partition": os.environ.get("SLURM_JOB_PARTITION"),
    "node": socket.gethostname(),
    "model_path": os.environ["QWEN_MODEL_PATH"],
    "model_revision": os.environ["QWEN_MODEL_REVISION"],
    "vllm_version": out(["python", "-c", "import vllm; print(vllm.__version__)"]),
    "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    "started_at_epoch": time.time(),
}, sort_keys=True))
PY

node="$(hostname -f)"
printf 'http://%s:%s/v1\n' "$node" "$VLLM_PORT" > "runs/pilot/vllm-${SLURM_JOB_ID}.endpoint"
exec vllm serve "$QWEN_MODEL_PATH" \
  --revision "$QWEN_MODEL_REVISION" \
  --served-model-name Qwen/Qwen3-Coder-30B-A3B-Instruct \
  --host 0.0.0.0 \
  --port "$VLLM_PORT" \
  --tensor-parallel-size "$VLLM_TENSOR_PARALLEL_SIZE" \
  --tool-call-parser "$VLLM_TOOL_CALL_PARSER" \
  --enable-auto-tool-choice
