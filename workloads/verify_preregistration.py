"""Dependency-free verifier for the frozen benchmark preregistration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workloads" / "benchmark_preregistration.json"


def key(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()


def verify() -> list[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data["protocol_id"] != "stage1-real-agent-oracle-2026-10-08":
        errors.append("protocol_id mismatch")
    if data["budgets"]["swebench_tasks"] != 6 or data["budgets"]["dsbench_tasks"] != 6:
        errors.append("task budget mismatch")

    tasks = data["swebench"]["tasks"]
    if len(tasks) != 6 or len({task["instance_id"] for task in tasks}) != 6:
        errors.append("SWE task uniqueness/count mismatch")
    if "astropy/astropy" not in {task["repo"] for task in tasks}:
        errors.append("Astropy is absent")
    for task in tasks:
        if task["selection_key_sha256"] != key("stage1-swe-v1", task["instance_id"]):
            errors.append(f"bad task selection key: {task['instance_id']}")
        if task["repository_selection_key_sha256"] != key("stage1-swe-repo-v1", task["repo"]):
            errors.append(f"bad repository selection key: {task['repo']}")

    ds = data["dsbench_modeling"]
    if ds["status"] != "BLOCKED_PENDING_DATA_LABEL_DEPENDENCY_VERIFICATION":
        errors.append("DSBench must remain blocked until qualification")
    if len(ds["tasks"]) != 6 or any(task["qualification"] != "BLOCKED" for task in ds["tasks"]):
        errors.append("DSBench qualification state is inconsistent")
    return errors


if __name__ == "__main__":
    failures = verify()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        raise SystemExit(1)
    print("PASS: benchmark preregistration is internally consistent")
