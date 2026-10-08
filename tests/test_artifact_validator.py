from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from oracle.validation.schema import Gate, Status
from oracle.validation.validator import ArtifactValidator


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _base_run(root: Path) -> None:
    for name in ("memory.snap", "vmstate.snap", "disk.img", "prefix.json", "tool-1.log", "tool-2.log"):
        (root / name).write_bytes(b"evidence")
    (root / "evaluator_result.json").write_text(json.dumps({"resolved": True}), encoding="utf-8")
    _write(root / "environment_manifest.json", {"python": "3.11", "firecracker_version": "1.17.0"})
    _write(root / "benchmark_manifest.json", {"benchmark": "swebench_verified", "task_id": "demo__repo-1"})
    _write(
        root / "experiment_manifest.json",
        {
            "run_id": "formal-001",
            "run_kind": "formal",
            "checkpoint": {
                "full_snapshot": True,
                "memory_snap": "memory.snap",
                "vmstate_snap": "vmstate.snap",
                "disk_state": "disk.img",
                "host_agent_prefix": "prefix.json",
            },
            "pristine_controls": [
                {
                    "run_id": "pristine-1",
                    "fresh_restore": True,
                    "original_vmm_terminated": True,
                    "new_vmm_pid": 1001,
                    "tool_reconnected": True,
                    "continuation_started": True,
                },
                {
                    "run_id": "pristine-2",
                    "fresh_restore": True,
                    "original_vmm_terminated": True,
                    "new_vmm_pid": 1002,
                    "tool_reconnected": True,
                    "continuation_started": True,
                },
            ],
        },
    )
    _write(
        root / "pilot_evidence.json",
        {
            "openhands_started": True,
            "vllm_started": True,
            "firecracker_started": True,
            "guest_tool_execution": True,
            "checkpoint_created": True,
            "fresh_restore": True,
            "original_vmm_terminated": True,
            "host_prefix_restored": True,
            "tool_reconnected": True,
            "autonomous_continuation": True,
            "official_evaluator": True,
            "guest_actions": [
                {"action_id": "a-1", "guest_pid": 2001, "execution_location": "guest", "raw_log": "tool-1.log"}
            ],
            "continuation_actions": [
                {"action_id": "a-2", "guest_pid": 2002, "execution_location": "guest", "raw_log": "tool-2.log"}
            ],
            "checkpoint_artifacts": ["memory.snap", "vmstate.snap", "disk.img", "prefix.json"],
            "evaluator_result_file": "evaluator_result.json",
        },
    )
    _write(
        root / "mapping_report.json",
        {
            "objects": [
                {
                    "object_id": "arr-1",
                    "identity": "Numeric",
                    "pid": 2001,
                    "data_pointer": 4096,
                    "virtual_address": "0x1000",
                    "nbytes": 16,
                    "guest_physical_pages": [7],
                    "snapshot_offsets": [8192],
                    "source_hash": "a" * 64,
                    "snapshot_hash": "b" * 64,
                    "mapping_verified": True,
                }
            ],
            "unknown_count": 2,
        },
    )
    _write(root / "state_census.json", {"states": [{"object_id": "arr-1", "identity": "Numeric"}]})
    _write(
        root / "mutation_results.json",
        {
            "treatments": [
                {
                    "treatment_id": "arr-1-fp16",
                    "object_id": "arr-1",
                    "mutation_type": "FP16",
                    "source_hash_before": "a" * 64,
                    "source_hash_after": "c" * 64,
                    "snapshot_hash_before": "b" * 64,
                    "snapshot_hash_after": "d" * 64,
                    "changed_byte_offsets": [0, 1],
                    "mapping_valid": True,
                    "bounds_valid": True,
                    "untouched_regions_hash_valid": True,
                    "mutation_applied": True,
                    "independent_pristine": True,
                }
            ]
        },
    )
    _write(
        root / "evaluation_results.json",
        {
            "pairs": [
                {
                    "pair_id": "pair-1",
                    "pristine_run_id": "pristine-eval-1",
                    "mutation_run_id": "mutation-eval-1",
                    "treatment_id": "arr-1-fp16",
                    "fresh_restore": True,
                    "autonomous_continuation": True,
                    "official_evaluator": True,
                    "evaluator_completed": True,
                    "mapping_valid": True,
                    "state_exercised": True,
                    "task_correct": True,
                }
            ]
        },
    )
    _write(
        root / "storage_ram_report.json",
        {
            "best_lossless_codec": "zstd",
            "best_lossless_original_size": 1000,
            "best_lossless_semantic_encoded_size": 400,
            "required_auxiliary_bytes": 50,
            "additional_reduction": 0.55,
            "ram_measurement_kind": "estimated",
            "estimated_reclaimable_bytes": 550,
        },
    )
    _write(root / "failure_log.json", {"failures": []})


class ArtifactValidatorTests(unittest.TestCase):
    def test_historical_run_reports_storage_not_tested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base_run(root)
            report = ArtifactValidator(root).validate()
            self.assertEqual(report.storage["status"], Status.NOT_TESTED.value)
            self.assertEqual(report.status, Status.VALID_PASS)

    def test_new_run_requires_storage_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base_run(root)
            experiment = json.loads((root / "experiment_manifest.json").read_text())
            experiment["storage_policy_required"] = True
            _write(root / "experiment_manifest.json", experiment)
            report = ArtifactValidator(root).validate()
            self.assertEqual(report.storage["status"], Status.INVALID_INFRA.value)
            self.assertEqual(report.status, Status.INVALID_INFRA)

    def test_new_run_rejects_unverified_home_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base_run(root)
            (root / "storage_manifest.json").write_text(json.dumps({
                "records": [{
                    "storage_class": "HOME",
                    "path": str(root / "memory.snap"),
                    "kind": "checkpoint",
                    "persistence_status": "VERIFIED",
                    "verification": {"status": "VERIFIED"},
                }]
            }), encoding="utf-8")
            experiment = json.loads((root / "experiment_manifest.json").read_text())
            experiment.update({"storage_policy_required": True, "storage_manifest_path": "storage_manifest.json"})
            _write(root / "experiment_manifest.json", experiment)
            report = ArtifactValidator(root).validate()
            self.assertEqual(report.storage["status"], Status.INVALID_INFRA.value)
            self.assertEqual(report.status, Status.INVALID_INFRA)
    def test_complete_formal_run_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base_run(root)
            report = ArtifactValidator(root).validate()
            self.assertEqual(report.status, Status.VALID_PASS)
            self.assertTrue(all(g.status is Status.VALID_PASS for g in report.gates))

    def test_missing_mapping_is_not_tested_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base_run(root)
            (root / "mapping_report.json").unlink()
            report = ArtifactValidator(root).validate()
            statuses = {g.gate: g.status for g in report.gates}
            self.assertEqual(statuses[Gate.G2], Status.NOT_TESTED)
            self.assertNotEqual(report.status, Status.VALID_PASS)

    def test_bad_storage_formula_is_invalid_infrastructure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base_run(root)
            storage = json.loads((root / "storage_ram_report.json").read_text())
            storage["additional_reduction"] = 0.1
            _write(root / "storage_ram_report.json", storage)
            report = ArtifactValidator(root).validate()
            statuses = {g.gate: g.status for g in report.gates}
            self.assertEqual(statuses[Gate.G5], Status.INVALID_INFRA)
            self.assertEqual(report.status, Status.INVALID_INFRA)

    def test_pilot_fallback_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "experiment_manifest.json", {"run_id": "pilot-1", "run_kind": "pilot"})
            _write(
                root / "pilot_evidence.json",
                {
                    "openhands_started": True,
                    "vllm_started": True,
                    "firecracker_started": True,
                    "guest_tool_execution": True,
                    "checkpoint_created": True,
                    "fresh_restore": True,
                    "original_vmm_terminated": True,
                    "host_prefix_restored": True,
                    "tool_reconnected": True,
                    "autonomous_continuation": True,
                    "official_evaluator": True,
                    "guest_fallback": True,
                },
            )
            report = ArtifactValidator(root).validate()
            self.assertEqual(report.gates[0].status, Status.INVALID_INFRA)
            self.assertEqual(report.status, Status.INVALID_INFRA)

    def test_pilot_boolean_claims_without_raw_evidence_do_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "experiment_manifest.json", {"run_id": "pilot-raw-missing", "run_kind": "pilot"})
            _write(
                root / "pilot_evidence.json",
                {
                    "status": "PASS",
                    "openhands_started": True,
                    "vllm_started": True,
                    "firecracker_started": True,
                    "guest_tool_execution": True,
                    "checkpoint_created": True,
                    "fresh_restore": True,
                    "original_vmm_terminated": True,
                    "host_prefix_restored": True,
                    "tool_reconnected": True,
                    "autonomous_continuation": True,
                    "official_evaluator": True,
                },
            )
            _write(root / "failure_log.json", {"failures": []})
            report = ArtifactValidator(root).validate()
            self.assertEqual(report.gates[0].status, Status.NOT_TESTED)
            self.assertNotEqual(report.status, Status.VALID_PASS)

    def test_out_of_bounds_mutation_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base_run(root)
            mutation = json.loads((root / "mutation_results.json").read_text())
            mutation["treatments"][0]["changed_byte_offsets"] = [16]
            _write(root / "mutation_results.json", mutation)
            report = ArtifactValidator(root).validate()
            statuses = {g.gate: g.status for g in report.gates}
            self.assertEqual(statuses[Gate.G3], Status.INVALID_INFRA)

    def test_duplicate_evaluation_run_id_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base_run(root)
            evaluation = json.loads((root / "evaluation_results.json").read_text())
            evaluation["pairs"].append({
                **evaluation["pairs"][0],
                "pair_id": "pair-2",
                "pristine_run_id": "pristine-eval-2",
                "treatment_id": "arr-1-fp16",
                "mutation_run_id": "mutation-eval-1",
            })
            _write(root / "evaluation_results.json", evaluation)
            report = ArtifactValidator(root).validate()
            statuses = {g.gate: g.status for g in report.gates}
            self.assertEqual(statuses[Gate.G4], Status.INVALID_INFRA)


if __name__ == "__main__":
    unittest.main()
