# TRUST-RH Signature Algorithm

Canonical executable module: `src/mdt/optimization/signature_algorithm.py`.

TRUST-RH first applies the engineering trust gate in `mdt.trust`. Only an `AUTHORIZED` twin may enter the stability-aware slot MILP. The slot formulation assigns each job exactly once, respects per-slot capacity, and penalizes changes from the prior slot plan. The detailed finite-capacity recovery engine remains the downstream plant scheduler.

See `docs/TRUST_RH.md` and `docs/RESEARCH_VALIDATION_TRUST_RH.md` for evidence boundaries and falsification.
