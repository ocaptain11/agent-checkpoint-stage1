#!/usr/bin/env bash
# Distinct bounded bootstrap attempt after resolver timeout 1698012.
# Single writer; all env/cache/temp paths are job-unique SCRATCH paths.
# A READY marker is written only after pip check succeeds.
#SBATCH --job-name=stage1-vllm-direct0101
#SBATCH --partition=dev
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=04:00:00
#SBATCH --output=/scratch/yishi/stage1-vllm-direct-logs/slurm-%j.out
#SBATCH --error=/scratch/yishi/stage1-vllm-direct-logs/slurm-%j.err

set -Eeuo pipefail
umask 077
ENV=${STAGE1_VLLM_ENV:-/scratch/yishi/stage1-vllm-py39-direct0101}
CACHE=/scratch/yishi/stage1-vllm-direct-cache-${SLURM_JOB_ID:?}
TMP=/scratch/yishi/stage1-vllm-direct-tmp-${SLURM_JOB_ID:?}
LOGROOT=/scratch/yishi/stage1-vllm-direct-logs
mkdir -p "$CACHE" "$TMP" "$LOGROOT"
export HF_HOME="$CACHE/huggingface" HF_HUB_CACHE="$CACHE/huggingface/hub" TRANSFORMERS_CACHE="$CACHE/huggingface/transformers" XDG_CACHE_HOME="$CACHE/xdg" PIP_CACHE_DIR="$CACHE/pip" CONDA_PKGS_DIRS="$CACHE/conda-pkgs" TMPDIR="$TMP" TORCH_HOME="$CACHE/torch" TRITON_CACHE_DIR="$CACHE/triton" VLLM_CACHE_ROOT="$CACHE/vllm" TORCH_EXTENSIONS_DIR="$CACHE/torch-extensions" TORCHINDUCTOR_CACHE_DIR="$CACHE/torchinductor" CUDA_CACHE_PATH="$CACHE/cuda" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$HF_HOME" "$HF_HUB_CACHE" "$TRANSFORMERS_CACHE" "$XDG_CACHE_HOME" "$PIP_CACHE_DIR" "$CONDA_PKGS_DIRS" "$TMPDIR" "$TORCH_HOME" "$TRITON_CACHE_DIR" "$VLLM_CACHE_ROOT" "$TORCH_EXTENSIONS_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$CUDA_CACHE_PATH"

python3.9 -m venv "$ENV"
PY="$ENV/bin/python"
"$PY" -m pip install --upgrade --progress-bar off pip setuptools wheel
"$PY" -m pip install --no-cache-dir --only-binary=:all: --progress-bar off --timeout 120 --retries 2 --no-deps torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1
"$PY" -m pip install --no-cache-dir --only-binary=:all: --progress-bar off --timeout 120 --retries 2 --no-deps vllm==0.10.1
"$PY" - <<'PY'
from importlib.metadata import requires
from pathlib import Path
import os
req = [x for x in (requires("vllm") or []) if ";" not in x or "extra ==" not in x]
Path("/scratch/yishi/vllm-0101-requires-" + os.environ["SLURM_JOB_ID"] + ".txt").write_text("\n".join(req) + "\n")
PY
"$PY" -m pip install --no-cache-dir --only-binary=:all: --prefer-binary --progress-bar off --timeout 120 --retries 2 -r "/scratch/yishi/vllm-0101-requires-$SLURM_JOB_ID.txt"
"$PY" -m pip check
"$PY" - <<'PY'
import hashlib, json, os, sys, time
from pathlib import Path
prefix = Path("/scratch/yishi/stage1-vllm-py39-direct0101")
freeze = os.popen(str(prefix / "bin/python") + " -m pip freeze").read()
marker = {"env": str(prefix), "python": sys.version, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pip_freeze_sha256": hashlib.sha256(freeze.encode()).hexdigest(), "install_job": os.environ.get("SLURM_JOB_ID"), "status": "READY_FOR_COMPATIBILITY_GATE"}
(prefix / ".stage1-ready.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
PY
"$PY" -m pip freeze > "$LOGROOT/freeze-$SLURM_JOB_ID.txt"
"$PY" -m pip check > "$LOGROOT/pip-check-$SLURM_JOB_ID.txt"
echo STAGE1_VLLM_DIRECT_READY
