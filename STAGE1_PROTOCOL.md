# Stage 1 Experimental Protocol

Protocol identifier: `stage1-real-agent-oracle-2026-10-08`

This document is the normative contract for the Stage 1 study. Any deviation
must be recorded in the experiment manifest before interpreting a result. A
small engineering correction is allowed only when it preserves the contract;
changing the model, benchmark, correctness criterion, or state-selection rule
requires an explicit protocol revision.

## 1. Scope and hypotheses

Stage 1 asks four questions in real Agent-with-Sandbox executions.  The core
estimand is the **minimum observed safe fidelity** for each mapped native
state, not a presumed identity label:

1. What numeric, reconstructible, disposable, exact, mixed, and unknown state
   exists in a checkpoint, and how does it live across Tool-idle and
   Tool-active boundaries?
2. What minimum observed fidelity (EXACT, FP16, INT8, INT4, RECONSTRUCT, or
   DROP) survives a fresh restore and live continuation for each native state?
3. How heterogeneous is fidelity sensitivity across states and tasks?
4. How much storage and physically recoverable memory remains after the best
   measured lossless baseline, once semantic encoding and all auxiliary bytes
   are included?

The unit of inference is the tested state under the stated workload and
continuation. A result is not a universal safety guarantee. Negative,
unknown, untested, and infrastructure-invalid outcomes are first-class data.

## 2. Fixed systems

### Agent and model

- Use the OpenHands SDK at a recorded immutable git commit.
- Run a host Agent Controller and custom tool executor; guest-side commands
  execute only in Firecracker.
- Serve `Qwen/Qwen3-Coder-30B-A3B-Instruct` through vLLM's OpenAI-compatible
  endpoint. Record model weights revision, vLLM version, tool-call parser,
  system prompt, temperature, top-p, seed, context length, tool/token budget,
  timeout, endpoint, and startup/shutdown timestamps.
- Do not substitute a model, silently change sampling, or use a host-local
  tool implementation.

### Firecracker and guest

- Verify the installed Firecracker version (target baseline v1.17.0 only if
  actually present), kernel, rootfs, Python, task dependencies, vCPU, RAM,
  network/vsock configuration, and `/dev/kvm` permissions.
- Every branch starts from the same read-only base image and an independent
  writable disk copy. A FULL checkpoint includes `memory.snap`,
  `vmstate.snap`, and the corresponding disk state.
- A fresh restore terminates the original VMM, creates a new Firecracker
  process with independent socket paths, reconnects network/vsock, restores
  host Agent state/prefix, and deduplicates tool commands. Reusing a live
  VMM is not a fresh restore.

### Benchmarks and pre-registration

- Pre-register six SWE-bench Verified tasks spanning multiple repositories,
  including Astropy where selected, and six DSBench Modeling tasks. Record
  task IDs, dataset/version/revision, official evaluator and metric,
  checkpoint-selection rule, budget, and exclusion reason before collection.
- SWE-bench uses official FAIL_TO_PASS, PASS_TO_PASS, `resolved`, patch
  validity, tool errors, restore continuation, and evaluator records.
- DSBench may enter the formal set only after verifying data, labels,
  dependencies, and the official Kaggle-style evaluator. CSV shape checks do
  not replace the official score; record RMSE/accuracy or the task-specified
  metric and prediction validity.
- Each SWE-bench branch has a unique evaluation `run_id`; evaluator caches
  must not be reused across pristine and treatment branches.

## 3. Sample and checkpoint rules

- Each task can contribute at most one naturally occurring Tool-idle
  checkpoint (tool completed, before the next tool begins) and one Tool-active
  checkpoint (inside a real Python/pytest/data/training command).
- Collect no more than 24 checkpoints total. If the boundary never occurs,
  record `NOT_OBSERVED`; do not synthesize state or pause solely to fill a
  quota.
- For every qualified checkpoint reserve two independent pristine controls.
  Run mutation treatments only when mapping and candidate qualifications hold;
  initial budget is at most four treatment branches per checkpoint.
- Save the complete Agent/tool trajectory, action IDs, guest PIDs, execution
  location, raw tool/VM logs, resource samples, timestamps, task and Agent
  commits, guest image/config hashes, snapshot/disk hashes, Host Agent prefix,
  and checkpoint timing label.
- Complete live Agent restore for Tool-idle (A) before studying Tool-active
  (B). If B can only be trace-driven because in-flight RPC/process state is
  not safely restorable, label it separately and do not present it as live
  correctness evidence.

## 4. Pilot (G0)

The pilot uses one real SWE-bench task solely for engineering validation. It
must perform all of the following:

1. start OpenHands and the fixed Qwen/vLLM service and verify the official
   evaluator is callable;
2. let the Agent autonomously issue Bash, Python, file, and test actions in
   Firecracker, recording action IDs, guest PIDs, execution location, and raw
   logs;
3. create a consistent FULL checkpoint at a tool-idle boundary;
4. terminate the original Firecracker VMM and restore with a new process,
   disk, socket paths, and host/guest connection;
5. restore the same Host Agent execution prefix and let the Agent choose the
   continuation actions; and
6. run the official evaluator against the Agent's actual output, preserving
   its raw result.

`PILOT_PASS` requires real continuation and evaluator execution; it does not
require SWE-bench `resolved=true`. Fallback to Host LocalWorkspace, manual
replay, gold-patch injection, a live original VMM, or missing continuation
evidence is `INVALID_INFRA` and cannot pass. Pilot output lives under
`runs/pilot/` and is excluded from formal science totals.

Pilot explicitly does **not** perform quantization, native-object scans,
fidelity sweeps, compression comparisons, or opportunity statistics.

## 5. Native capture and provenance (G2)

For each checkpoint build and validate the chain:

```text
native object → runtime virtual address/buffer range
             → guest physical page(s) → memory.snap byte offset(s)
```

Capture at minimum:

- NumPy data pointer, dtype, shape, strides, nbytes, owning PID, and lifetime;
- PyTorch CPU storage pointer, sharing/aliasing, layout, owning PID, and
  lifetime;
- cache/derived-state source, dependency files, rebuild procedure, and access
  observations; and
- object bytes and hashes before and after translation.

Validate virtual-to-physical translation, snapshot offset, page contents, and
ownership. `sys.getsizeof()` is not a buffer-size measurement. Record
unmapped objects, GC-invisible state, overlapping/shared buffers, and
mixed-ownership pages explicitly. File-backed status alone does not imply
reconstructibility. Only an object with a passing mapping report may enter a
mutation treatment.

## 6. State census

Keep two independent dimensions:

- **Identity/candidate:** Numeric, Reconstructible, Disposable, Exact/control,
  Unknown/Mixed.
- **Tested fidelity:** the lowest treatment actually surviving mapping,
  restore, state exercise, and behavioral evaluation.

For each state and checkpoint report unique bytes, pages, process, lifetime,
Tool-idle/active label, mapped bytes, unknown/untested bytes, and all overlap
deduplication. Candidate identity alone never assigns a safe fidelity.
Mixed pages cannot be counted as wholly transformable. Every denominator and
source artifact must be explicit.

## 7. Independent mutation treatments (G3)

Create every treatment independently from the same pristine checkpoint; never
stack mutations. Keep the original object layout and ABI unless the compact
encoding is itself the treatment under accounting.

- Numeric: pristine/original precision, FP16, INT8, and INT4. The first
  sensitivity pass for FP32 uses quantize→dequantize back to FP32 in the same
  memory layout, changing only numeric bytes while preserving dtype, pointer,
  object size, and metadata.
- Reconstructible: keep control versus drop, then rebuild through the actual
  dependency path; measure recomputation and continuation.
- Disposable: keep control versus drop and observe all later accesses.
- Exact/control: pristine and sham controls; deliberately damaged control
  structures, if needed, are isolated from semantic mutations.

For each branch record target identity, mapping proof, transform parameters,
before/after hashes, changed byte offsets and values, untouched-region hashes,
auxiliary metadata, and an integrity verdict. Out-of-bounds writes,
cross-object pollution, mutation of a non-mapped object, or missing proof is
`INVALID_INFRA`/`INVALID_MUTATION`, never a negative scientific result.

## 8. Paired fresh restore and evaluation (G1/G4)

Each qualified treatment and its same-source pristine control independently
restore from the same snapshot, disk state, Host Agent prefix, and model
configuration. Randomize branch order when practical. Reconnect tools and
let OpenHands choose future actions; do not replay a prerecorded future trace.

Evaluate three dimensions:

1. mapping validity (the intended bytes were changed);
2. state exercised (read, used, or successfully reconstructed after restore);
3. behavioral correctness (continuation and official task evaluation).

If pristine fails or shows substantial normal stochastic variation, do not
attribute a treatment difference to semantic mutation. If the target is not
read, report `NOT_EXERCISED`/`INCONCLUSIVE`. Trace-driven suffixes are useful
for instrumentation but cannot replace autonomous live-Agent evidence.

## 9. Storage, RAM, and cost accounting (G5)

Measure original and transformed checkpoints with a predeclared lossless codec
selection rule (for example, choose the best of LZ4 and Zstd on the same
bytes). Then account for compact semantic encodings including packed values,
scale/zero-point, decoder metadata, reconstruction data, and required layout
information. Use:

```text
additional_reduction = 1 -
  (best_lossless_semantic_encoded_size + required_auxiliary_bytes)
  / best_lossless_original_size
```

Keep separate columns for layout-preserving fidelity sensitivity, measured
compact storage, estimated reclaimable physical memory, and actually reclaimed
host RAM. Record encode/decode time, restore latency, recomputation, extra
tool calls, task wall time, guest configured/used/resident memory, host RSS/PSS
and private/shared/file-backed pages, snapshot size, timing label, and state
lifetime. A `memory.snap` file size is not sandbox-owned physical RAM, and an
estimate is not a reclamation claim.

## 10. Artifacts, validator, and status vocabulary

Every run must preserve:

```text
environment_manifest.json
benchmark_manifest.json
experiment_manifest.json
mapping_report.json
state_census.json
mutation_results.json
evaluation_results.json
storage_ram_report.json
failure_log.json
```

Also preserve raw Agent/tool/VM/Slurm/evaluator logs, snapshot/disk hashes,
and scripts sufficient to recompute every number. An independent validator
must read raw artifacts directly and check qualifications, mappings,
mutations, restores, evaluator outputs, byte counts, and compression math; it
must not trust narrative summaries.

Each branch receives one of `VALID_PASS`, `VALID_NEGATIVE`, `INCONCLUSIVE`,
`INVALID_INFRA`, `NOT_TESTED`, or `UNKNOWN`. A Slurm preemption, network
failure, missing evaluator, or unavailable dependency remains infrastructure
failure. Report all tasks, branches, exclusions, `NOT_OBSERVED` checkpoints,
and failures rather than selecting successful examples.

## 11. Final report

`reports/STAGE1_FINAL_REPORT.md` must stratify results by benchmark, checkpoint
timing, state identity, and tested fidelity. The primary figure is exactly
**State Fraction vs Minimum Observed Safe Fidelity**, with UNKNOWN and UNTESTED shown
explicitly. Include baseline and restoration costs, all failure reasons,
negative findings, and the limits of any conclusion. Do not claim Stage 2/3
generalization, automatic discovery, physical page reclamation, or universal
semantic safety from Stage 1 observations.
