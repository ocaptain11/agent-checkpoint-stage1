# Independent Stage 1 artifact validator

Run from the project root:

```bash
python -m oracle.validation runs/formal/<run-id> --pretty --output runs/formal/<run-id>/gate_results.json
```

The validator consumes raw JSON artifacts only. It does not trust narrative
claims and it never treats missing evidence as a pass. Its outcomes are:
`VALID_PASS`, `VALID_NEGATIVE`, `INCONCLUSIVE`, `INVALID_INFRA`, `NOT_TESTED`,
and `UNKNOWN`.

Gate meanings:

- G0: real OpenHands + vLLM + Firecracker pilot, full snapshot, fresh VMM,
  autonomous continuation, official evaluator, and no forbidden fallback.
- G1: FULL checkpoint and at least two independent pristine fresh restores.
- G2: verified native-object to virtual/physical/snapshot mapping.
- G3: independent mutations, byte bounds, target hit, untouched-region proof.
- G4: paired fresh restore, state exercise, autonomous continuation, official
  evaluator, and unique evaluation run IDs.
- G5: recomputed lossless/semantic sizes and strict separation of estimated
  reclaimable bytes from actual Host RAM reclamation.

The JSON schema file documents the artifact catalog, while the Python
validator implements the cross-artifact and arithmetic checks that plain JSON
Schema cannot express.
