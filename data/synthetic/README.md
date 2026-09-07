# MDT Operational Scenario Dataset

`mdt_operational_scenarios_10000.csv` is a deterministic, synthetic dataset
for the Manufacturing Digital Twin portfolio demo. It is safe to use at career
fairs, in classroom demonstrations, and in research notebooks because it does
not contain plant, customer, employee, or personally identifiable information.

## What it covers

- 10,000 scenario observations across ten operating conditions: nominal flow,
  high WIP, tight due dates, process variability, machine failure, machine
  recovery, quality excursions, material delay, capacity bottlenecks, and policy
  trade-offs.
- All five canonical event types used by the twin: job release, operation
  start, operation completion, machine down, and machine up.
- Machine state, queue/WIP/capacity, processing variation, MTBF/MTTR,
  maintenance failure modes, sensor-like signals, quality outcomes, lateness,
  risk, anomaly flags, and policy outcomes.
- A reproducible seed and SHA-256 digest in `DATASET_MANIFEST.json`.

## Evidence boundary

Every row is labeled `source_kind=synthetic_demo` and
`evidence_label=synthetic_scenario_observation`. The dataset is **not** a live
event ledger, a public plant dataset, or evidence of realized operational or
financial improvement. Do not describe it as real factory telemetry.

The canonical CSV replay adapter remains intentionally strict. This scenario
table is for analytics and demonstrations; real event ingestion should use the
seven-column contract documented in `docs/DATA_DICTIONARY.md` and
`docs/EVENT_CONTRACT_V1.md`.

## Reproduce it

From the `Manufacturing_Digital_Twin` directory:

```powershell
python scripts/generate_synthetic_dataset.py
```

The generator uses only the Python standard library. The default seed is
`20260906`; changing the seed intentionally changes the data and its digest.

## Public references checked

The project also documents public reference sources in `docs/DATA.md` and the
manifest. UCI AI4I is a 10,000-row predictive-maintenance dataset but is itself
synthetic and does not represent the twin's event/scheduling schema. UCI SECOM
is a smaller public semiconductor process dataset. NASA prognostics data and
OR-Library job-shop instances are useful for method-specific validation, but
neither is a drop-in replacement for plant event history.
