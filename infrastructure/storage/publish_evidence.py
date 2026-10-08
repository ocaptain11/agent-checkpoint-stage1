#!/usr/bin/env python3
"""Safely stage, hash-verify, and publish retained Stage 1 evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePath
import shutil
import socket
from typing import Any, Iterable, Sequence
import uuid


MANIFEST_NAME = "_storage_manifest.json"
RECEIPT_NAME = "_storage_publish_receipt.json"
FAILURE_NAME = "_storage_publish_failure.json"
RESERVED_SOURCE_NAMES = {MANIFEST_NAME, RECEIPT_NAME, FAILURE_NAME}


class PolicyError(RuntimeError):
    """Raised when publication would violate the storage policy."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_forbidden_path(path: Path, label: str) -> None:
    # On Windows, Path('/data/...') is rendered as '\\data\\...' on the
    # current drive.  Normalize both the caller's spelling and the resolved
    # spelling so the policy remains testable and portable; the cluster
    # runtime is Linux, where the first branch is the relevant one.
    raw = str(path).replace("\\", "/").rstrip("/")
    normalized = path.expanduser().absolute().as_posix().rstrip("/")
    if (
        raw == "/data"
        or raw.startswith("/data/")
        or normalized == "/data"
        or normalized.startswith("/data/")
    ):
        raise PolicyError(f"{label} uses forbidden /data storage: {path}")


def _validate_relative_destination(value: PurePath) -> Path:
    if value.is_absolute() or not value.parts:
        raise PolicyError("relative destination must be a non-empty relative path")
    if any(part in {"", ".", ".."} for part in value.parts):
        raise PolicyError("relative destination contains traversal or empty components")
    if value.parts[0] in {".staging", ".publish-locks"}:
        raise PolicyError("relative destination uses a reserved internal directory")
    return Path(*value.parts)


def _validate_source(source: Path) -> Path:
    _reject_forbidden_path(source, "source")
    if not source.exists():
        raise PolicyError(f"source does not exist: {source}")
    resolved = source.resolve(strict=True)
    _reject_forbidden_path(resolved, "resolved source")
    if source.is_symlink():
        raise PolicyError("source symlinks are not allowed")
    if resolved.is_dir():
        for entry in resolved.rglob("*"):
            if entry.is_symlink():
                raise PolicyError(f"source contains symlink: {entry}")
        collisions = RESERVED_SOURCE_NAMES.intersection(
            child.name for child in resolved.iterdir()
        )
        if collisions:
            raise PolicyError(
                "source root contains reserved publisher files: "
                + ", ".join(sorted(collisions))
            )
    elif resolved.name in RESERVED_SOURCE_NAMES:
        raise PolicyError(f"source file uses reserved name: {resolved.name}")
    elif not resolved.is_file():
        raise PolicyError("source must be a regular file or directory")
    return resolved


def _validate_fact_data_root(
    root: Path, *, user: str, enforce_cluster_root: bool
) -> Path:
    _reject_forbidden_path(root, "FACT_DATA root")
    if enforce_cluster_root:
        allowed = Path(f"/fact_data/{user}").absolute()
        requested = root.expanduser().absolute()
        if not _is_relative_to(requested, allowed):
            raise PolicyError(
                f"FACT_DATA root must be inside {allowed}; got {requested}"
            )
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve(strict=True)
    _reject_forbidden_path(resolved, "resolved FACT_DATA root")
    if enforce_cluster_root:
        allowed_resolved = Path(f"/fact_data/{user}").resolve(strict=False)
        if not _is_relative_to(resolved, allowed_resolved):
            raise PolicyError(
                "resolved FACT_DATA root escaped its allowed user root; "
                f"expected {allowed_resolved}, got {resolved}"
            )
    if not resolved.is_dir():
        raise PolicyError(f"FACT_DATA root is not a directory: {resolved}")
    return resolved


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_regular_files(root: Path, *, ignore_control_files: bool) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise PolicyError(f"symlink encountered while hashing: {path}")
        if not path.is_file():
            continue
        if ignore_control_files and path.parent == root and path.name in RESERVED_SOURCE_NAMES:
            continue
        yield path


def tree_manifest(root: Path, *, ignore_control_files: bool = False) -> dict[str, Any]:
    """Hash every regular file and return a canonical tree digest."""

    resolved = root.resolve(strict=True)
    entries: list[dict[str, Any]] = []
    for path in _iter_regular_files(resolved, ignore_control_files=ignore_control_files):
        relative = path.name if resolved.is_file() else path.relative_to(resolved).as_posix()
        entries.append(
            {"relative_path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)}
        )
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "file_count": len(entries),
        "total_bytes": sum(entry["bytes"] for entry in entries),
        "tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": entries,
    }


def _same_tree(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = ("file_count", "total_bytes", "tree_sha256", "files")
    return all(left.get(key) == right.get(key) for key in keys)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _copy_payload(source: Path, payload: Path) -> None:
    payload.mkdir(parents=False, exist_ok=False)
    if source.is_file():
        shutil.copy2(source, payload / source.name)
        return
    for child in source.iterdir():
        target = payload / child.name
        if child.is_dir():
            shutil.copytree(child, target, symlinks=False)
        else:
            shutil.copy2(child, target)


def verify_published(destination: Path) -> dict[str, Any]:
    """Recompute a published tree and require its verification receipt."""

    resolved = destination.resolve(strict=True)
    manifest_path = resolved / MANIFEST_NAME
    receipt_path = resolved / RECEIPT_NAME
    if not manifest_path.is_file() or not receipt_path.is_file():
        raise PolicyError("published directory lacks manifest or VERIFIED receipt")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    observed = tree_manifest(resolved, ignore_control_files=True)
    expected = manifest.get("data_manifest")
    if not isinstance(expected, dict) or not _same_tree(expected, observed):
        raise PolicyError("published bytes no longer match the recorded data manifest")
    if receipt.get("status") != "VERIFIED" or receipt.get("tree_sha256") != observed["tree_sha256"]:
        raise PolicyError("published verification receipt is missing or inconsistent")
    return observed


def publish_evidence(
    source: Path,
    fact_data_root: Path,
    relative_destination: PurePath,
    *,
    user: str | None = None,
    job_id: str | None = None,
    artifact_id: str | None = None,
    regenerable: bool = False,
    rebuild_steps: Sequence[str] = (),
    enforce_cluster_root: bool = True,
) -> dict[str, Any]:
    """Publish an immutable source tree through verified FACT_DATA staging.

    `enforce_cluster_root=False` exists for isolated unit tests only. The CLI
    never disables cluster-root enforcement.
    """

    audited_user = user or getpass.getuser()
    resolved_source = _validate_source(source)
    root = _validate_fact_data_root(
        fact_data_root, user=audited_user, enforce_cluster_root=enforce_cluster_root
    )
    if _is_relative_to(resolved_source, root):
        raise PolicyError("source must not be inside the authoritative FACT_DATA root")

    relative = _validate_relative_destination(relative_destination)
    final = (root / relative).resolve(strict=False)
    if not _is_relative_to(final, root):
        raise PolicyError("destination escapes FACT_DATA root")
    _reject_forbidden_path(final, "destination")
    if final.exists():
        raise PolicyError(f"destination already exists; overwrite is forbidden: {final}")

    staging_root = root / ".staging"
    lock_root = root / ".publish-locks"
    staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)

    destination_key = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()
    lock_path = lock_root / f"{destination_key}.lock"
    run_token = uuid.uuid4().hex
    stage = staging_root / f"{destination_key[:16]}-{run_token}"
    stage.mkdir(mode=0o700, parents=False, exist_ok=False)
    payload = stage / "payload"

    lock_handle = None
    lock_acquired = False
    try:
        try:
            lock_handle = lock_path.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise PolicyError(f"another publisher holds destination lock: {lock_path}") from exc
        lock_acquired = True
        json.dump(
            {
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "destination": relative.as_posix(),
                "created_at_utc": _utc_now(),
            },
            lock_handle,
            sort_keys=True,
        )
        lock_handle.flush()
        os.fsync(lock_handle.fileno())

        before = tree_manifest(resolved_source)
        _copy_payload(resolved_source, payload)
        after = tree_manifest(resolved_source)
        staged = tree_manifest(payload)
        if not _same_tree(before, after):
            raise PolicyError("source changed while it was being copied")
        if not _same_tree(before, staged):
            raise PolicyError("staged copy failed SHA-256/size verification")

        manifest = {
            "schema_version": "stage1-storage-publish-v1",
            "artifact_id": artifact_id or relative.as_posix(),
            "created_at_utc": _utc_now(),
            "user": audited_user,
            "host": socket.gethostname(),
            "job_id": job_id,
            "source_path": str(resolved_source),
            "destination_path": str(final),
            "storage_class": "FACT_DATA",
            "regenerable": regenerable,
            "rebuild_steps": list(rebuild_steps),
            "source_preserved": True,
            "copy_protocol": "source-before/source-after/staged SHA-256 equality",
            "data_manifest": staged,
        }
        _write_json_atomic(payload / MANIFEST_NAME, manifest)

        if os.stat(stage).st_dev != os.stat(final.parent).st_dev:
            raise PolicyError("staging and final destination are not on the same filesystem")
        if final.exists():
            raise PolicyError("destination appeared during staging; refusing overwrite")
        # Both paths are within FACT_DATA.  The destination lock serializes
        # this publisher and the existence check prevents an intentional
        # overwrite.  os.rename is atomic on the same filesystem.
        os.rename(payload, final)
        stage.rmdir()

        published = tree_manifest(final, ignore_control_files=True)
        if not _same_tree(staged, published):
            raise PolicyError("published tree failed post-rename SHA-256/size verification")
        receipt = {
            "schema_version": "stage1-storage-publish-receipt-v1",
            "status": "VERIFIED",
            "verified_at_utc": _utc_now(),
            "destination_path": str(final),
            "file_count": published["file_count"],
            "total_bytes": published["total_bytes"],
            "tree_sha256": published["tree_sha256"],
            "source_preserved": resolved_source.exists(),
        }
        _write_json_atomic(final / RECEIPT_NAME, receipt)
        verify_published(final)
        return receipt
    except Exception as exc:
        failure = {
            "schema_version": "stage1-storage-publish-failure-v1",
            "status": "FAILED_STAGING",
            "failed_at_utc": _utc_now(),
            "source_path": str(resolved_source),
            "intended_destination": str(final),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "note": "staging or incomplete publication retained for audit; source was not deleted",
        }
        failure_root = stage if stage.exists() else (final if final.exists() else None)
        if failure_root is not None and not (failure_root / RECEIPT_NAME).exists():
            try:
                _write_json_atomic(failure_root / FAILURE_NAME, failure)
            except OSError:
                pass
        raise
    finally:
        if lock_handle is not None:
            lock_handle.close()
        if lock_acquired:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


def _parser() -> argparse.ArgumentParser:
    user = getpass.getuser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--fact-data-root",
        type=Path,
        default=Path(f"/fact_data/{user}/agent-checkpoint-stage1"),
    )
    parser.add_argument("--relative-destination", required=True, type=Path)
    parser.add_argument("--user", default=user)
    parser.add_argument("--job-id")
    parser.add_argument("--artifact-id")
    parser.add_argument("--regenerable", action="store_true")
    parser.add_argument("--rebuild-step", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = publish_evidence(
        args.source,
        args.fact_data_root,
        args.relative_destination,
        user=args.user,
        job_id=args.job_id,
        artifact_id=args.artifact_id,
        regenerable=args.regenerable,
        rebuild_steps=args.rebuild_step,
        enforce_cluster_root=True,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
