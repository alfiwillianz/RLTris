"""Statistical helpers used by evaluation and reports.

No result is ever hard-coded: every confidence interval is computed from the
collected samples with the sample size attached.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion (win rate)."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def mean_ci(values: Sequence[float], z: float = 1.959963984540054) -> Tuple[float, float, float]:
    """Return ``(mean, 95% CI low, 95% CI high)`` using the normal approximation."""
    if not values:
        return (0.0, 0.0, 0.0)
    n = len(values)
    mean = sum(values) / n
    if n == 1:
        return (mean, mean, mean)
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = math.sqrt(var / n)
    margin = z * se
    return (mean, mean - margin, mean + margin)


def summarize(values: Iterable[float]) -> Dict[str, float]:
    vals = [float(v) for v in values]
    mean, lo, hi = mean_ci(vals)
    return {"mean": mean, "ci_low": lo, "ci_high": hi, "n": len(vals)}


def paired_mean_difference(a: Sequence[float], b: Sequence[float]) -> Dict[str, float]:
    """Mean of paired differences ``a-b`` with a 95% CI (paired seeds)."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    diffs = [float(x) - float(y) for x, y in zip(a, b)]
    mean, lo, hi = mean_ci(diffs)
    return {"mean_diff": mean, "ci_low": lo, "ci_high": hi, "n": len(diffs), "diffs": diffs}


def win_rate(successes: int, n: int) -> Dict[str, float]:
    lo, hi = wilson_interval(successes, n)
    return {
        "win_rate": successes / n if n else 0.0,
        "ci_low": lo,
        "ci_high": hi,
        "n": n,
    }
