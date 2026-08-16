from __future__ import annotations

from dataclasses import dataclass
from math import inf
from time import perf_counter

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


@dataclass(frozen=True)
class StochasticPolicyEvidence:
    backend: str
    status: str
    objective_value: float | None
    best_bound: float | None
    mip_gap: float | None
    solve_time_seconds: float
    alpha: float
    risk_aversion: float
    scenarios: int
    policies: int
    oracle_selected_policy: str | None
    oracle_objective: float | None


@dataclass(frozen=True)
class StochasticPolicySelection:
    selected_policy: str | None
    expected_loss: float | None
    cvar_loss: float | None
    objective_value: float | None
    evidence: StochasticPolicyEvidence


def _empirical_cvar(values: np.ndarray, alpha: float) -> float:
    # Use the same linear CVaR representation as the optimization: minimize
    # eta + 1/((1-alpha)N) * sum(max(loss-eta, 0)) over observed scenarios.
    candidates = np.unique(values)
    best = inf
    for eta in candidates:
        value = float(eta + np.maximum(values - eta, 0.0).mean() / (1.0 - alpha))
        best = min(best, value)
    return float(best)


def _enumeration_oracle(policy_losses: dict[str, tuple[float, ...]], alpha: float, risk_aversion: float) -> tuple[str, float, float, float]:
    rows = []
    for policy, losses in policy_losses.items():
        arr = np.asarray(losses, dtype=float)
        expected = float(arr.mean())
        cvar = _empirical_cvar(arr, alpha)
        objective = expected + risk_aversion * cvar
        rows.append((objective, expected, cvar, policy))
    objective, expected, cvar, policy = min(rows)
    return policy, expected, cvar, objective


def select_policy_stochastic(
    policy_losses: dict[str, tuple[float, ...]],
    *,
    alpha: float = 0.95,
    risk_aversion: float = 0.35,
    time_limit: float = 10.0,
) -> StochasticPolicySelection:
    """Choose one policy under a finite scenario distribution using a CVaR MILP.

    Decision variables
    ------------------
    x[p] in {0,1}: choose exactly one candidate policy.
    eta >= 0: VaR/CVaR threshold surrogate.
    u[s] >= 0: scenario excess over eta.

    Objective
    ---------
    E[L] + risk_aversion * CVaR_alpha(L)

    where each scenario's selected loss is sum_p loss[p,s] * x[p].

    The model is independently verified by exact enumeration of all candidate
    policies, which is practical because this decision is policy selection, not
    operation-level scheduling.
    """
    if not policy_losses:
        raise ValueError("policy_losses cannot be empty")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    if risk_aversion < 0:
        raise ValueError("risk_aversion must be non-negative")
    if time_limit <= 0:
        raise ValueError("time_limit must be positive")
    policies = tuple(sorted(policy_losses))
    lengths = {len(policy_losses[p]) for p in policies}
    if len(lengths) != 1 or next(iter(lengths)) < 2:
        raise ValueError("all policies must have the same number of at least two scenarios")
    n_scenarios = next(iter(lengths))
    losses = np.asarray([policy_losses[p] for p in policies], dtype=float)
    if not np.all(np.isfinite(losses)) or np.any(losses < 0):
        raise ValueError("scenario losses must be finite and non-negative")

    n_policies = len(policies)
    x0 = 0
    eta_idx = n_policies
    u0 = eta_idx + 1
    n_vars = u0 + n_scenarios

    c = np.zeros(n_vars, dtype=float)
    mean_loss = losses.mean(axis=1)
    c[:n_policies] = mean_loss
    c[eta_idx] = risk_aversion
    c[u0:] = risk_aversion / ((1.0 - alpha) * n_scenarios)

    integrality = np.zeros(n_vars, dtype=int)
    integrality[:n_policies] = 1
    lb = np.zeros(n_vars, dtype=float)
    ub = np.full(n_vars, np.inf, dtype=float)
    ub[:n_policies] = 1.0
    bounds = Bounds(lb, ub)

    # Equality: sum x_p = 1.
    Aeq = lil_matrix((1, n_vars), dtype=float)
    for p_idx in range(n_policies):
        Aeq[0, p_idx] = 1.0
    constraints: list[LinearConstraint] = [LinearConstraint(Aeq.tocsr(), np.array([1.0]), np.array([1.0]))]

    # For each scenario: selected_loss - eta - u_s <= 0.
    A = lil_matrix((n_scenarios, n_vars), dtype=float)
    for s in range(n_scenarios):
        for p_idx in range(n_policies):
            A[s, p_idx] = losses[p_idx, s]
        A[s, eta_idx] = -1.0
        A[s, u0 + s] = -1.0
    constraints.append(LinearConstraint(A.tocsr(), np.full(n_scenarios, -np.inf), np.zeros(n_scenarios)))

    started = perf_counter()
    res = milp(
        c=c,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
        options={"time_limit": float(time_limit), "mip_rel_gap": 0.0, "presolve": True},
    )
    elapsed = perf_counter() - started
    status_map = {0: "OPTIMAL", 1: "TIME_LIMIT", 2: "INFEASIBLE", 3: "UNBOUNDED", 4: "ERROR"}
    status = status_map.get(int(res.status), "ERROR")

    oracle_policy, oracle_expected, oracle_cvar, oracle_obj = _enumeration_oracle(policy_losses, alpha, risk_aversion)
    selected: str | None = None
    expected: float | None = None
    cvar: float | None = None
    obj: float | None = None
    if res.x is not None:
        selected_idx = int(np.argmax(res.x[:n_policies]))
        selected = policies[selected_idx]
        selected_losses = losses[selected_idx]
        expected = float(selected_losses.mean())
        cvar = _empirical_cvar(selected_losses, alpha)
        obj = expected + risk_aversion * cvar
        if status == "OPTIMAL" and (selected != oracle_policy or abs(obj - oracle_obj) > 1e-6):
            raise RuntimeError("stochastic policy MILP disagrees with exact enumeration oracle")

    evidence = StochasticPolicyEvidence(
        backend="scipy-highs",
        status=status,
        objective_value=float(res.fun) if res.fun is not None else None,
        best_bound=float(res.mip_dual_bound) if getattr(res, "mip_dual_bound", None) is not None else None,
        mip_gap=float(res.mip_gap) if getattr(res, "mip_gap", None) is not None else None,
        solve_time_seconds=float(elapsed),
        alpha=float(alpha),
        risk_aversion=float(risk_aversion),
        scenarios=n_scenarios,
        policies=n_policies,
        oracle_selected_policy=oracle_policy,
        oracle_objective=float(oracle_obj),
    )
    return StochasticPolicySelection(selected, expected, cvar, obj, evidence)
