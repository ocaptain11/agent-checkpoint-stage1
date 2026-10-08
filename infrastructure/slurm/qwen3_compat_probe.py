#!/usr/bin/env python3
"""Dependency-light OpenAI/vLLM and parser probes for the Stage 1 gate."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _request(base_url: str, path: str, payload: dict[str, Any] | None = None,
             timeout: float = 30.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
        method="GET" if body is None else "POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"HTTP request failed for {url}: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response from {url}: {raw[:500]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"response from {url} is not a JSON object")
    return value


def _message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"completion has no choices: {response}")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise RuntimeError(f"completion has no structured message: {response}")
    return message


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parser_probe() -> dict[str, Any]:
    import torch  # type: ignore
    import transformers  # type: ignore
    import vllm  # type: ignore
    from vllm.entrypoints.openai.tool_parsers import ToolParserManager  # type: ignore

    registry = getattr(ToolParserManager, "tool_parsers", None)
    if not isinstance(registry, dict):
        registry = dict(registry or {})
    names = sorted(str(name) for name in registry)
    if "qwen3_coder" not in names:
        raise RuntimeError(f"qwen3_coder is absent from ToolParserManager registry: {names}")
    parser_class = registry["qwen3_coder"]
    parser_source = inspect.getsourcefile(parser_class)
    if not parser_source:
        raise RuntimeError("qwen3_coder parser class has no inspectable source file")
    return {
        "python": sys.version,
        "vllm": getattr(vllm, "__version__", None),
        "torch": getattr(torch, "__version__", None),
        "torch_cuda": getattr(torch.version, "cuda", None),
        "transformers": getattr(transformers, "__version__", None),
        "parser_registry": names,
        "vllm_distribution": importlib.metadata.version("vllm"),
        "qwen3_coder_parser": repr(parser_class),
        "qwen3_coder_parser_module": getattr(parser_class, "__module__", None),
        "qwen3_coder_parser_qualname": getattr(parser_class, "__qualname__", None),
        "qwen3_coder_parser_source": parser_source,
        "qwen3_coder_parser_source_sha256": _sha256(Path(parser_source)),
    }


def api_probe(base_url: str, model: str) -> dict[str, Any]:
    models = _request(base_url, "/models")
    model_ids = [entry.get("id") for entry in models.get("data", []) if isinstance(entry, dict)]
    if model not in model_ids:
        raise RuntimeError(f"requested model is absent from /models: requested={model!r}, observed={model_ids!r}")
    chat = _request(
        base_url,
        "/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly READY."}],
            "temperature": 0,
            "top_p": 1,
            "seed": 20261008,
            "max_tokens": 32,
        },
    )
    simple_message = _message(chat)
    simple_text = str(simple_message.get("content") or "").strip()
    if simple_text != "READY":
        raise RuntimeError(f"simple completion did not return exact READY: {simple_message!r}")

    tools = [{
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Add two integers.",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
        },
    }]
    tool_response = _request(
        base_url,
        "/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": "Call add_numbers with a=2 and b=3. Do not answer directly."}],
            "tools": tools,
            "tool_choice": {"type": "function", "function": {"name": "add_numbers"}},
            "temperature": 0,
            "top_p": 1,
            "seed": 20261008,
            "max_tokens": 128,
        },
    )
    tool_message = _message(tool_response)
    calls = tool_message.get("tool_calls")
    choice = tool_response.get("choices", [{}])[0]
    if not isinstance(calls, list) or len(calls) != 1:
        raise RuntimeError(f"tool response must have exactly one structured tool call: {tool_response}")
    if not isinstance(choice, dict) or choice.get("finish_reason") != "tool_calls":
        raise RuntimeError(f"tool response finish_reason is not tool_calls: {tool_response}")
    call = calls[0]
    function = call.get("function") if isinstance(call, dict) else None
    if not isinstance(function, dict) or function.get("name") != "add_numbers":
        raise RuntimeError(f"unexpected parsed tool call: {tool_response}")
    if not isinstance(call.get("id"), str) or not call.get("id"):
        raise RuntimeError(f"tool call has no non-empty id: {tool_response}")
    if not isinstance(function.get("arguments"), str):
        raise RuntimeError(f"tool arguments are not a JSON string: {function}")
    try:
        arguments = json.loads(function.get("arguments", "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tool arguments are not JSON: {function}") from exc
    if arguments != {"a": 2, "b": 3}:
        raise RuntimeError(f"unexpected tool arguments: {arguments}")
    def add_numbers(a: int, b: int) -> int:
        return a + b

    result = add_numbers(**arguments)
    assistant_message = dict(tool_message)
    assistant_message["role"] = "assistant"
    follow_up = _request(
        base_url,
        "/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "user", "content": "Call add_numbers with a=2 and b=3."},
                assistant_message,
                {"role": "tool", "tool_call_id": call.get("id", "probe-call"), "name": "add_numbers", "content": str(result)},
            ],
            "tools": tools,
            "temperature": 0,
            "top_p": 1,
            "seed": 20261008,
            "max_tokens": 64,
        },
    )
    follow_up_message = _message(follow_up)
    follow_up_text = str(follow_up_message.get("content") or "").strip()
    if not follow_up_text or "5" not in follow_up_text:
        raise RuntimeError(f"follow-up completion does not contain the executed result: {follow_up}")
    return {
        "models": models,
        "simple_message": simple_message,
        "tool_message": tool_message,
        "tool_arguments": arguments,
        "executed_result": result,
        "follow_up_message": follow_up_message,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-parser", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_url": args.base_url,
        "model": args.model,
        "pid": os.getpid(),
    }
    try:
        result["parser"] = parser_probe()
        if args.model_parser:
            result["model_parser_path"] = str(args.model_parser)
            result["model_parser_sha256"] = _sha256(args.model_parser)
        result["api"] = api_probe(args.base_url, args.model)
        result["status"] = "PASS"
    except Exception as exc:  # noqa: BLE001 - preserve exact gate failure
        result["status"] = "INVALID_INFRA"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["error_type"] = type(exc).__name__
    result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
