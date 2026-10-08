"""Independent validation of Stage 1 run artifacts.

The validator is intentionally conservative.  It never upgrades missing or
ambiguous evidence to a pass, and it keeps infrastructure failures distinct
from valid semantic negatives.  It can be invoked as a library or through
``python -m oracle.validation.cli``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import json
import math

from .schema import (
    Gate,
    GateResult,
    REQUIRED_ARTIFACTS,
    Status,
    ValidationReport,
    as_bool,
    as_nonnegative_number,
    first,
    list_or_empty,
    merge_reasons,
    nonempty_string,
    read_json,
    status_from,
)


_EPS = 1e-9
_INFRA_CATEGORIES = {
    "infra",
    "infrastructure",
    "network",
    "slurm",
    "firecracker",
    "vmm",
    "evaluator_unavailable",
    "tool_connection",
    "checkpoint_io",
}


def _truth(mapping: dict[str, Any], *keys: str) -> bool | None:
    return as_bool(first(mapping, *keys))


def _is_true(mapping: dict[str, Any], *keys: str) -> bool:
    return _truth(mapping, *keys) is True


def _is_false(mapping: dict[str, Any], *keys: str) -> bool:
    return _truth(mapping, *keys) is False


def _status(value: Any) -> Status | None:
    return status_from(value)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class _Loaded:
    artifacts: dict[str, dict[str, Any]]
    errors: list[str]


class ArtifactValidator:
    """Validate one run directory without relying on narrative summaries."""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir).resolve()

    def _load(self) -> _Loaded:
        artifacts: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for name in REQUIRED_ARTIFACTS:
            value, error = read_json(self.run_dir / name)
            if value is not None:
                artifacts[name] = value
            elif error:
                errors.append(error)
        # Pilot evidence is optional for formal runs but required to establish
        # G0.  Keep it outside REQUIRED_ARTIFACTS so old/pilot runs can be
        # validated without inventing formal artifacts.
        for name in ("pilot_evidence.json", "gate_results.json"):
            value, _ = read_json(self.run_dir / name)
            if value is not None:
                artifacts[name] = value
        return _Loaded(artifacts, errors)

    def validate(self) -> ValidationReport:
        loaded = self._load()
        a = loaded.artifacts
        experiment = a.get("experiment_manifest.json", {})
        run_id = first(experiment, "run_id", "experiment_id")
        run_kind = str(first(experiment, "run_kind", "kind", default="formal")).lower()
        if run_kind == "pilot":
            pilot_required = ("experiment_manifest.json", "failure_log.json")
            errors = [
                error for error in loaded.errors
                if any(name in error for name in pilot_required)
            ]
        else:
            errors = list(loaded.errors)
        warnings: list[str] = []

        storage = self._validate_storage(a)
        if storage.get("status") == Status.INVALID_INFRA.value:
            errors.extend(str(item) for item in storage.get("errors", []))
        elif storage.get("status") in {Status.NOT_TESTED.value, Status.UNKNOWN.value}:
            warnings.extend(str(item) for item in storage.get("warnings", []))

        # A missing formal artifact is an infrastructure/schema problem, but a
        # pilot may intentionally omit formal-only artifacts.  Gate methods
        # below retain their own NOT_TESTED status for missing evidence.
        if not self.run_dir.exists():
            errors.append(f"run directory does not exist: {self.run_dir}")

        gates = [
            self._gate_g0(a),
            self._gate_g1(a, run_kind),
            self._gate_g2(a),
            self._gate_g3(a),
            self._gate_g4(a),
            self._gate_g5(a),
        ]

        # Missing formal artifacts are reported as invalid only if the run
        # claims to be formal and at least one required artifact is absent.
        relevant = gates[:1] if run_kind == "pilot" else gates
        status = self._overall_status(relevant, errors)
        if run_kind == "pilot" and gates[0].status is Status.VALID_PASS and not errors:
            # A pilot PASS is about engineering continuity only; formal gates
            # remain NOT_TESTED by design.
            status = Status.VALID_PASS

        return ValidationReport(
            run_dir=str(self.run_dir),
            run_id=str(run_id) if run_id is not None else None,
            status=status,
            gates=gates,
            errors=errors,
            warnings=warnings,
            recomputed=self._recomputed(a),
            storage=storage,
        )

    def _validate_storage(self, artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Validate the storage contract for new runs without trusting prose.

        Historical artifacts that do not opt into ``storage_policy_required``
        remain auditable but are reported as NOT_TESTED.  New runs must point
        at a manifest whose required evidence is in FACT_DATA and has a
        publisher VERIFIED receipt.
        """
        experiment = artifacts.get("experiment_manifest.json", {})
        environment = artifacts.get("environment_manifest.json", {})
        required_value = first(experiment, "storage_policy_required", default=first(environment, "storage_policy_required"))
        required = as_bool(required_value) is True
        manifest_ref = first(experiment, "storage_manifest_path", "storage_manifest", default=first(environment, "storage_manifest_path", "storage_manifest"))
        if manifest_ref is None:
            if required:
                return {"status": Status.INVALID_INFRA.value, "errors": ["storage_policy_required=true but no storage manifest reference is present"], "warnings": []}
            return {"status": Status.NOT_TESTED.value, "errors": [], "warnings": ["storage manifest was not required by this historical artifact"]}

        if isinstance(manifest_ref, dict):
            manifest = manifest_ref
            manifest_path = None
        else:
            manifest_path = Path(str(manifest_ref))
            if not manifest_path.is_absolute():
                manifest_path = self.run_dir / manifest_path
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return {"status": Status.INVALID_INFRA.value if required else Status.UNKNOWN.value, "errors": [f"storage manifest unreadable: {exc}"], "warnings": []}
        if not isinstance(manifest, dict):
            return {"status": Status.INVALID_INFRA.value, "errors": ["storage manifest must be a JSON object"], "warnings": []}

        errors: list[str] = []
        records = manifest.get("records")
        if not isinstance(records, list):
            errors.append("storage manifest records must be a list")
            records = []
        checked = 0
        verified = 0
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(f"storage record {index} is not an object")
                continue
            required_record = bool(record.get("required_for_run", False)) or record.get("persistence_status") not in {None, "NOT_REQUIRED"}
            if not required_record:
                continue
            checked += 1
            path_value = record.get("path") or record.get("published_path")
            storage_class = str(record.get("storage_class", "")).upper()
            if not nonempty_string(path_value):
                errors.append(f"storage record {index} has no path")
                continue
            path = Path(str(path_value))
            if not path.is_absolute():
                path = self.run_dir / path
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                errors.append(f"storage record {index} path is unavailable: {path} ({exc})")
                continue
            normalized = resolved.as_posix()
            if normalized == "/data" or normalized.startswith("/data/"):
                errors.append(f"storage record {index} uses forbidden /data path")
            if storage_class == "FACT_DATA" and not (normalized == "/fact_data" or normalized.startswith("/fact_data/")):
                errors.append(f"storage record {index} FACT_DATA path is outside /fact_data")
            if storage_class == "HOME" and any(token in str(record.get("kind", "")).lower() for token in ("model", "cache", "checkpoint")):
                errors.append(f"storage record {index} places large/retained data in HOME")
            if storage_class == "SCRATCH" and record.get("regenerable") is False:
                errors.append(f"storage record {index} marks non-regenerable data as scratch-only")
            verification = record.get("verification") if isinstance(record.get("verification"), dict) else {}
            if record.get("persistence_status") not in {"VERIFIED", "PUBLISHED_VERIFIED"} or verification.get("status") != "VERIFIED":
                errors.append(f"storage record {index} lacks VERIFIED persistence status")
            if resolved.is_dir() and storage_class == "FACT_DATA":
                receipt_path = resolved / "_storage_publish_receipt.json"
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"storage record {index} lacks readable FACT_DATA publish receipt: {exc}")
                else:
                    if receipt.get("status") != "VERIFIED":
                        errors.append(f"storage record {index} FACT_DATA receipt is not VERIFIED")
                    else:
                        verified += 1
            elif resolved.is_file():
                verified += 1
            else:
                errors.append(f"storage record {index} is neither a regular file nor directory")

        status = Status.VALID_PASS.value if not errors and checked == verified else Status.INVALID_INFRA.value
        return {"status": status, "required": required, "manifest_path": str(manifest_path) if manifest_path else None, "checked_records": checked, "verified_records": verified, "errors": errors, "warnings": []}

    @staticmethod
    def _overall_status(gates: list[GateResult], errors: list[str]) -> Status:
        if errors:
            return Status.INVALID_INFRA
        if any(g.status is Status.INVALID_INFRA for g in gates):
            return Status.INVALID_INFRA
        if any(g.status is Status.UNKNOWN for g in gates):
            return Status.UNKNOWN
        if any(g.status is Status.INCONCLUSIVE for g in gates):
            return Status.INCONCLUSIVE
        if any(g.status is Status.VALID_NEGATIVE for g in gates):
            return Status.VALID_NEGATIVE
        if any(g.status is Status.NOT_TESTED for g in gates):
            return Status.NOT_TESTED
        return Status.VALID_PASS

    def _gate_g0(self, a: dict[str, dict[str, Any]]) -> GateResult:
        evidence = a.get("pilot_evidence.json")
        if evidence is None:
            experiment = a.get("experiment_manifest.json", {})
            inline = first(experiment, "pilot_evidence", "g0_evidence")
            evidence = inline if isinstance(inline, dict) else None
        if evidence is None:
            return GateResult(Gate.G0, Status.NOT_TESTED, ["no pilot evidence artifact"])

        reasons: list[str] = []
        prohibited = {
            "manual_replay": "manual replay was used",
            "guest_fallback": "Guest execution fell back to Host LocalWorkspace",
            "gold_patch_injected": "gold patch was injected into the Agent Guest",
            "original_vmm_kept_alive": "original VMM was not terminated before fresh restore",
        }
        for key, reason in prohibited.items():
            if _is_true(evidence, key):
                reasons.append(reason)
        required = {
            "openhands_started": "OpenHands did not start",
            "vllm_started": "vLLM/model service did not start",
            "firecracker_started": "Firecracker did not start",
            "guest_tool_execution": "no real Guest tool execution evidence",
            "checkpoint_created": "no checkpoint creation evidence",
            "fresh_restore": "no fresh restore evidence",
            "original_vmm_terminated": "original VMM termination is not evidenced",
            "host_prefix_restored": "Host Agent prefix restoration is not evidenced",
            "tool_reconnected": "Host–Guest tool reconnection is not evidenced",
            "autonomous_continuation": "autonomous Agent continuation is not evidenced",
            "official_evaluator": "official evaluator execution is not evidenced",
        }
        missing: list[str] = []
        for key, reason in required.items():
            if not _is_true(evidence, key):
                missing.append(reason)
        guest_actions = first(evidence, "guest_actions", "pre_checkpoint_actions")
        continuation_actions = first(evidence, "continuation_actions", "post_restore_actions")
        for label, actions in (("pre-checkpoint", guest_actions), ("post-restore", continuation_actions)):
            if not isinstance(actions, list) or not actions:
                missing.append(f"no {label} action records")
                continue
            for index, action in enumerate(actions):
                if not isinstance(action, dict):
                    missing.append(f"{label} action {index} is not an object")
                    continue
                if not nonempty_string(first(action, "action_id", "id")):
                    missing.append(f"{label} action {index} has no action_id")
                guest_pid = first(action, "guest_pid", "pid")
                if not isinstance(guest_pid, int) or guest_pid <= 0:
                    missing.append(f"{label} action {index} has no positive guest_pid")
                if str(first(action, "execution_location", default="")).lower() not in {"guest", "firecracker_guest"}:
                    missing.append(f"{label} action {index} is not marked as Guest execution")
                raw_log = first(action, "raw_log", "log_path")
                if not nonempty_string(raw_log):
                    missing.append(f"{label} action {index} has no raw log reference")
                else:
                    log_path = Path(str(raw_log))
                    if not log_path.is_absolute():
                        log_path = self.run_dir / log_path
                    if not log_path.exists():
                        missing.append(f"{label} action raw log is missing: {raw_log}")
        checkpoint_artifacts = first(evidence, "checkpoint_artifacts")
        if not isinstance(checkpoint_artifacts, list) or len(checkpoint_artifacts) < 3:
            missing.append("checkpoint artifact list is incomplete")
        else:
            for artifact in checkpoint_artifacts:
                if not nonempty_string(artifact):
                    missing.append("checkpoint artifact reference is empty")
                    continue
                path = Path(str(artifact))
                if not path.is_absolute():
                    path = self.run_dir / path
                if not path.exists():
                    missing.append(f"checkpoint artifact is missing: {artifact}")
        evaluator_result = first(evidence, "evaluator_result_file", "official_evaluator_result")
        if not nonempty_string(evaluator_result):
            missing.append("official evaluator result artifact is not referenced")
        else:
            result_path = Path(str(evaluator_result))
            if not result_path.is_absolute():
                result_path = self.run_dir / result_path
            if not result_path.exists():
                missing.append(f"official evaluator result artifact is missing: {evaluator_result}")
            else:
                try:
                    parsed_result = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    missing.append(f"official evaluator result is unreadable: {exc}")
                else:
                    if not isinstance(parsed_result, dict):
                        missing.append("official evaluator result must be a JSON object")
        explicit = _status(first(evidence, "status", "g0_status"))
        raw_status = str(first(evidence, "status", "g0_status", default="")).strip().upper()
        if reasons:
            return GateResult(Gate.G0, Status.INVALID_INFRA, reasons, {"status": explicit.value if explicit else None})
        if explicit is Status.INVALID_INFRA or raw_status in {"INVALID_INFRA", "INVALID", "INFRA_ERROR"}:
            return GateResult(Gate.G0, Status.INVALID_INFRA, ["pilot evidence explicitly marks infrastructure invalid"])
        if raw_status in {"NOT_TESTED", "UNKNOWN"} and missing:
            return GateResult(Gate.G0, Status.NOT_TESTED, ["pilot evidence explicitly marks the pilot as not tested", *missing])
        if missing:
            return GateResult(Gate.G0, Status.NOT_TESTED, missing)
        return GateResult(Gate.G0, Status.VALID_PASS, ["all pilot E2E evidence fields are present"], {
            "action_count": first(evidence, "action_count", default=0),
            "checkpoint_id": first(evidence, "checkpoint_id"),
        })

    def _gate_g1(self, a: dict[str, dict[str, Any]], run_kind: str) -> GateResult:
        experiment = a.get("experiment_manifest.json", {})
        checkpoint = first(experiment, "checkpoint", "checkpoint_manifest")
        if not isinstance(checkpoint, dict):
            return GateResult(Gate.G1, Status.NOT_TESTED, ["checkpoint manifest is absent"])
        reasons: list[str] = []
        if not _is_true(checkpoint, "full_snapshot", "is_full_snapshot"):
            reasons.append("checkpoint is not explicitly a FULL snapshot")
        for key, label in (
            ("memory_snap", "memory.snap"),
            ("vmstate_snap", "vmstate.snap"),
            ("disk_state", "disk state"),
            ("host_agent_prefix", "Host Agent prefix"),
        ):
            value = first(checkpoint, key)
            if not (nonempty_string(value) or isinstance(value, dict)):
                reasons.append(f"missing {label} evidence")

        controls = list_or_empty(first(experiment, "pristine_controls", "pristine_restores"))
        if len(controls) < 2:
            # Pilot may have one control; formal runs require two independent
            # controls as specified by the protocol.
            if run_kind == "pilot" and len(controls) >= 1:
                pass
            else:
                reasons.append("fewer than two independent pristine controls")
        control_ids: set[str] = set()
        for index, control in enumerate(controls):
            if not isinstance(control, dict):
                reasons.append(f"pristine control {index} is not an object")
                continue
            control_id = first(control, "run_id", "control_id")
            if not nonempty_string(control_id):
                reasons.append(f"pristine control {index} has no unique run_id")
            elif str(control_id) in control_ids:
                reasons.append(f"duplicate pristine control run_id: {control_id}")
            else:
                control_ids.add(str(control_id))
            for key, label in (
                ("fresh_restore", "fresh restore"),
                ("original_vmm_terminated", "original VMM termination"),
                ("new_vmm_pid", "new VMM process"),
                ("tool_reconnected", "tool reconnection"),
                ("continuation_started", "continuation start"),
            ):
                if key == "new_vmm_pid":
                    value = first(control, key)
                    if not isinstance(value, int) or value <= 0:
                        reasons.append(f"control {control_id or index}: missing {label} evidence")
                elif not _is_true(control, key):
                    reasons.append(f"control {control_id or index}: missing {label} evidence")
            old_pid = first(control, "original_vmm_pid")
            new_pid = first(control, "new_vmm_pid")
            if isinstance(old_pid, int) and isinstance(new_pid, int) and old_pid == new_pid:
                reasons.append(f"control {control_id or index}: restore reused original VMM PID")
            if _is_true(control, "trace_only", "replay_only"):
                reasons.append(f"control {control_id or index} is trace/replay-only")
        if reasons:
            return GateResult(Gate.G1, Status.INVALID_INFRA, reasons)
        return GateResult(Gate.G1, Status.VALID_PASS, ["pristine fresh-restore controls verified"], {
            "control_count": len(controls),
            "control_ids": sorted(control_ids),
        })

    def _gate_g2(self, a: dict[str, dict[str, Any]]) -> GateResult:
        mapping = a.get("mapping_report.json")
        if mapping is None:
            return GateResult(Gate.G2, Status.NOT_TESTED, ["mapping_report.json is absent"])
        explicit = _status(first(mapping, "status", "mapping_status"))
        if explicit is Status.INVALID_INFRA:
            return GateResult(Gate.G2, Status.INVALID_INFRA, ["mapping report explicitly marks infrastructure invalid"])
        objects = list_or_empty(first(mapping, "objects", "native_objects", "candidates"))
        no_candidates = _is_true(mapping, "no_qualified_candidates", "no_candidates")
        if not objects and no_candidates:
            return GateResult(Gate.G2, Status.VALID_NEGATIVE, ["no qualified native candidates were observed"], {
                "candidate_count": 0,
                "unknown_count": first(mapping, "unknown_count", default=0),
            })
        if not objects:
            return GateResult(Gate.G2, Status.NOT_TESTED, ["mapping report contains no mapped objects"])
        reasons: list[str] = []
        valid_ids: list[str] = []
        for index, obj in enumerate(objects):
            if not isinstance(obj, dict):
                reasons.append(f"mapping object {index} is not an object")
                continue
            oid = first(obj, "object_id", "id")
            prefix = f"mapping object {oid or index}"
            if not nonempty_string(oid):
                reasons.append(f"{prefix}: missing object_id")
            else:
                valid_ids.append(str(oid))
            if not nonempty_string(first(obj, "identity", "category")):
                reasons.append(f"{prefix}: missing semantic identity/category")
            if not isinstance(first(obj, "pid", "process_id"), int):
                reasons.append(f"{prefix}: missing owning PID")
            nbytes = as_nonnegative_number(first(obj, "nbytes", "byte_length"))
            if nbytes is None or nbytes <= 0:
                reasons.append(f"{prefix}: nbytes must be positive")
            for key, label in (
                ("data_pointer", "data pointer"),
                ("virtual_address", "virtual address"),
                ("guest_physical_pages", "Guest physical pages"),
                ("snapshot_offsets", "snapshot offsets"),
                ("source_hash", "source bytes hash"),
                ("snapshot_hash", "snapshot bytes hash"),
            ):
                value = first(obj, key)
                if key in {"guest_physical_pages", "snapshot_offsets"}:
                    if not isinstance(value, list) or not value:
                        reasons.append(f"{prefix}: missing {label}")
                elif key in {"data_pointer", "virtual_address"}:
                    if value is None:
                        reasons.append(f"{prefix}: missing {label}")
                elif not nonempty_string(value):
                    reasons.append(f"{prefix}: missing {label}")
            if not _is_true(obj, "mapping_verified", "verified"):
                reasons.append(f"{prefix}: mapping_verified is not true")
            if _is_true(obj, "mixed_page", "mixed_ownership") and not _is_true(obj, "excluded_from_mutation"):
                reasons.append(f"{prefix}: mixed-ownership page is not excluded from mutation")
            if _is_true(obj, "overlap") and not _is_true(obj, "shared_buffer_accounted"):
                reasons.append(f"{prefix}: overlapping/shared buffer is not accounted for")
        if reasons:
            return GateResult(Gate.G2, Status.INVALID_INFRA, reasons)
        return GateResult(Gate.G2, Status.VALID_PASS, ["all candidate mappings carry address/page/offset evidence"], {
            "candidate_count": len(valid_ids),
            "object_ids": valid_ids,
            "unknown_count": first(mapping, "unknown_count", default=0),
            "unmapped_count": first(mapping, "unmapped_count", default=0),
        })

    def _gate_g3(self, a: dict[str, dict[str, Any]]) -> GateResult:
        mapping_gate = self._gate_g2(a)
        if mapping_gate.status is not Status.VALID_PASS:
            return GateResult(Gate.G3, Status.NOT_TESTED, [
                f"native mapping is not eligible for mutation ({mapping_gate.status.value})"
            ])
        mutation = a.get("mutation_results.json")
        if mutation is None:
            return GateResult(Gate.G3, Status.NOT_TESTED, ["mutation_results.json is absent"])
        treatments = list_or_empty(first(mutation, "treatments", "mutations", "branches"))
        if not treatments:
            return GateResult(Gate.G3, Status.NOT_TESTED, ["no mutation treatments were run"])
        mapping_objects = list_or_empty(first(a.get("mapping_report.json", {}), "objects", "native_objects", "candidates"))
        nbytes_by_id = {
            str(first(obj, "object_id", "id")): as_nonnegative_number(first(obj, "nbytes", "byte_length"))
            for obj in mapping_objects if isinstance(obj, dict)
        }
        reasons: list[str] = []
        for index, treatment in enumerate(treatments):
            if not isinstance(treatment, dict):
                reasons.append(f"treatment {index} is not an object")
                continue
            tid = first(treatment, "treatment_id", "id", default=index)
            if _is_true(treatment, "synthetic", "artificial_state", "mirror_object"):
                reasons.append(f"treatment {tid}: synthetic/mirror state is forbidden")
            for key, label in (
                ("object_id", "object_id"),
                ("mutation_type", "mutation type"),
                ("source_hash_before", "pre-mutation source hash"),
                ("source_hash_after", "post-mutation source hash"),
                ("snapshot_hash_before", "pre-mutation snapshot hash"),
                ("snapshot_hash_after", "post-mutation snapshot hash"),
            ):
                value = first(treatment, key)
                if key == "object_id":
                    if not nonempty_string(value):
                        reasons.append(f"treatment {tid}: missing {label}")
                elif not nonempty_string(value):
                    reasons.append(f"treatment {tid}: missing {label}")
            for key, label in (
                ("mapping_valid", "mapping validity"),
                ("bounds_valid", "bounds validity"),
                ("untouched_regions_hash_valid", "untouched-region integrity"),
                ("mutation_applied", "mutation application"),
                ("independent_pristine", "independent pristine branch"),
            ):
                if not _is_true(treatment, key):
                    reasons.append(f"treatment {tid}: {label} is not verified")
            offsets = first(treatment, "changed_byte_offsets", "changed_offsets")
            if not isinstance(offsets, list):
                reasons.append(f"treatment {tid}: changed byte offsets are absent")
            else:
                oid = str(first(treatment, "object_id"))
                nbytes = nbytes_by_id.get(oid)
                if nbytes is None:
                    reasons.append(f"treatment {tid}: object_id is absent from mapping report")
                else:
                    bad = [off for off in offsets if not isinstance(off, int) or off < 0 or off >= nbytes]
                    if bad:
                        reasons.append(f"treatment {tid}: mutation offsets exceed mapped object bounds")
            if _is_true(treatment, "out_of_bounds", "cross_object_write", "metadata_modified"):
                reasons.append(f"treatment {tid}: mutation contaminated non-target state")
        if reasons:
            return GateResult(Gate.G3, Status.INVALID_INFRA, reasons)
        return GateResult(Gate.G3, Status.VALID_PASS, ["mutation bounds and untouched-region checks verified"], {
            "treatment_count": len(treatments),
            "treatment_ids": [str(first(t, "treatment_id", "id", default=i)) for i, t in enumerate(treatments) if isinstance(t, dict)],
        })

    def _gate_g4(self, a: dict[str, dict[str, Any]]) -> GateResult:
        mutation = a.get("mutation_results.json")
        treatments = list_or_empty(first(mutation or {}, "treatments", "mutations", "branches"))
        if not treatments:
            return GateResult(Gate.G4, Status.NOT_TESTED, ["no mutation treatments to evaluate"])
        evaluation = a.get("evaluation_results.json")
        if evaluation is None:
            return GateResult(Gate.G4, Status.NOT_TESTED, ["evaluation_results.json is absent"])
        pairs = list_or_empty(first(evaluation, "pairs", "evaluations", "branches"))
        if not pairs:
            return GateResult(Gate.G4, Status.NOT_TESTED, ["no paired pristine/mutation evaluations were recorded"])
        reasons: list[str] = []
        inconclusive: list[str] = []
        negative = False
        mutation_run_ids: set[str] = set()
        pristine_run_ids: set[str] = set()
        treatment_ids = {
            str(first(treatment, "treatment_id", "id"))
            for treatment in treatments
            if isinstance(treatment, dict) and first(treatment, "treatment_id", "id") is not None
        }
        for index, pair in enumerate(pairs):
            if not isinstance(pair, dict):
                reasons.append(f"evaluation pair {index} is not an object")
                continue
            pid = first(pair, "pair_id", "evaluation_id", default=index)
            for key, label in (
                ("pristine_run_id", "pristine run ID"),
                ("mutation_run_id", "mutation run ID"),
                ("treatment_id", "treatment ID"),
            ):
                if not nonempty_string(first(pair, key)):
                    reasons.append(f"pair {pid}: missing {label}")
            pair_treatment = first(pair, "treatment_id")
            if nonempty_string(pair_treatment) and str(pair_treatment) not in treatment_ids:
                reasons.append(f"pair {pid}: treatment_id does not match mutation_results.json")
            for key, label in (
                ("fresh_restore", "fresh restore"),
                ("autonomous_continuation", "autonomous Agent continuation"),
                ("official_evaluator", "official evaluator execution"),
                ("mapping_valid", "mapping validity"),
                ("evaluator_completed", "evaluator completion"),
            ):
                if not _is_true(pair, key):
                    reasons.append(f"pair {pid}: {label} is not verified")
            if _is_true(pair, "trace_only", "replay_only") and not _is_true(pair, "autonomous_continuation"):
                inconclusive.append(f"pair {pid}: trace-only continuation")
            exercised = _truth(pair, "state_exercised", "target_state_exercised")
            if exercised is False:
                inconclusive.append(f"pair {pid}: target state was not exercised")
            elif exercised is None:
                inconclusive.append(f"pair {pid}: target-state exercise is unknown")
            outcome = first(pair, "task_correct", "semantic_correct", "result", "evaluation_status")
            if outcome is None:
                inconclusive.append(f"pair {pid}: no behavioral correctness outcome was recorded")
            if _is_true(pair, "infra_error", "evaluator_error", "restore_error"):
                reasons.append(f"pair {pid}: evaluator/restore infrastructure error")
            if _is_true(pair, "task_correct", "semantic_correct") is False:
                negative = True
            result = str(first(pair, "result", "evaluation_status", default="")).upper()
            if result in {"FAIL", "FAILED", "SEMANTIC_FAIL", "INCORRECT"}:
                negative = True
            mutation_run_id = first(pair, "mutation_run_id")
            pristine_run_id = first(pair, "pristine_run_id")
            if nonempty_string(mutation_run_id):
                if str(mutation_run_id) in mutation_run_ids:
                    reasons.append(f"pair {pid}: duplicate mutation evaluation run ID")
                mutation_run_ids.add(str(mutation_run_id))
            if nonempty_string(pristine_run_id):
                if str(pristine_run_id) in pristine_run_ids:
                    reasons.append(f"pair {pid}: duplicate pristine evaluation run ID")
                pristine_run_ids.add(str(pristine_run_id))
            if nonempty_string(mutation_run_id) and str(mutation_run_id) in pristine_run_ids:
                reasons.append(f"pair {pid}: mutation and pristine run IDs collide")
        if reasons:
            return GateResult(Gate.G4, Status.INVALID_INFRA, reasons)
        if inconclusive:
            return GateResult(Gate.G4, Status.INCONCLUSIVE, inconclusive)
        if negative:
            return GateResult(Gate.G4, Status.VALID_NEGATIVE, ["official evaluator completed and observed semantic/task failure"])
        return GateResult(Gate.G4, Status.VALID_PASS, ["paired autonomous continuation and official evaluation verified"], {
            "pair_count": len(pairs),
            "mutation_run_ids": sorted(mutation_run_ids),
            "pristine_run_ids": sorted(pristine_run_ids),
        })

    def _gate_g5(self, a: dict[str, dict[str, Any]]) -> GateResult:
        report = a.get("storage_ram_report.json")
        if report is None:
            return GateResult(Gate.G5, Status.NOT_TESTED, ["storage_ram_report.json is absent"])
        if _status(first(report, "status")) is Status.NOT_TESTED:
            return GateResult(Gate.G5, Status.NOT_TESTED, ["accounting was explicitly not tested"])
        required = {
            "best_lossless_original_size": "best-lossless original size",
            "best_lossless_semantic_encoded_size": "semantic encoded size",
            "required_auxiliary_bytes": "required auxiliary bytes",
            "additional_reduction": "additional reduction",
        }
        values: dict[str, float] = {}
        reasons: list[str] = []
        for key, label in required.items():
            value = as_nonnegative_number(first(report, key))
            if value is None:
                reasons.append(f"missing/non-numeric {label}")
            else:
                values[key] = value
        if values.get("best_lossless_original_size", 0) <= 0:
            reasons.append("best-lossless original size must be positive")
        codec = first(report, "best_lossless_codec", "codec")
        if not nonempty_string(codec):
            reasons.append("best-lossless codec is not recorded")
        if _is_true(report, "memory_snap_used_as_ram", "used_memory_snap_file_size_as_ram"):
            reasons.append("memory.snap file size was used as physical RAM")
        # A report may carry either estimated or actual RAM values, but an
        # estimate must never be labelled as reclaimed Host RAM.
        ram_kind = str(first(report, "ram_measurement_kind", default="")).lower()
        actual = as_nonnegative_number(first(report, "actual_host_ram_reclaimed_bytes"))
        estimated = as_nonnegative_number(first(report, "estimated_reclaimable_bytes"))
        if actual is not None and ram_kind in {"estimated", "modeled", "projection"}:
            reasons.append("estimated RAM saving is labelled as actual Host reclamation")
        if actual is not None and estimated is not None and actual > estimated + _EPS:
            reasons.append("actual reclaimed RAM exceeds estimated reclaimable bytes")
        if reasons:
            return GateResult(Gate.G5, Status.INVALID_INFRA, reasons)
        original = values["best_lossless_original_size"]
        compact = values["best_lossless_semantic_encoded_size"] + values["required_auxiliary_bytes"]
        recomputed = 1.0 - compact / original
        reported = values["additional_reduction"]
        if not math.isclose(recomputed, reported, rel_tol=1e-7, abs_tol=1e-9):
            return GateResult(Gate.G5, Status.INVALID_INFRA, [
                f"additional_reduction mismatch: reported={reported:.12g}, recomputed={recomputed:.12g}"
            ], {"recomputed_additional_reduction": recomputed})
        if compact > original + _EPS or reported <= _EPS:
            return GateResult(Gate.G5, Status.VALID_NEGATIVE, ["accounting is valid but shows no additional reduction"], {
                "recomputed_additional_reduction": recomputed,
                "compact_bytes": compact,
            })
        return GateResult(Gate.G5, Status.VALID_PASS, ["storage formula and RAM accounting recomputed"], {
            "recomputed_additional_reduction": recomputed,
            "compact_bytes": compact,
            "codec": codec,
        })

    def _recomputed(self, a: dict[str, dict[str, Any]]) -> dict[str, Any]:
        report = a.get("storage_ram_report.json", {})
        original = as_nonnegative_number(first(report, "best_lossless_original_size"))
        semantic = as_nonnegative_number(first(report, "best_lossless_semantic_encoded_size"))
        aux = as_nonnegative_number(first(report, "required_auxiliary_bytes"))
        result: dict[str, Any] = {}
        if original and semantic is not None and aux is not None:
            result["best_lossless_compact_bytes"] = semantic + aux
            result["additional_reduction"] = 1.0 - (semantic + aux) / original
        return result


def validate_run(run_dir: str | Path) -> dict[str, Any]:
    """Convenience API returning a JSON-serialisable report dictionary."""

    return ArtifactValidator(run_dir).validate().as_dict()
