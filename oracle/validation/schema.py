"""Small, dependency-free schema helpers used by the independent validator.

This is deliberately not a permissive JSON-schema implementation.  Stage 1
artifacts are allowed to carry extra fields, but the fields used for a gate
must be explicit and type checked.  Missing evidence is reported as
``NOT_TESTED`` (or ``UNKNOWN`` where the artifact explicitly says so), never
as a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping
import json


class Status(str, Enum):
    VALID_PASS = "VALID_PASS"
    VALID_NEGATIVE = "VALID_NEGATIVE"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALID_INFRA = "INVALID_INFRA"
    NOT_TESTED = "NOT_TESTED"
    UNKNOWN = "UNKNOWN"


class Gate(str, Enum):
    G0 = "G0_PILOT_E2E"
    G1 = "G1_PRISTINE_FRESH_RESTORE"
    G2 = "G2_NATIVE_MAPPING"
    G3 = "G3_MUTATION_INTEGRITY"
    G4 = "G4_PAIRED_CONTINUATION_EVALUATION"
    G5 = "G5_ACCOUNTING_RECOMPUTATION"


REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "environment_manifest.json",
    "benchmark_manifest.json",
    "experiment_manifest.json",
    "mapping_report.json",
    "state_census.json",
    "mutation_results.json",
    "evaluation_results.json",
    "storage_ram_report.json",
    "failure_log.json",
)


@dataclass
class GateResult:
    gate: Gate
    status: Status
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate.value,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "evidence": self.evidence,
        }


@dataclass
class ValidationReport:
    run_dir: str
    run_id: str | None
    status: Status
    gates: list[GateResult]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recomputed: dict[str, Any] = field(default_factory=dict)
    storage: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_dir": self.run_dir,
            "run_id": self.run_id,
            "overall_status": self.status.value,
            "gates": [gate.as_dict() for gate in self.gates],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "recomputed": self.recomputed,
            "storage": self.storage,
        }


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read one JSON object, returning a stable error instead of raising."""

    if not path.exists():
        return None, f"missing artifact: {path.name}"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable artifact {path.name}: {exc}"
    if not isinstance(value, dict):
        return None, f"artifact {path.name} must contain a JSON object"
    return value, None


def first(mapping: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Return the first present key from a mapping."""

    if not mapping:
        return default
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def as_bool(value: Any) -> bool | None:
    """Parse strict-ish booleans; unknown values remain ``None``."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "pass", "passed", "ok", "valid"}:
            return True
        if lowered in {"false", "no", "fail", "failed", "invalid"}:
            return False
    return None


def as_nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def status_from(value: Any) -> Status | None:
    if isinstance(value, Status):
        return value
    if isinstance(value, str):
        try:
            return Status(value.strip().upper())
        except ValueError:
            return None
    return None


def merge_reasons(*groups: Iterable[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for item in group:
            if item and item not in result:
                result.append(item)
    return result
