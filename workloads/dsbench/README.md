# DSBench Modeling source audit

The formal DSBench sample is frozen in
`../benchmark_preregistration.json`. This directory contains source-audit
evidence only; it is not a copy of the 3.1 GB dataset and does not provide
synthetic labels.

The official DSBench repository at commit
`ba786096137a5108af11c016ad3f09cdb97beefd` publishes a 74-entry
`data_modeling/data.json` catalog and one evaluator script per competition.
The six pre-registered tasks and their metrics are recorded in
`verification_record.json`:

- `titanic`: accuracy on `Survived`;
- `bike-sharing-demand`: RMSLE on `count`;
- `commonlitreadabilityprize`: RMSE on `target`;
- `liverpool-ion-switching`: macro-F1 on `open_channels`;
- `spaceship-titanic`: accuracy on `Transported`;
- `ventilator-pressure-prediction`: MAE on `pressure`.

The evaluator source is available and its CLI/result-file contract was checked,
but source availability is not evaluator qualification. The processed archive
advertises 3,126,493,713 bytes, and the remote Kaggle API returned HTTP 401
(`Unauthenticated`) for all six probes. Therefore the status is
`BLOCKED_PENDING_DATA_LABEL_DEPENDENCY_VERIFICATION`; no task is eligible to
consume formal checkpoint budget yet. A later operator must obtain the exact
data/labels through an authorized route, record hashes, run each official
evaluator inside the actual Guest image, and update the qualification record.
