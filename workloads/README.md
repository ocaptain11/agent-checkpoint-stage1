# Stage 1 benchmark preregistration

`benchmark_preregistration.json` is the frozen sample contract for the formal
Stage 1 study. It is deliberately separate from run-time manifests: a task may
be listed here and still be `PENDING` or `BLOCKED` until the independent
qualification gates pass.

## SWE-bench Verified

The sample is pinned to the official `test` split at dataset revision
`c104f840cc67f8b6eec6f759ebc8b2693d585d4a` (500 rows; parquet SHA-256 is in
the manifest) and the official SWE-bench evaluator at commit
`02e7a74ffd0b707aab73d203fe87bdc7c76afc8e`. Six repositories are selected by a
published SHA-256 rule and one instance per selected repository is selected by
the same kind of rule. This is reproducible without inspecting task outcomes.
Astropy is explicitly included, and the manifest records base commits and
dataset versions. The evaluator must report `resolved`, FAIL_TO_PASS,
PASS_TO_PASS, patch validity, tool errors, and live continuation evidence.

## DSBench Modeling

The source catalog is pinned to `LiqiangJing/DSBench` commit
`ba786096137a5108af11c016ad3f09cdb97beefd`; its catalog has 74 competitions
and its official tree contains per-competition evaluator scripts. Six names
are fixed in advance to cover classification and several numeric metrics.

The formal status is currently **BLOCKED**, not a scientific negative: the
public processed archive is about 3.13 GB, labels have not been verified, and
the unauthenticated Kaggle API returned HTTP 401 on the remote host. The source
evaluators are evidence of the intended metric only. No DSBench task may
consume checkpoint or mutation budget until the data, labels, Guest
dependencies, and evaluator smoke tests all pass. Do not replace blocked tasks
based on convenience, success, or observed semantic opportunity.

The blocking record is intentionally retained in the manifest so a later run
can resolve it without silently changing the sample.
