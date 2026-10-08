"""Command-line entry point for independent Stage 1 artifact validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .schema import Status
from .validator import ArtifactValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate one Stage 1 run directory")
    parser.add_argument("run_dir", type=Path, help="directory containing raw run artifacts")
    parser.add_argument(
        "--output",
        type=Path,
        help="optional path for the JSON validation report (stdout is always emitted)",
    )
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ArtifactValidator(args.run_dir).validate()
    payload = report.as_dict()
    rendered = json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    # Invalid infrastructure is a hard validator error.  All other statuses
    # are scientifically meaningful outcomes (including NOT_TESTED).
    return 2 if report.status is Status.INVALID_INFRA else 0


if __name__ == "__main__":
    sys.exit(main())
