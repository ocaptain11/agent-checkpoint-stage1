"""Pilot orchestration helpers.

The runner is a thin evidence-producing wrapper around real OpenHands,
Firecracker, vLLM, checkpoint, restore, and evaluator commands.  It has no
synthetic workload mode and never fabricates a PASS.
"""
