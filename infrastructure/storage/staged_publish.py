#!/usr/bin/env python3
"""Compatibility entry point for the staged FACT_DATA publisher.

The implementation lives in :mod:`publish_evidence`; this name is kept
explicit because the protocol calls the operation staged-publish.
"""

try:
    from .publish_evidence import (  # type: ignore[attr-defined] # noqa: F401
        PolicyError,
        main,
        publish_evidence,
        tree_manifest,
        verify_published,
    )
except ImportError:  # Direct execution: python infrastructure/storage/staged_publish.py
    from publish_evidence import (  # type: ignore[no-redef] # noqa: F401
        PolicyError,
        main,
        publish_evidence,
        tree_manifest,
        verify_published,
    )


if __name__ == "__main__":
    raise SystemExit(main())
