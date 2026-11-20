"""Match metric aggregation.

Matches are described by dicts produced by
:func:`tetrisrl.evaluation.evaluator.play_match`; these helpers turn a list of
matches into the metric set required by the specification (win rate, attack per
minute, attack efficiency, garbage cancelled, survival, board quality, ...).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .statistical_analysis import mean_ci, wilson_interval


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_matches(matches: Sequence[Dict[str, Any]], perspective: str = "a") -> Dict[str, Any]:
    """Aggregate per-match records for the agent on side ``perspective``."""
    n = len(matches)
    wins = sum(1 for m in matches if m["winner"] == (0 if perspective == "a" else 1))
    losses = sum(1 for m in matches if m["winner"] is not None and m["winner"] != (0 if perspective == "a" else 1))
    draws = n - wins - losses

    def stats(m: Dict[str, Any]) -> Dict[str, Any]:
        return m["stats"][0 if perspective == "a" else 1]

    pieces = [stats(m)["pieces"] for m in matches]
    lines = [stats(m)["lines"] for m in matches]
    attacks = [stats(m)["attack"] for m in matches]
    sent = [stats(m)["attack_sent"] for m in matches]
    cancelled = [stats(m)["cancelled"] for m in matches]
    received = [stats(m)["garbage_received"] for m in matches]
    inserted = [stats(m)["garbage_inserted"] for m in matches]
    heights = [stats(m)["final_height"] for m in matches]
    holes = [stats(m)["final_holes"] for m in matches]
    tetrises = [stats(m)["four_lines"] for m in matches]
    tspins = [stats(m)["tspins"] for m in matches]
    combos = [stats(m)["max_combo"] for m in matches]
    topouts = [1.0 if stats(m)["top_out_reason"] else 0.0 for m in matches]
    durations = [m["ticks"] for m in matches]

    lo, hi = wilson_interval(wins, n)
    total_pieces = sum(pieces) or 1
    total_attack = sum(attacks)
    total_lines = sum(lines) or 1
    total_minutes = max(1e-9, sum(durations) / 60.0)

    return {
        "matches": n,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / n if n else 0.0,
        "win_rate_ci_low": lo,
        "win_rate_ci_high": hi,
        "win_rate_n": n,
        "pieces": _mean(pieces),
        "lines": _mean(lines),
        "attack": _mean(attacks),
        "attack_sent": _mean(sent),
        "garbage_cancelled": _mean(cancelled),
        "garbage_received": _mean(received),
        "garbage_inserted": _mean(inserted),
        "attack_per_minute": total_attack / total_minutes,
        "attack_efficiency": total_attack / total_lines,
        "attack_per_piece": total_attack / total_pieces,
        "pieces_per_second": total_pieces / max(1e-9, sum(durations)),
        "avg_final_height": _mean(heights),
        "avg_final_holes": _mean(holes),
        "tetrises": _mean(tetrises),
        "tspins": _mean(tspins),
        "max_combo": _mean(combos),
        "top_out_rate": _mean(topouts),
        "match_duration_ticks": _mean(durations),
        "duration_ci": mean_ci([float(d) for d in durations]),
    }
