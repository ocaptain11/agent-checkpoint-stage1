# Qwen3-Coder/vLLM compatibility gate

This is an engineering gate for the Stage 1 Pilot.  It is deliberately not a
claim that a package version is compatible until the isolated Slurm job has
passed all checks below.  The existing `vllm-agent-clean` environment is
frozen evidence only (`vllm 0.8.3`, `torch 2.6.0`, `transformers 4.51.3`) and
must not be modified or used as the candidate environment.

## Fixed model and parser contract

The weights stay fixed at `Qwen/Qwen3-Coder-30B-A3B-Instruct`; no model
replacement or quantized checkpoint is allowed.  The expected parser key is
`qwen3_coder`, but this must be observed in the candidate runtime rather than
assumed.  If the candidate vLLM does not ship that parser, the official model
parser file must be loaded with `--tool-parser-plugin` and its registration
must be checked through `ToolParserManager.tool_parsers` before serving.

The serving command must include:

```text
--enable-auto-tool-choice --tool-call-parser qwen3_coder
```

The job must record the actual parser registry, the parser module path/hash,
and the complete resolved package versions.  A successful `/v1/models` or
plain text response alone is insufficient.

## Candidate versions and evidence status

| Candidate | Role | Status before isolated test |
|---|---|---|
| 0.8.3 (Torch 2.6.0, Transformers 4.51.3) | Existing baseline | **INVALID_INFRA**: Qwen3-MoE warm-up failed; retained only as negative engineering evidence |
| 0.10.0 | First candidate family to investigate | `TO_VERIFY`; do not infer support from download success |
| 0.10.1/0.10.1.post1 (if available in the approved index) | Patch candidate | `TO_VERIFY`; test only after recording wheel metadata |
| 0.11.x or later | Fallback candidate if the 0.10 family fails | `TO_VERIFY`; may only be selected with a recorded compatibility rationale |

The exact PyTorch, CUDA runtime, Transformers, and vLLM requirements must be
taken from the candidate wheel metadata and the installed runtime on the
allocated GPU node.  Do not copy the old environment or silently upgrade it.
The job must record `pip show`, `pip check`, `torch.__version__`,
`torch.version.cuda`, `transformers.__version__`, `vllm.__version__`, and
`nvidia-smi` output.  A package install succeeding is not compatibility
evidence.

## Required isolated Slurm checks

For each candidate, one bounded job (explicit wall-time and failure timeout)
must perform, in order:

1. import/version and `pip check` validation;
2. parser registration lookup (`qwen3_coder`); 
3. vLLM model load and warm-up completion;
4. `GET /v1/models` and a simple chat completion;
5. a real OpenAI tools request whose returned message contains a parseable
   tool call (not merely text resembling JSON);
6. an OpenHands SDK request through the same node-specific endpoint.

The job writes command lines, node/GPU, environment manifest, endpoint, start
and end times, exit status, and raw stdout/stderr.  Any failed stage is
`INVALID_INFRA`; it must not be reported as a semantic mutation result.

## Primary references to retrieve and archive from the remote job

* [Qwen3-Coder model card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct)
* [Qwen3-Coder announcement](https://qwenlm.github.io/blog/qwen3-coder/)
* [vLLM tool-calling documentation](https://docs.vllm.ai/en/latest/features/tool_calling.html)
* [vLLM supported-model documentation](https://docs.vllm.ai/en/latest/models/supported_models.html)
* [vLLM v0.10.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.10.0)

The URLs are primary-source pointers.  The remote audit must retain the
retrieved page or API response with timestamp; this file intentionally does
not turn a documentation claim into a PASS.

## Storage and persistence gate

The current candidate prefixes are job-isolated under SCRATCH:
`/scratch/yishi/stage1-vllm-py39` (1698012, timed out) and the distinct direct
bootstrap `/scratch/yishi/stage1-vllm-py39-direct0101` (1698764).  Each runtime
must have a single-writer READY marker before a serving job can read it.  HF,
pip, Conda, XDG, Torch, Triton, vLLM, CUDA and temporary paths are job-unique
SCRATCH directories and are recorded with their observed `realpath`, mount,
prefix and cache location.

Slurm output and raw probes are spooled in SCRATCH.  A gate cannot be reported
as PASS until its complete spool is copied through
`infrastructure/storage/publish_evidence.py` into FACT_DATA and receives a
`VERIFIED` receipt plus a separate persisted-status record.  Install success,
HTTP health, or an endpoint response without that receipt remains
`INVALID_INFRA`/`NOT_TESTED`.
