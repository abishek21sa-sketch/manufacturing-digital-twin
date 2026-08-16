from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class IndividualsMRResult:
    center_line: float
    moving_range_bar: float
    sigma_estimate: float
    ucl: float
    lcl: float
    out_of_control_indices: tuple[int, ...]


def individuals_mr(values: Iterable[float]) -> IndividualsMRResult:
    x = np.asarray(list(values), dtype=float)
    if x.size < 2:
        raise ValueError("at least two observations are required")
    if not np.all(np.isfinite(x)):
        raise ValueError("observations must be finite")
    moving_ranges = np.abs(np.diff(x))
    mrbar = float(moving_ranges.mean())
    # d2 for moving range of two observations.
    sigma = mrbar / 1.128
    center = float(x.mean())
    ucl = center + 3.0 * sigma
    lcl = center - 3.0 * sigma
    flags = tuple(int(i) for i, value in enumerate(x) if value > ucl or value < lcl)
    return IndividualsMRResult(center, mrbar, sigma, ucl, lcl, flags)


@dataclass(frozen=True)
class FactorialEffect:
    term: str
    effect: float


def two_level_factorial_effects(rows: Iterable[dict[str, float]], outcome: str) -> tuple[FactorialEffect, ...]:
    data = list(rows)
    if not data:
        raise ValueError("DOE rows are required")
    factors = sorted(key for key in data[0] if key != outcome)
    if not factors:
        raise ValueError("at least one factor is required")
    for row in data:
        if set(row) != set(factors) | {outcome}:
            raise ValueError("all DOE rows must share the same columns")
        for factor in factors:
            if row[factor] not in {-1, -1.0, 1, 1.0}:
                raise ValueError("two-level factors must be coded as -1/+1")
    y = np.asarray([row[outcome] for row in data], dtype=float)
    effects: list[FactorialEffect] = []
    max_order = min(2, len(factors))
    for order in range(1, max_order + 1):
        for combo in combinations(factors, order):
            contrast = np.ones(len(data), dtype=float)
            for factor in combo:
                contrast *= np.asarray([row[factor] for row in data], dtype=float)
            # For balanced +/-1 factorial designs, effect is difference in means.
            effect = float(2.0 * np.mean(contrast * y))
            effects.append(FactorialEffect("*".join(combo), effect))
    return tuple(effects)
