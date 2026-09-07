# TRUST-RH — Trust-Gated Receding-Horizon Decision Authorization

TRUST-RH is a governance layer that sits **before** recovery optimization. It does not replace the finite-capacity scheduling model; it decides whether the digital-twin evidence is strong enough for an optimizer recommendation to be treated as autonomous decision evidence.

The trust score is

\[
T = 0.30S + 0.25L + 0.20E + 0.25F,
\]

where `S` is structural twin consistency, `L` is event-ledger consistency, `E` is analytical-model evidence coverage, and `F = exp(-age/horizon)` is an explicit freshness decay term.

Default governance thresholds are `AUTHORIZED >= 0.82`, `HUMAN_REVIEW >= 0.62`, otherwise `BLOCKED`. Structural inconsistency, event-ledger mismatch, or model-evidence coverage below 75% are hard stops and force `BLOCKED` regardless of the weighted score.

The gate is intentionally deterministic and auditable. Its score is **not** a calibrated probability that the physical plant is represented correctly. The current validation is synthetic/benchmark validation of authorization behavior; external plant validation remains outside the evidence boundary.
