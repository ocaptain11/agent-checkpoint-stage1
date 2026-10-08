#!/usr/bin/env python3
"""Read-only audit of Stage 1 cluster storage roots.

The program writes only JSON to stdout. It never creates probe files, changes
permissions, migrates data, or deletes anything.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
from typing import Any, Sequence


SCHEMA_VERSION = "stage1-storage-audit-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_text(value: str, limit: int = 32_768) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit] + "\n...[truncated]", True


def _run_read_only(command: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if executable is None:
        return {"status": "UNAVAILABLE", "command": list(command)}
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout, out_truncated = _bounded_text(exc.stdout or "")
        stderr, err_truncated = _bounded_text(exc.stderr or "")
        return {
            "status": "TIMEOUT",
            "command": list(command),
            "timeout_seconds": timeout_seconds,
            "stdout": stdout,
            "stderr": stderr,
            "output_truncated": out_truncated or err_truncated,
        }
    stdout, out_truncated = _bounded_text(completed.stdout)
    stderr, err_truncated = _bounded_text(completed.stderr)
    return {
        "status": "OK" if completed.returncode == 0 else "COMMAND_FAILED",
        "command": list(command),
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "output_truncated": out_truncated or err_truncated,
    }


def _path_report(
    path: Path,
    *,
    include_mount: bool,
    include_du: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    lexical = path.expanduser()
    report: dict[str, Any] = {
        "path": str(lexical),
        "exists": lexical.exists(),
    }
    if not lexical.exists():
        return report

    resolved = lexical.resolve(strict=True)
    stat = resolved.stat()
    usage = shutil.disk_usage(resolved)
    report.update(
        {
            "resolved_path": str(resolved),
            "is_directory": resolved.is_dir(),
            "uid": getattr(stat, "st_uid", None),
            "gid": getattr(stat, "st_gid", None),
            "mode_octal": oct(stat.st_mode & 0o7777),
            "access_reported": {
                "read": os.access(resolved, os.R_OK),
                "write": os.access(resolved, os.W_OK),
                "execute": os.access(resolved, os.X_OK),
                "note": "os.access only; no write probe was attempted",
            },
            "filesystem_capacity_bytes": {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
            },
        }
    )
    if include_mount:
        report["mount"] = _run_read_only(
            [
                "findmnt",
                "--json",
                "--target",
                str(resolved),
                "--output",
                "TARGET,SOURCE,FSTYPE,OPTIONS",
            ],
            timeout_seconds,
        )
    if include_du:
        report["top_level_usage"] = _run_read_only(
            ["du", "-x", "-B1", "--max-depth=1", str(resolved)],
            timeout_seconds,
        )
    return report


def audit_storage(
    home_root: Path,
    fact_data_root: Path,
    scratch_root: Path,
    *,
    user: str | None = None,
    include_mount: bool = True,
    include_du: bool = True,
    include_quota: bool = True,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Return a storage audit without modifying any filesystem state."""

    audited_user = user or getpass.getuser()
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collected_at_utc": _utc_now(),
        "identity": {
            "user": audited_user,
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
        "read_only_guarantee": {
            "write_probe_performed": False,
            "migration_performed": False,
            "cleanup_performed": False,
        },
        "storage_roots": {
            "HOME": _path_report(
                home_root,
                include_mount=include_mount,
                include_du=include_du,
                timeout_seconds=timeout_seconds,
            ),
            "FACT_DATA": _path_report(
                fact_data_root,
                include_mount=include_mount,
                include_du=include_du,
                timeout_seconds=timeout_seconds,
            ),
            "SCRATCH": _path_report(
                scratch_root,
                include_mount=include_mount,
                include_du=include_du,
                timeout_seconds=timeout_seconds,
            ),
        },
    }
    if include_quota:
        report["quota"] = _run_read_only(
            ["quota", "-s", "-u", audited_user], timeout_seconds
        )
    else:
        report["quota"] = {"status": "SKIPPED"}
    return report


def _parser() -> argparse.ArgumentParser:
    user = getpass.getuser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=user)
    parser.add_argument("--home-root", type=Path, default=Path(f"/fact_home/{user}"))
    parser.add_argument(
        "--fact-data-root", type=Path, default=Path(f"/fact_data/{user}")
    )
    parser.add_argument("--scratch-root", type=Path, default=Path(f"/scratch/{user}"))
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--skip-du", action="store_true")
    parser.add_argument("--skip-mount", action="store_true")
    parser.add_argument("--skip-quota", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    report = audit_storage(
        args.home_root,
        args.fact_data_root,
        args.scratch_root,
        user=args.user,
        include_mount=not args.skip_mount,
        include_du=not args.skip_du,
        include_quota=not args.skip_quota,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
