# Stage 1 Cluster Storage Policy

This policy is a hard engineering constraint for every Stage 1 environment,
Slurm job, pilot run, and formal experiment. It does not relax any scientific
gate in `STAGE1_PROTOCOL.md`.

## Storage classes

| Class | Authoritative root | Allowed content | Prohibited content |
| --- | --- | --- | --- |
| `HOME` | `/fact_home/$USER/` | Git repositories, source, configs, lock files, scripts, small manifests, indexes, and reports | model weights, large Conda/venv prefixes, package/model caches, snapshots, large datasets, temporary downloads |
| `FACT_DATA` | `/fact_data/$USER/` | authoritative, retained research evidence: Firecracker snapshots and disk state, non-reconstructible mapping data, evaluator outputs, raw results/logs, failure records, and machine-readable manifests | disposable caches and sole copies that are still being written |
| `SCRATCH` | `/scratch/$USER/` | regenerable environments, model downloads, package caches, Torch/Triton/vLLM caches, temporary downloads, working snapshot copies, and intermediates | the only copy of research evidence or shared components that require reliable cross-node locking/transactions |

`/data` and similar node-local experimental SSD paths are forbidden. Existing
files, environments, models, and historical results are never deleted or
moved merely to make space. A quota problem is reported with the blocking
paths and requested capacity before any migration or cleanup is proposed.

## Required runtime layout

Each candidate environment gets a unique, single-writer directory below
scratch. Before installation or launch, set and record at least:

```sh
export STAGE1_SCRATCH=/scratch/$USER/agent-checkpoint-stage1
export HF_HOME=$STAGE1_SCRATCH/cache/huggingface
export HF_HUB_CACHE=$HF_HOME/hub
export XDG_CACHE_HOME=$STAGE1_SCRATCH/cache/xdg
export PIP_CACHE_DIR=$STAGE1_SCRATCH/cache/pip
export CONDA_PKGS_DIRS=$STAGE1_SCRATCH/cache/conda-pkgs
export TMPDIR=$STAGE1_SCRATCH/tmp
export TORCH_HOME=$STAGE1_SCRATCH/cache/torch
export TRITON_CACHE_DIR=$STAGE1_SCRATCH/cache/triton
export VLLM_CACHE_ROOT=$STAGE1_SCRATCH/cache/vllm
```

Setting variables is not proof that they took effect. Every job records
`sys.prefix`, installed package locations, model location/revision, relevant
environment variables, observed cache/temp paths, and a directory inventory.
Only one installation job may write a candidate environment. Runtime jobs
must treat a completed environment as immutable.

If a model or dependency cannot be fetched reproducibly, do not label it a
disposable cache. Record the retrieval problem and assess a verified retained
copy under `FACT_DATA`.

## Read-only audit before changes

Run the audit from a login or allocated node before planning storage changes:

```sh
python infrastructure/storage/storage_audit.py --pretty \
  > /fact_home/$USER/agent-checkpoint-stage1/reports/storage_audit.json
```

The script itself performs no writes; shell redirection is the caller's
explicit choice. It reports identity, mount information, permissions,
filesystem capacity, quota command results, and top-level byte usage. Use
`--skip-du` only when a bounded `du` cannot complete; record that omission.

Do not move pre-existing results based only on the audit. Migration needs an
explicit, reviewed source/destination plan.

## Evidence persistence protocol

Important evidence is never left only in scratch. After a run finishes:

1. close all writers and identify the exact immutable source tree;
2. inventory every source file with byte count and SHA-256;
3. copy into a unique `.staging` directory inside the target `FACT_DATA` root;
4. inventory the source again and the staged copy; all three manifests must
   match (detecting source changes during copy);
5. atomically rename the verified staged payload to its final path on the
   same filesystem;
6. re-hash the published tree and write a verification receipt; and
7. register the final path, hashes, size, provenance, regeneration status,
   job metadata, and failure state in the storage manifest.

Use:

```sh
python infrastructure/storage/publish_evidence.py \
  --source /scratch/$USER/agent-checkpoint-stage1/runs/pilot/RUN_ID \
  --fact-data-root /fact_data/$USER/agent-checkpoint-stage1 \
  --relative-destination runs/pilot/RUN_ID
```

The publisher never deletes its source and never overwrites a destination.
It rejects symlinks, path traversal, `/data`, concurrent writers for the same
destination, source mutation during copying, and hash/size differences. A
failed staging directory is retained with a failure record for audit; it may
only be cleaned later after resolving and validating its exact path.

Consumers must require `_storage_publish_receipt.json` with status
`VERIFIED`. A directory without that receipt is incomplete even if files are
visible.

## Required audit record

For every environment install, Slurm job, and formal experiment, record:

- actual install/cache/input/output paths, user, node, job ID, timestamps,
  exit code, and raw log path;
- exact environment, CUDA/PyTorch/Transformers/vLLM/model versions and config
  hashes;
- paths, sizes, and SHA-256 for important inputs and outputs;
- whether each item is regenerable and exact rebuild steps;
- persistence and verification status; and
- failure classification without relabelling `INVALID_INFRA` as a scientific
  negative.

Keep the small storage index and summaries in `HOME`. Keep authoritative raw
evidence in `FACT_DATA`. A scratch loss must be recoverable from source/config
or from verified authoritative evidence.
