import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workloads" / "benchmark_preregistration.json"


def _key(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()


def test_manifest_is_frozen_and_has_expected_budget():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["protocol_id"] == "stage1-real-agent-oracle-2026-10-08"
    assert data["selection_policy"]["frozen_before_formal_runs"] is True
    assert data["selection_policy"]["selection_may_use_success_rate"] is False
    assert data["selection_policy"]["selection_may_use_semantic_opportunity"] is False
    assert data["budgets"]["swebench_tasks"] == 6
    assert data["budgets"]["dsbench_tasks"] == 6
    assert data["budgets"]["max_checkpoints_total"] == 24


def test_swe_tasks_are_unique_and_selection_keys_recompute():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tasks = data["swebench"]["tasks"]
    assert len(tasks) == 6
    assert len({t["instance_id"] for t in tasks}) == 6
    assert "astropy/astropy" in {t["repo"] for t in tasks}
    for task in tasks:
        assert task["selection_key_sha256"] == _key("stage1-swe-v1", task["instance_id"])
        assert task["repository_selection_key_sha256"] == _key("stage1-swe-repo-v1", task["repo"])
    universe = data["swebench"]["repository_universe_counts"]
    expected_repos = [repo for _, repo in sorted(((_key("stage1-swe-repo-v1", repo), repo) for repo in universe))[:6]]
    assert {task["repo"] for task in tasks} == set(expected_repos)


def test_dsbench_tasks_have_official_metric_and_remain_blocked_until_qualified():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ds = data["dsbench_modeling"]
    assert ds["status"] == "BLOCKED_PENDING_DATA_LABEL_DEPENDENCY_VERIFICATION"
    assert len(ds["tasks"]) == 6
    assert all(t["qualification"] == "BLOCKED" for t in ds["tasks"])
    assert {t["metric"] for t in ds["tasks"]} >= {"accuracy", "RMSE", "RMSLE", "MAE", "macro-F1"}
    assert ds["official_source"]["processed_data_size_bytes"] == 3126493713
    assert any("401" in x for x in ds["blocking_evidence"])


def test_no_legacy_runtime_reference_in_preregistration():
    text = MANIFEST.read_text(encoding="utf-8").lower()
    assert "agent-checkpoint/" not in text
    assert "replay-history" not in text
