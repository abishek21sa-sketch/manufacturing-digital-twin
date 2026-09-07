# Public Data Catalog and Usage Boundary

The project uses public data where it matches the engineering question and
uses synthetic data only where no public source supplies the required joined
schema. Public sources are not silently treated as live factory telemetry.

| Source | Public contribution | Local treatment | Terms/boundary |
|---|---|---|---|
| [OR-Library job-shop benchmarks](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/jobshopinfo.html) | Routing and deterministic processing times; FT06 gives the scheduling benchmark | `data/external/orlib/jobshop1.txt`; parsed and used by the optimization/validation stack | Preserve source attribution and check the OR-Library notice before redistribution. |
| [UCI AI4I 2020](https://archive.ics.uci.edu/dataset/601/ai4i) | 10,000-row predictive-maintenance reference with machine-failure labels | Metadata/reference only; it is itself synthetic and is not an event-sourced schedule | CC BY 4.0; attribution required. |
| [UCI SECOM](https://archive.ics.uci.edu/dataset/179/secom) | Semiconductor process sensor/yield reference with missingness and high dimensionality | Method reference for future quality/process adapters; not fused into the FT06 twin | CC BY 4.0; attribution required. |
| [NASA PCoE repository](https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/) | Public run-to-failure and prognostics references for reliability-method comparison | Reference only; source-specific redistribution terms must be checked | Do not redistribute a NASA source file unless its source terms allow it. |

## Why sources are not joined into one fictional factory

The sources measure different systems, units, populations, and labels. Joining
them would create a plausible-looking but scientifically invalid company
history. The repository instead keeps:

```text
public benchmark -> FactoryModel / scheduling evidence
public method reference -> catalogued future adapter target
synthetic scenario generator -> complete demo analytics schema
site-owned data -> future approved connector and calibration boundary
```

## Included synthetic pack

`data/synthetic/mdt_operational_scenarios_150000.csv` is a deterministic,
150,000-row, 80-column scenario-observation dataset with ten stress families.
Its manifest records the seed, schema, digest, public references, and evidence boundary.
Every row is labeled `source_kind=synthetic_demo` and
`evidence_label=synthetic_scenario_observation`. The API verifies the digest
before showing the pack as ready.

## Public-data integration rule

Any future public source must add its URL, owner, license/terms, retrieval date,
checksum, schema mapping, transformation code, and validation evidence before
it is used in a model or displayed as evidence. A source that lacks a clear
license remains a documented reference, not a bundled artifact.
