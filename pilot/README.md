# Pilot orchestration skeleton

`pilot_runner.py` defaults to plan-only mode. It starts external services only
with `--execute`. The checked-in example config intentionally contains
`REPLACE_ME`/site-specific values and therefore cannot accidentally produce a
pilot pass.

```bash
python pilot/pilot_runner.py \
  --config infrastructure/openhands/pilot_config.example.json \
  --run-dir runs/pilot/pilot-001 --pretty
```

Before execution, replace the example values with verified pinned OpenHands,
Firecracker image, model endpoint, official evaluator, and one selected real
SWE-bench task. The runner requires raw action logs carrying Guest PIDs and
action IDs, checkpoint files, a distinct restored VMM PID, restore evidence,
post-restore autonomous actions, and evaluator JSON. A local-workspace
fallback, manual replay, injected gold patch, missing evidence, or failed
command yields `INVALID_INFRA`/`NOT_TESTED`, never `PILOT_PASS`.

On the Linux execution host, verify the checked-in wrappers are executable
(`chmod +x infrastructure/firecracker/*.sh infrastructure/openhands/*.sh`)
and record that permission/configuration check in the environment manifest.

The example submits the vLLM service asynchronously with `sbatch`; do not add
`--wait`, because the service is expected to remain available while the Agent
and restore branches run. Point `health_url` at the actual allocated GPU-node
endpoint recorded by the Slurm manifest.
