# Governance Compliance Traceability — Manufacturing Digital Twin

This file records the current RC2 engineering-release evidence against the supplied Portfolio Engineering Governance Pack and Signature Algorithms & Mathematical Foundations standard.

## Mandatory engineering-release controls

- **Project-specific signature algorithm:** `TRUST-RH` in the documented project-native decision/math package.
- **Fresh signature-module line coverage:** **98%** (required threshold: >=90%).
- **Regression evidence:** 91/91 tests under process-isolated native-solver execution.
- **Research/evidence gate:** 6/6 signature; 7/7 canonical trust; 96 trust sensitivity + 5 stability sensitivity.
- **Explicit objective, variables, constraints, operational decision and claim boundary:** documented in [`docs/TRUST_RH.md`](TRUST_RH.md).
- **Baseline/counterfactual, ablation and sensitivity evidence:** present in machine-readable artifacts under `artifacts/`.
- **Evidence classes:** observational/ingested, predicted, simulated, optimized and realized evidence are not conflated.
- **AI/agent role:** explanatory, predictive or analytical support only; the mathematical optimizer/control model remains the decision engine.
- **Human/evidence gate:** optimization recommendations are governed and do not autonomously execute external operational actions.
- **API/service exposure:** signature decision is exposed through the project service boundary.
- **Dedicated operator UI:** signature inputs, constraints/trade-offs, evidence status and baseline/counterfactual context are visible in the project UI.
- **Windows acceptance command:** `python .\scripts\windows_v1_acceptance.py`. Execution on the user's Windows machine is still required before final promotion.
- **README traceability:** README links the canonical `docs/SIGNATURE_ALGORITHM.md`.
- **Clean packaging:** RC2 packaging excludes `.env`, `.git`, virtual environments, caches/bytecode and stale nested archives.

## Explicit null hypotheses

- H0-D1: TRUST-RH does not reduce unsafe optimizer authorization under stale, inconsistent, or incomplete twin evidence versus an ungated optimizer.
- H0-D2: Stability-aware receding-horizon scheduling does not improve schedule-churn/objective trade-offs versus zero-stability reoptimization.

These are falsification targets, not claims that current evidence establishes causal or field superiority.

## Research-upgrade path

The engineering-release gate is intentionally separate from publication-grade research. Literature-positioning, stronger theoretical guarantees, broad public-benchmark studies, solver-scaling/warm-start studies, and field/causal validation remain **research-upgrade work unless explicitly evidenced in this repository**. The release does not backfill or imply those claims.
