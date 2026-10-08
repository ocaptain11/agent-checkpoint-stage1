# Semantic Agent Checkpointing — Stage 1

This directory is an independent project for the **Real Agent Sandbox Oracle
Feasibility & Opportunity Study**. It is intentionally separate from the
legacy `agent-checkpoint` directory. The scaffold was initialized on
2026-10-08 (Asia/Shanghai) and contains no pilot or formal scientific result
yet.

## Location and isolation

The intended cluster location is `/fact_home/yishi/agent-checkpoint-stage1/`.
In this managed Windows workspace the old project is exposed as
`C:\Users\26793\agent-checkpoint`; its parent is not writable. Therefore the
local mirror is `C:\Users\26793\agent-checkpoint\agent-checkpoint-stage1`.
This mapping is recorded in `imports/import_manifest.json` and must be
reconciled before any remote run is launched.

The legacy project is read-only for this study. No symlinks, `PYTHONPATH`
entries, shared writable caches, old result files, replay-history oracle data,
synthetic workload conclusions, or historical coverage numbers may be used at
runtime. Every future import must be explicitly recorded with source,
revision, SHA-256, purpose, and dependency information.

## Scientific objective

Stage 1 measures, on real OpenHands-with-Firecracker workloads, the prevalence
of semantic state and the **minimum observed safe fidelity** required for a
live agent to continue. The study must preserve negative and inconclusive
results. A successful restore, a single `resolved=true`, or an unexercised
object is not evidence of semantic safety.

The four primary outputs are:

1. state prevalence and lifetime by checkpoint timing;
2. observed fidelity preservation (EXACT, FP16, INT8, INT4, RECONSTRUCT,
   DROP) with explicit UNKNOWN/UNTESTED mass;
3. heterogeneity of fidelity sensitivity and task-level correctness; and
4. additional reduction beyond a measured best lossless baseline, including
   auxiliary metadata and separate RAM-reclamation accounting.

## Fixed experimental contract

The protocol fixes OpenHands SDK at a recorded commit, Qwen/Qwen3-Coder-30B-
A3B-Instruct served by vLLM, the tool-call parser and generation settings,
Firecracker version/kernel/rootfs/guest dependencies, and the benchmark task
IDs before formal collection. The Agent loop and checkpoint coordinator run
on the host; Bash, Python, editing, tests, and data processing execute in the
Firecracker guest. Model substitution, host-local tool fallback, manual
replay of future actions, gold-patch injection, or reusing evaluator caches is
not allowed.

The formal plan is twelve pre-registered tasks (six SWE-bench Verified and six
DSBench Modeling), at most one naturally occurring Tool-idle and one
Tool-active checkpoint per task, and at most four qualified mutation branches
per checkpoint. Missing natural checkpoints are recorded as `NOT_OBSERVED`;
states are never fabricated to fill a quota. SWE-bench uses the official
FAIL_TO_PASS, PASS_TO_PASS, and `resolved` evaluator plus patch/tool/restore
evidence. DSBench must use each task's official metric and evaluator after
verifying data and dependencies.

## Repository layout

```text
agent-checkpoint-stage1/
├── README.md
├── STAGE1_PROTOCOL.md
├── imports/import_manifest.json
├── third_party/swe_bench/
├── workloads/{swebench,dsbench}/
├── infrastructure/{slurm,firecracker,openhands}/
├── pilot/
├── oracle/{capture,mapping,transformations,validation}/
├── evaluation/
├── analysis/
├── runs/{pilot,formal}/
└── reports/
```

Runtime artifacts belong under `runs/`; source code, manifests, and validators
remain reviewable and deterministic. Each run must contain the manifests and
raw logs listed in `STAGE1_PROTOCOL.md`, with hashes for snapshots and disks.

## Cluster storage contract

The cluster storage policy is a hard constraint, documented in
[`infrastructure/storage/STORAGE_POLICY.md`](infrastructure/storage/STORAGE_POLICY.md).
HOME holds only this project’s source and small indexes; regenerable model,
environment, package, and compiler caches live in SCRATCH; retained raw
evidence is published through staged SHA-256/size verification into FACT_DATA.
The read-only audit and publisher are covered by the storage-tool tests. The
current remote audit/index is recorded in
[`reports/STAGE1_STORAGE_MANIFEST_20261008.json`](reports/STAGE1_STORAGE_MANIFEST_20261008.json);
it explicitly leaves legacy results untouched and records quota as UNKNOWN
when the cluster quota interfaces cannot report a user limit.

## Evidence gates

| Gate | Required evidence | Status at scaffold initialization |
| --- | --- | --- |
| G0 | real OpenHands + Qwen + Firecracker pilot E2E | NOT_RUN |
| G1 | independent pristine fresh restore controls | NOT_RUN |
| G2 | verified native-object/address/page mapping | NOT_RUN |
| G3 | mutation bounds, hashes, and untouched-region checks | NOT_RUN |
| G4 | paired autonomous continuation and official evaluation | NOT_RUN |
| G5 | independent accounting and recomputation | NOT_RUN |

Result labels are `VALID_PASS`, `VALID_NEGATIVE`, `INCONCLUSIVE`,
`INVALID_INFRA`, `NOT_TESTED`, and `UNKNOWN`. Infrastructure failures,
Slurm preemption, network failures, and unavailable evaluators must remain
separate from semantic negative results.

## Current status

- [x] Independent directory scaffold created.
- [x] Legacy directory inspected read-only; no files changed there.
- [x] Import policy and inspected-source hashes recorded.
- [ ] Remote host, Slurm, Firecracker, OpenHands, and vLLM versions verified.
- [ ] Pilot passes G0.
- [ ] Formal task manifest and checkpoint collection complete.
- [ ] Oracle census, fidelity treatments, paired restores, and accounting complete.
- [ ] Independent validator and `reports/STAGE1_FINAL_REPORT.md` complete.

Do not interpret this scaffold as an experiment completion claim. The first
scientific result may legitimately be that no qualified candidate or no
additional reduction was observed.
