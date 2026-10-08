"""Run or plan the Stage 1 engineering pilot.

The pilot is deliberately command-driven: an operator supplies concrete
commands for the real vLLM service, OpenHands headless agent, Firecracker
snapshot/restore, and official evaluator.  The default mode is ``--plan``;
``--execute`` is required before any external process is started.  Every
step writes raw stdout/stderr and exit status into the run directory.  A pilot
is marked PILOT_PASS only when all required evidence is observed, not merely because
commands were configured.

Example::

    python pilot/pilot_runner.py \
      --config infrastructure/openhands/pilot_config.example.json \
      --run-dir runs/pilot/pilot-001 --execute

The example configuration is intentionally incomplete and therefore plans but
does not pass until an operator fills in actual paths, endpoints, and commands.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable
from urllib.error import URLError
from urllib.request import urlopen


REQUIRED_EVIDENCE = (
    "openhands_started",
    "vllm_started",
    "firecracker_started",
    "guest_tool_execution",
    "checkpoint_created",
    "fresh_restore",
    "original_vmm_terminated",
    "host_prefix_restored",
    "tool_reconnected",
    "autonomous_continuation",
    "official_evaluator",
)


@dataclass
class CommandResult:
    name: str
    command: list[str]
    returncode: int | None
    started_at: float | None
    ended_at: float | None
    log_path: str | None
    error: str | None = None
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "returncode": self.returncode,
            "started_at_epoch": self.started_at,
            "ended_at_epoch": self.ended_at,
            "log_path": self.log_path,
            "error": self.error,
            "timed_out": self.timed_out,
        }


@dataclass
class PilotState:
    run_id: str
    run_dir: Path
    evidence: dict[str, Any] = field(default_factory=dict)
    commands: list[CommandResult] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    services: dict[str, subprocess.Popen[Any]] = field(default_factory=dict)
    restored_vmm_pid: int | None = None

    def __post_init__(self) -> None:
        for key in REQUIRED_EVIDENCE:
            self.evidence.setdefault(key, False)
        self.evidence.setdefault("action_count", 0)
        self.evidence.setdefault("guest_actions", [])
        self.evidence.setdefault("status", "NOT_TESTED")


def _load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read pilot config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("pilot config must be a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_command(value: Any, name: str) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return list(value)
    if isinstance(value, str) and value.strip():
        return shlex.split(value)
    raise ValueError(f"{name} must be a non-empty command list/string")


def _unresolved(command: Iterable[str]) -> list[str]:
    unresolved: list[str] = []
    for token in command:
        if "<" in token or ">" in token or "${" in token or "REPLACE_ME" in token:
            unresolved.append(token)
    return unresolved


def _resolve_executable(command: list[str]) -> str | None:
    executable = command[0]
    if os.path.sep in executable or (os.path.altsep and os.path.altsep in executable):
        return executable if Path(executable).exists() else None
    return shutil.which(executable)


def _now() -> float:
    return time.time()


def _http_ready(url: str, timeout: float) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:  # nosec B310 - operator supplies endpoint
            return 200 <= int(response.status) < 500
    except (OSError, URLError, ValueError):
        return False


class PilotRunner:
    def __init__(self, config: dict[str, Any], run_dir: Path):
        self.config = config
        self.run_dir = run_dir
        self.run_id = str(config.get("run_id") or run_dir.name)
        self.state = PilotState(self.run_id, run_dir)
        self.logs_dir = run_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def plan(self) -> dict[str, Any]:
        """Return a plan without launching any process."""

        steps = self._step_commands()
        plan = {
            "run_id": self.run_id,
            "mode": "plan",
            "steps": [
                {"name": name, "command": command, "unresolved": _unresolved(command)}
                for name, command in steps
            ],
            "warning": "No command was executed; this cannot establish PILOT_PASS.",
        }
        _write_json(self.run_dir / "pilot_plan.json", plan)
        return plan

    def execute(self) -> dict[str, Any]:
        """Execute configured real commands and write evidence artifacts."""

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state.evidence["execution_started_at_epoch"] = _now()
        try:
            self._preflight()
            self._start_services()
            self._run_agent()
            self._checkpoint()
            self._fresh_restore()
            self._continue_agent()
            self._evaluate()
        except Exception as exc:  # keep evidence and failure logs durable
            self.state.failures.append({"category": "infrastructure", "step": "runner", "error": str(exc)})
        finally:
            self._stop_services()
            self.state.evidence["execution_ended_at_epoch"] = _now()
            self._finalize()
        return self.state.evidence

    def _step_commands(self) -> list[tuple[str, list[str]]]:
        steps: list[tuple[str, list[str]]] = []
        for section, key in (
            ("vllm", "start_command"),
            ("firecracker", "start_command"),
            ("openhands", "run_command"),
            ("checkpoint", "command"),
            ("restore", "command"),
            ("continuation", "run_command"),
            ("evaluator", "command"),
        ):
            value = self.config.get(section, {})
            if isinstance(value, dict) and value.get(key):
                steps.append((f"{section}.{key}", _as_command(value[key], f"{section}.{key}")))
        return steps

    def _preflight(self) -> None:
        if not self.config.get("real_guest_required", True):
            raise ValueError("real_guest_required must remain true; synthetic/local fallback is forbidden")
        if self.config.get("guest_fallback", False):
            raise ValueError("guest_fallback is forbidden")
        if self.config.get("manual_replay", False):
            raise ValueError("manual_replay is forbidden")
        if self.config.get("gold_patch_injected", False):
            raise ValueError("gold_patch_injected is forbidden")
        if not self.config.get("official_evaluator", True):
            raise ValueError("official_evaluator must remain true")
        for name, command in self._step_commands():
            unresolved = _unresolved(command)
            if unresolved:
                raise ValueError(f"{name} contains unresolved placeholders: {unresolved}")
            if _resolve_executable(command) is None:
                raise ValueError(f"executable unavailable for {name}: {command[0]}")
        firecracker = self.config.get("firecracker", {})
        if isinstance(firecracker, dict) and firecracker.get("require_kvm", True):
            kvm_path = Path(str(firecracker.get("kvm_path", "/dev/kvm")))
            if not kvm_path.exists():
                raise ValueError(f"required KVM device is unavailable: {kvm_path}")

    def _start_services(self) -> None:
        self._start_service("vllm", "start_command", "vllm_started")
        self._wait_health("vllm")
        self._start_service("firecracker", "start_command", "firecracker_started")
        self._wait_socket("firecracker")

    def _start_service(self, section: str, key: str, evidence_key: str) -> None:
        config = self.config.get(section, {})
        if not isinstance(config, dict) or not config.get(key):
            raise ValueError(f"missing {section}.{key}")
        command = _as_command(config[key], f"{section}.{key}")
        log_path = self.logs_dir / f"{section}.service.log"
        stream = log_path.open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, cwd=config.get("cwd") or None)
        except Exception:
            stream.close()
            raise
        self.state.services[section] = process
        if section == "firecracker":
            self.state.evidence["original_vmm_pid"] = process.pid
        self.state.evidence[evidence_key] = process.poll() is None
        self.state.commands.append(CommandResult(section, command, None, _now(), None, str(log_path)))

    def _wait_health(self, section: str) -> None:
        config = self.config.get(section, {})
        if not isinstance(config, dict):
            return
        url = config.get("health_url")
        if not url:
            # A running process alone is not enough to prove vLLM readiness;
            # require explicit opt-in for command-only health evidence.
            if config.get("allow_process_ready_evidence", False):
                self.state.evidence["vllm_started"] = True
                return
            raise ValueError(f"{section}.health_url is required")
        timeout = float(config.get("health_timeout_seconds", 60))
        deadline = _now() + timeout
        while _now() < deadline:
            process = self.state.services.get(section)
            if process is not None and process.poll() is not None:
                raise ValueError(f"{section} exited before health check (code {process.returncode})")
            if _http_ready(str(url), min(5.0, max(0.1, deadline - _now()))):
                self.state.evidence["vllm_started"] = True
                return
            time.sleep(0.5)
        raise TimeoutError(f"health check timed out for {section}: {url}")

    def _wait_socket(self, section: str) -> None:
        config = self.config.get(section, {})
        socket_path = config.get("socket_path") if isinstance(config, dict) else None
        if not socket_path:
            if isinstance(config, dict) and config.get("allow_process_ready_evidence", False):
                self.state.evidence["firecracker_started"] = True
                return
            raise ValueError("firecracker.socket_path is required")
        timeout = float(config.get("socket_timeout_seconds", 30))
        deadline = _now() + timeout
        path = Path(str(socket_path))
        while _now() < deadline:
            if path.exists():
                self.state.evidence["firecracker_started"] = True
                return
            process = self.state.services.get(section)
            if process is not None and process.poll() is not None:
                raise ValueError(f"Firecracker exited before socket appeared (code {process.returncode})")
            time.sleep(0.25)
        raise TimeoutError(f"Firecracker API socket did not appear: {path}")

    def _run_agent(self) -> None:
        section = self.config.get("openhands", {})
        if not isinstance(section, dict) or not section.get("run_command"):
            raise ValueError("missing openhands.run_command")
        result = self._run_command("openhands", section["run_command"], section)
        if result.returncode != 0:
            raise RuntimeError(f"OpenHands exited with code {result.returncode}")
        # The command must emit machine-readable guest action evidence.  A
        # local process exit alone cannot establish real Guest execution.
        action_file = section.get("action_log")
        if not action_file:
            raise ValueError("openhands.action_log is required")
        action_path = Path(str(action_file))
        if not action_path.exists():
            raise ValueError(f"OpenHands action log missing: {action_path}")
        try:
            actions = json.loads(action_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid OpenHands action log: {exc}") from exc
        if not isinstance(actions, list) or not actions:
            raise ValueError("OpenHands action log contains no Guest actions")
        self._validate_action_records(actions, "pre-checkpoint")
        self.state.evidence["guest_tool_execution"] = True
        self.state.evidence["guest_actions"] = actions
        self.state.evidence["action_count"] = len(actions)
        self.state.evidence["openhands_started"] = True

    def _checkpoint(self) -> None:
        section = self.config.get("checkpoint", {})
        if not isinstance(section, dict) or not section.get("command"):
            raise ValueError("missing checkpoint.command")
        result = self._run_command("checkpoint", section["command"], section)
        if result.returncode != 0:
            raise RuntimeError(f"checkpoint command exited with code {result.returncode}")
        required = [section.get("memory_snap"), section.get("vmstate_snap"), section.get("disk_state"), section.get("host_agent_prefix")]
        missing = [str(item) for item in required if not item or not Path(str(item)).exists()]
        if missing:
            raise ValueError(f"checkpoint artifacts missing: {missing}")
        self.state.evidence["checkpoint_created"] = True
        self.state.evidence["checkpoint_id"] = section.get("checkpoint_id", self.run_id)
        self.state.evidence["checkpoint_artifacts"] = [str(item) for item in required]

    def _fresh_restore(self) -> None:
        original_process = self.state.services.get("firecracker")
        original_pid = original_process.pid if original_process is not None else None
        terminate = self.config.get("terminate_original_vmm_command")
        if terminate:
            result = self._run_command("terminate_original_vmm", terminate, {})
            if result.returncode != 0:
                raise RuntimeError(f"original VMM termination exited with code {result.returncode}")
        elif self.config.get("require_explicit_vmm_termination", True):
            raise ValueError("explicit terminate_original_vmm_command is required")
        if original_process is not None:
            try:
                original_process.wait(timeout=10)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("original Firecracker process is still alive after termination") from exc
        self.state.evidence["original_vmm_terminated"] = True
        section = self.config.get("restore", {})
        if not isinstance(section, dict) or not section.get("command"):
            raise ValueError("missing restore.command")
        result = self._run_command("restore", section["command"], section)
        if result.returncode != 0:
            raise RuntimeError(f"fresh restore command exited with code {result.returncode}")
        pid_file = section.get("new_vmm_pid_file")
        if not pid_file or not Path(str(pid_file)).exists():
            raise ValueError("restore.new_vmm_pid_file is required and must exist")
        try:
            new_pid = int(Path(str(pid_file)).read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            raise ValueError("restore.new_vmm_pid_file does not contain an integer PID") from exc
        if new_pid <= 0 or (original_pid is not None and new_pid == original_pid):
            raise ValueError("fresh restore did not produce a distinct VMM PID")
        evidence_file = section.get("evidence_file")
        if not evidence_file or not Path(str(evidence_file)).exists():
            raise ValueError("restore.evidence_file is required")
        try:
            restore_evidence = json.loads(Path(str(evidence_file)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid restore evidence file: {exc}") from exc
        if not isinstance(restore_evidence, dict):
            raise ValueError("restore evidence must be a JSON object")
        if restore_evidence.get("host_prefix_restored") is not True:
            raise ValueError("restore evidence does not confirm Host Agent prefix restoration")
        if restore_evidence.get("tool_reconnected") is not True:
            raise ValueError("restore evidence does not confirm Host–Guest tool reconnection")
        self.state.evidence["fresh_restore"] = True
        self.state.evidence["host_prefix_restored"] = True
        self.state.evidence["tool_reconnected"] = True
        self.state.evidence["new_vmm_pid"] = new_pid
        self.state.restored_vmm_pid = new_pid

    def _continue_agent(self) -> None:
        section = self.config.get("continuation", {})
        if not isinstance(section, dict) or not section.get("run_command"):
            raise ValueError("missing continuation.run_command")
        result = self._run_command("continuation", section["run_command"], section)
        if result.returncode != 0:
            raise RuntimeError(f"Agent continuation exited with code {result.returncode}")
        action_file = section.get("action_log")
        if not action_file or not Path(str(action_file)).exists():
            raise ValueError("continuation.action_log is required")
        try:
            actions = json.loads(Path(str(action_file)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid continuation action log: {exc}") from exc
        if not isinstance(actions, list) or not actions:
            raise ValueError("continuation action log contains no post-restore actions")
        self._validate_action_records(actions, "post-restore")
        self.state.evidence["autonomous_continuation"] = True
        self.state.evidence["continuation_actions"] = actions

    def _validate_action_records(self, actions: list[Any], label: str) -> None:
        """Require machine-readable, real Guest action and raw-log evidence."""

        invalid: list[str] = []
        for index, item in enumerate(actions):
            if not isinstance(item, dict):
                invalid.append(f"{label} action {index} is not an object")
                continue
            if not item.get("guest_pid") or not isinstance(item.get("guest_pid"), int):
                invalid.append(f"{label} action {index} lacks positive guest_pid")
            if not item.get("action_id"):
                invalid.append(f"{label} action {index} lacks action_id")
            if item.get("execution_location") not in {"guest", "firecracker_guest"}:
                invalid.append(f"{label} action {index} is not Guest execution")
            raw_log = item.get("raw_log") or item.get("log_path")
            if not isinstance(raw_log, str) or not raw_log.strip():
                invalid.append(f"{label} action {index} lacks raw_log path")
            else:
                raw_path = Path(raw_log)
                if not raw_path.is_absolute():
                    raw_path = self.run_dir / raw_path
                if not raw_path.exists():
                    invalid.append(f"{label} action {index} raw log is missing: {raw_log}")
        if invalid:
            raise ValueError("; ".join(invalid))

    def _evaluate(self) -> None:
        section = self.config.get("evaluator", {})
        if not isinstance(section, dict) or not section.get("command"):
            raise ValueError("missing evaluator.command")
        result = self._run_command("evaluator", section["command"], section)
        output = section.get("result_file")
        if result.returncode != 0 and (not output or not Path(str(output)).exists()):
            raise RuntimeError(f"official evaluator failed without a result artifact (code {result.returncode})")
        if not output or not Path(str(output)).exists():
            raise ValueError("evaluator.result_file is required")
        try:
            evaluator_result = json.loads(Path(str(output)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid evaluator result JSON: {exc}") from exc
        if not isinstance(evaluator_result, dict):
            raise ValueError("evaluator result must be a JSON object")
        self.state.evidence["official_evaluator"] = True
        self.state.evidence["evaluator_result_file"] = str(output)

    def _run_command(self, name: str, command_value: Any, section: dict[str, Any]) -> CommandResult:
        command = _as_command(command_value, name)
        log_path = self.logs_dir / f"{name}.log"
        timeout = float(section.get("timeout_seconds", self.config.get("command_timeout_seconds", 3600)))
        started = _now()
        try:
            completed = subprocess.run(
                command,
                stdout=log_path.open("w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                cwd=section.get("cwd") or None,
                env={**os.environ, **{str(k): str(v) for k, v in (section.get("env") or {}).items()}},
                timeout=timeout,
                check=False,
            )
            result = CommandResult(name, command, completed.returncode, started, _now(), str(log_path))
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(name, command, None, started, _now(), str(log_path), str(exc), timed_out=True)
        except OSError as exc:
            result = CommandResult(name, command, None, started, _now(), str(log_path), str(exc))
        self.state.commands.append(result)
        if result.returncode not in (0, None):
            self.state.failures.append({"category": "infrastructure", "step": name, "error": f"exit code {result.returncode}"})
        if result.error:
            self.state.failures.append({"category": "infrastructure", "step": name, "error": result.error})
        return result

    def _stop_services(self) -> None:
        restored_pid = self.state.restored_vmm_pid
        if isinstance(restored_pid, int) and restored_pid > 0:
            try:
                os.kill(restored_pid, 15)
                deadline = _now() + 10
                while _now() < deadline:
                    try:
                        os.kill(restored_pid, 0)
                    except OSError:
                        break
                    time.sleep(0.1)
                else:
                    os.kill(restored_pid, 9)
                self.state.evidence.setdefault("service_shutdown", {})["restored_firecracker"] = True
            except OSError as exc:
                self.state.evidence.setdefault("service_shutdown", {})["restored_firecracker"] = False
                self.state.failures.append({"category": "infrastructure", "step": "cleanup", "error": f"restored VMM cleanup failed: {exc}"})
        for name, process in self.state.services.items():
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
            self.state.evidence.setdefault("service_shutdown", {})[name] = process.poll() is not None

    def _finalize(self) -> None:
        self.state.evidence["manual_replay"] = bool(self.config.get("manual_replay", False))
        self.state.evidence["guest_fallback"] = bool(self.config.get("guest_fallback", False))
        self.state.evidence["gold_patch_injected"] = bool(self.config.get("gold_patch_injected", False))
        complete = all(bool(self.state.evidence.get(key)) for key in REQUIRED_EVIDENCE)
        if self.state.failures or not complete:
            self.state.evidence["status"] = "INVALID_INFRA" if self.state.failures else "NOT_TESTED"
        else:
            # Protocol terminology is explicit: the engineering pilot gate is
            # PILOT_PASS, distinct from formal VALID_PASS branch outcomes.
            self.state.evidence["status"] = "PILOT_PASS"
        _write_json(self.run_dir / "pilot_evidence.json", self.state.evidence)
        _write_json(self.run_dir / "failure_log.json", {"failures": self.state.failures})
        _write_json(
            self.run_dir / "environment_manifest.json",
            {
                "run_id": self.run_id,
                "run_kind": "pilot",
                "host": os.environ.get("HOSTNAME") or os.environ.get("COMPUTERNAME"),
                "python": sys.version,
                "cwd": os.getcwd(),
                "config_path": self.config.get("config_path"),
                "vllm_endpoint": (self.config.get("vllm") or {}).get("health_url") if isinstance(self.config.get("vllm"), dict) else None,
                "firecracker_kvm_path": (self.config.get("firecracker") or {}).get("kvm_path") if isinstance(self.config.get("firecracker"), dict) else None,
            },
        )
        _write_json(
            self.run_dir / "benchmark_manifest.json",
            {
                "benchmark": self.config.get("benchmark", "swebench_verified"),
                "task_id": self.config.get("task_id"),
                "official_evaluator": bool(self.config.get("official_evaluator", True)),
            },
        )
        _write_json(
            self.run_dir / "pilot_command_log.json",
            {"commands": [result.as_dict() for result in self.state.commands]},
        )
        _write_json(
            self.run_dir / "experiment_manifest.json",
            {
                "run_id": self.run_id,
                "run_kind": "pilot",
                "pilot_evidence": self.state.evidence,
                "config_path": self.config.get("config_path"),
            },
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan/execute a real Stage 1 OpenHands pilot")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="launch configured external processes")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = _load_config(args.config)
        config["config_path"] = str(args.config.resolve())
        runner = PilotRunner(config, args.run_dir)
        if not args.execute:
            payload = runner.plan()
            print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
            return 0
        payload = runner.execute()
        print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
        return 0 if payload.get("status") == "PILOT_PASS" else 2
    except Exception as exc:
        args.run_dir.mkdir(parents=True, exist_ok=True)
        failure = {"status": "INVALID_INFRA", "failures": [{"category": "infrastructure", "step": "config", "error": str(exc)}]}
        _write_json(args.run_dir / "pilot_evidence.json", failure)
        _write_json(args.run_dir / "failure_log.json", failure)
        print(json.dumps(failure, indent=2 if args.pretty else None, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
