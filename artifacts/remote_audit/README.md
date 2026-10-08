# Remote environment audit (read-only)

Audit date: 2026-10-08 (Asia/Shanghai), user `yishi`.

This directory records the read-only SSH/Slurm/GPU/Firecracker/OpenHands/vLLM
checks requested for Stage 1. Passwords and private credentials are deliberately
not recorded. The command transcript was collected through the configured path
`factlab-cf -> mantis -> infinite-frontier`.

## Connection findings

* Local sandboxed SSH initially failed with `ssh: Could not resolve hostname
  factlab-cf`; the same configured command succeeded only after the approved
  external SSH escalation. This is a local sandbox/network restriction, not a
  remote host failure.
* `ssh -G factlab-cf` resolved the local alias to user `codexsandboxoffline`,
  host `factlab-cf`, port 22. The authenticated prompt identified the gateway
  as `ssh.fact-lab.work/mantis`; the session reported `hostname=mantis`,
  `whoami=yishi`, `pwd=/fact_home/yishi`.
* From that authenticated mantis session, `ssh infinite-frontier` succeeded and
  landed on `hostname=infinite-frontier`, `whoami=yishi`, with the same home.
* The exact first-hop and nested-hop commands, exit statuses, and raw error are
  in `ssh_transcript.txt`.

## High-level result

* The requested home path exists and is accessible on both hosts.
* Slurm is reachable (`ClusterName=fact_cluster`, controller hosts
  `deep-space,quantum`). AI has H20 nodes (`gpu:nvidia_h20:8`); dev has L20
  nodes (`gpu:nvidia_l20:4`). At audit time all AI nodes were allocated in the
  node-state view; do not infer future availability from this snapshot.
* `infinite-frontier` is a live L20 compute node with four L20 GPUs visible to
  the shell. `nvidia-smi` worked; driver 610.43.02, CUDA UMD 13.3, 46,068 MiB
  per GPU. `nvcc` is not installed.
* `/dev/kvm` is present and world-readable/writable (`0666`) on both hosts and
  `kvm_intel`/`kvm` are loaded.
* Firecracker is not on `PATH`, but the old-project binary exists and reports
  `Firecracker v1.17.0`:
  `/fact_home/yishi/agent-checkpoint/firecracker-test/release-v1.17.0-x86_64/firecracker-v1.17.0-x86_64`.
  The Stage 1 project must import/copy this binary if it is trusted; it must not
  depend on the old project at runtime.
* `/fact_home/yishi/.conda/envs/agent-checkpoint` contains OpenHands SDK
  distributions 1.34.0 (`openhands-sdk`, `openhands-agent-server`,
  `openhands-tools`) and `openhands-ai` 1.11.0. `openhands`, `openhands.sdk`,
  and `openhands.tools` import successfully there.
* `/fact_home/yishi/.conda/envs/vllm-agent-clean` contains vLLM 0.8.3, Torch
  2.6.0, Transformers 4.51.3, NumPy 2.1.3. System Python and the e2b-compat
  environment do not contain vLLM/OpenHands.
* Existing pilot vLLM jobs are infrastructure failures, not semantic results:
  job 1696201 (H20, `blue-space`) exited 137; retry notes report the fixed Qwen
  model + vLLM 0.8.3 failing during Qwen3 MoE warm-up (`TorchDynamo` and then
  `attention_instances is None`). See `pilot_vllm_artifacts.txt`.

## Files

* `ssh_transcript.txt` — hop commands, raw errors, host identity and path checks.
* `slurm_transcript.txt` — `sinfo`, `squeue`, `scontrol`, node/GPU inventory.
* `runtime_transcript.txt` — nvidia/KVM/Firecracker/Python/package checks.
* `pilot_vllm_artifacts.txt` — read-only copy of the existing pilot manifest and
  retry rationale, including exit codes and failure classification.
* `audit_manifest.json` — machine-readable facts and evidence paths.

The transcript includes terminal-width wrapping removed where possible; command
labels and exit codes are retained. No remote files were changed by this audit.
