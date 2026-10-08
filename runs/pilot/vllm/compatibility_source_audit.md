# Qwen3-Coder / vLLM compatibility source audit

Audit date: 2026-10-08 (Asia/Shanghai). This is an engineering prerequisite,
not a model-serving PASS.

## Primary sources checked

* [Qwen vLLM deployment guide](https://qwen.readthedocs.io/en/latest/deployment/vllm.html)
  (the source page recommends `vllm>=0.8.5`, documents Qwen3 reasoning-parser
  behavior from v0.9.0, and warns that prebuilt vLLM has strict Torch/CUDA
  dependencies). Its tool-calling example uses `--enable-auto-tool-choice`
  and a parser name; this does not by itself certify the Coder checkpoint.
* [vLLM v0.10.1 source tree](https://github.com/vllm-project/vllm/tree/v0.10.1)
  (the tag contains both `vllm/model_executor/models/qwen3_moe.py` and
  `vllm/entrypoints/openai/tool_parsers/qwen3coder_tool_parser.py`).
* [vLLM Qwen3-Coder parser at v0.10.1](https://github.com/vllm-project/vllm/blob/v0.10.1/vllm/entrypoints/openai/tool_parsers/qwen3coder_tool_parser.py)
  (the source decorator is `@ToolParserManager.register_module(["qwen3_coder"])`).
* [Qwen3-Coder model card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct)
  and [Qwen3-Coder repository](https://github.com/QwenLM/Qwen3-Coder) (the
  fixed checkpoint is explicitly an agentic/tool-calling model).

The official source inspection establishes a candidate parser contract, not
runtime compatibility. Runtime qualification still requires the isolated
environment, `pip check`, actual registry lookup, model warm-up, a structured
OpenAI tool call, and an OpenHands SDK request through the same endpoint.

## Candidate selection

The old `/fact_home/yishi/.conda/envs/vllm-agent-clean` environment remains
untouched evidence only: vLLM 0.8.3, Torch 2.6.0, Transformers 4.51.3, and
three failed Qwen3-MoE warm-ups are `INVALID_INFRA`. It is not reused.

The first new candidate is vLLM `0.10.1`, selected because its official source
tag contains the Qwen3-MoE implementation and the built-in `qwen3_coder`
parser. PyPI metadata inspected remotely requires, among other packages,
Transformers >=4.55.0 and Torch/Torchaudio 2.7.1/Torchvision 0.22.1 for this
release. These requirements must be confirmed after installation with the
candidate environment's `pip check` and CUDA runtime report; they are not
assumed to be satisfied.

The isolated prefix is on the cluster scratch filesystem (the first attempt
under `/fact_home` hit the user's file quota before installation completed):

```text
/scratch/yishi/stage1-vllm-qwen3-0101
```

No package was installed into the old environment. The bounded install log is
`runs/pilot/vllm/isolated_vllm_0101_install.log` on the remote project. A
successful download or import will not be called compatible until the Slurm
job `vllm_qwen3_coder_compat.sbatch` passes all four runtime checks.

## Runtime gate order

1. Candidate versions and `pip check`, GPU/CUDA and fixed model/parser hashes.
2. `ToolParserManager.tool_parsers` contains `qwen3_coder`.
3. vLLM warm-up and `/health`/`/v1/models` response.
4. Simple chat, structured forced tool call, local tool execution/follow-up,
   and an OpenHands SDK completion through the node-specific endpoint.

Any failure is `INVALID_INFRA`; no Firecracker Live Agent Pilot or formal
checkpoint collection may start until the complete gate is `PASS`.
