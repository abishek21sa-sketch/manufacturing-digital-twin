# Canonical Data Dictionary

## FactoryModel

| Field | Type | Unit | Required | Meaning |
|---|---|---:|---|---|
| `factory_id` | string | — | yes | Stable identifier for the represented manufacturing system/benchmark. |
| `machines` | MachineSpec[] | — | yes | Finite-capacity production resources. |
| `jobs` | JobSpec[] | — | yes | Production jobs with ordered routings. |
| `source` | string | — | yes | Human-readable source provenance. |
| `source_kind` | string | — | yes | Evidence class, e.g. `public_benchmark`. |
| `metadata` | object | — | no | Source/instance metadata. |

## MachineSpec

| Field | Type | Unit | Meaning |
|---|---|---:|---|
| `machine_id` | string | — | Unique machine/resource identifier. |
| `name` | string | — | Display name. |

## JobSpec

| Field | Type | Unit | Meaning |
|---|---|---:|---|
| `job_id` | string | — | Unique production-job identifier. |
| `operations` | OperationSpec[] | — | Ordered routing. |
| `release_time` | float | model time | Earliest allowed release. |
| `due_time` | float/null | model time | Optional due time. Not fabricated for FT06. |

## OperationSpec

| Field | Type | Unit | Meaning |
|---|---|---:|---|
| `operation_id` | string | — | Unique operation identifier. |
| `job_id` | string | — | Parent job. |
| `sequence` | integer | ordinal | Precedence position in routing. |
| `machine_id` | string | — | Required machine for classical JSSP. |
| `processing_time` | float | benchmark time units | Deterministic processing time supplied by benchmark. |

## ManufacturingEvent

| Field | Type | Unit | Meaning |
|---|---|---:|---|
| `event_id` | string | — | Globally unique/idempotency identifier. |
| `event_type` | enum | — | `job_released`, `operation_started`, `operation_completed`, `machine_down`, `machine_up`. |
| `timestamp` | float | model time | Monotonic event time. |
| `job_id` | string/null | — | Job context where applicable. |
| `operation_id` | string/null | — | Operation context where applicable. |
| `machine_id` | string/null | — | Machine context where applicable. |
| `payload` | object | — | Extension metadata; deterministic state changes never rely on undocumented fabricated fields. |

## Runtime states

Machine status is one of `idle`, `busy`, `down`. Operation status is one of `not_ready`, `ready`, `running`, `complete`. Job status is one of `unreleased`, `released`, `in_process`, `complete`.
