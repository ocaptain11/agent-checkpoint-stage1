# Import ledger

`import_manifest.json` is the authoritative ledger for dependencies copied
into this project. An entry in `inspected_sources` is evidence of a read-only
check only; it is not an import and must not become a runtime dependency.

Before adding an import, record its immutable source, version or commit,
SHA-256, license, purpose, and dependency constraints. Do not copy old
results, replay-history oracle outputs, synthetic conclusions, or unverified
benchmark artifacts. Update the manifest in the same change that adds the
files, then run the independent validator.

