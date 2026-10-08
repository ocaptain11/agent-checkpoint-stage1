# SWE-bench Verified source and sample

The formal sample is frozen in `../benchmark_preregistration.json`.

- Dataset: `princeton-nlp/SWE-bench_Verified`, test split, revision
  `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`.
- Pinned parquet SHA-256:
  `a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd`.
- Official evaluator: `SWE-bench/SWE-bench` commit
  `02e7a74ffd0b707aab73d203fe87bdc7c76afc8e`, entry point
  `swebench.harness.run_evaluation`.

Six repository/task pairs are selected by the published SHA-256 rule, with
Astropy included. Selection occurs before any Agent run and does not inspect
patch success, checkpoint contents, state prevalence, or semantic opportunity.
At evaluation time, use a unique `run_id` for every pristine/treatment branch;
the official harness caches by `run_id` and `instance_id`.

The manifest deliberately leaves runtime qualification pending. A task may
only consume formal checkpoint budget after its fixed base commit, environment
setup, official evaluator, and Guest execution path pass the independent
infrastructure gates.
