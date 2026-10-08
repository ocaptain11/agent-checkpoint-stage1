#!/usr/bin/env python3
"""Prove that the pinned OpenHands SDK can call the candidate endpoint."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path
import time


def _dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_url": args.base_url,
        "model": args.model,
    }
    try:
        from openhands.sdk import LLM, Message
        from openhands.sdk.llm.message import TextContent

        llm = LLM(
            model=f"openai/{args.model}",
            api_key="EMPTY",
            base_url=args.base_url,
            temperature=0,
            top_p=1,
            max_output_tokens=64,
            timeout=120,
            num_retries=0,
            native_tool_calling=True,
            stream=False,
        )
        response = llm.completion(
            [Message(role="user", content=[TextContent(text="Reply with exactly OPENHANDS_ENDPOINT_OK.")])]
        )
        serialized = _dump(response)
        result["response"] = serialized
        result["python"] = sys.version
        result["executable"] = sys.executable
        result["sdk_version"] = importlib.metadata.version("openhands-sdk")
        result["response_text_contains_expected"] = "OPENHANDS_ENDPOINT_OK" in str(serialized)
        if not result["response_text_contains_expected"]:
            raise RuntimeError(f"OpenHands response did not contain OPENHANDS_ENDPOINT_OK: {serialized!r}")
        result["evidence_scope"] = "OpenHands SDK plain completion through endpoint; direct structured tool-call proof is recorded by qwen3_compat_probe"
        result["status"] = "PASS"
    except Exception as exc:  # noqa: BLE001 - preserve endpoint failure
        result["status"] = "INVALID_INFRA"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["error_type"] = type(exc).__name__
    result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
