"""Attack computation, combo multiplier, B2B charging/surge, garbage queue."""

from __future__ import annotations

import math

import pytest

from tetrisrl.environment.board import Board
from tetrisrl.environment.garbage import GarbageQueue
from tetrisrl.environment.ruleset import AttackTable, GarbageConfig, tetrio_s1_ruleset, tetrio_s2_ruleset
from tetrisrl.environment.scoring import ClearState, compute_clear, on_no_clear, split_surge


def test_base_attack_values():
    table = AttackTable()
    assert table.base_attack(1, False, False) == 0
    assert table.base_attack(2, False, False) == 1
    assert table.base_attack(3, False, False) == 2
    assert table.base_attack(4, False, False) == 4
    assert table.base_attack(1, True, False) == 2
    assert table.base_attack(2, True, False) == 4
    assert table.base_attack(3, True, False) == 6
    # Mini spins: 0 / 1 / 2 in Season 2.
    assert table.base_attack(1, True, True) == 0
    assert table.base_attack(2, True, True) == 1
    assert table.base_attack(3, True, True) == 2


def test_combo_multiplier_and_log_floor():
    rules = tetrio_s2_ruleset()
    state = ClearState()
    assert state.combo == -1
    first = compute_clear(rules, state, 1, False, False, False)
    assert first.combo_after == 0
    assert first.combo_multiplier == 1.0
    assert first.attack == 0
    second = compute_clear(rules, state, 1, False, False, False)
    assert second.combo_after == 1
    assert second.combo_multiplier == pytest.approx(1.25)
    assert second.attack == 0  # 0 base stays 0 when combo == 1
    third = compute_clear(rules, state, 1, False, False, False)
    assert third.combo_after == 2
    # ln(1 + 1.25*2) = 1.25 -> floor 1
    assert third.attack == 1
    doubled = ClearState()
    compute_clear(rules, doubled, 2, False, False, False)
    comp = compute_clear(rules, doubled, 2, False, False, False)
    assert comp.combo_after == 1
    assert comp.attack == 1  # floor(1 * 1.25)


def test_combo_resets_on_no_clear():
    rules = tetrio_s2_ruleset()
    state = ClearState()
    compute_clear(rules, state, 2, False, False, False)
    assert state.combo == 0
    on_no_clear(rules, state)
    assert state.combo == -1


def test_b2b_flat_bonus_and_streak():
    rules = tetrio_s2_ruleset()
    state = ClearState()
    first = compute_clear(rules, state, 4, False, False, False)
    assert first.b2b_flat == 0
    assert state.b2b == 1
    second = compute_clear(rules, state, 4, False, False, False)
    assert second.b2b_flat == 1
    assert state.b2b == 2
    # Combo 1 multiplier applies after the flat b2b bonus: floor((4+1)*1.25)=6.
    assert second.attack == 6


def test_b2b_break_on_non_difficult_clear_releases_surge():
    rules = tetrio_s2_ruleset()
    state = ClearState()
    for _ in range(4):
        compute_clear(rules, state, 4, False, False, False)
    assert state.b2b == 4
    assert state.surge == 4
    comp = compute_clear(rules, state, 2, False, False, False)
    assert comp.surge_released is True
    assert comp.surge_segments == [1, 1, 2]
    assert state.b2b == 0
    assert state.surge == 0
    assert state.surges_released == 1
    # Surge events come first, then the clear's own attack.
    assert comp.attack_events[:3] == [1, 1, 2]


def test_surge_releases_on_empty_lock():
    rules = tetrio_s2_ruleset()
    state = ClearState()
    for _ in range(4):
        compute_clear(rules, state, 4, False, False, False)
    events = on_no_clear(rules, state)
    assert events == [1, 1, 2]
    assert state.b2b == 0 and state.surge == 0


def test_surge_grows_with_b2b_count():
    rules = tetrio_s2_ruleset()
    state = ClearState()
    for _ in range(8):
        compute_clear(rules, state, 4, False, False, False)
    assert state.b2b == 8
    assert state.surge == 8
    assert split_surge(8) == [3, 3, 2]


def test_classic_mode_has_no_surge():
    rules = tetrio_s1_ruleset()
    assert rules.b2b.mode == "classic"
    state = ClearState()
    for _ in range(6):
        comp = compute_clear(rules, state, 4, False, False, False)
        assert comp.surge_released is False
        assert comp.surge_segments == []
    assert state.b2b == 6


def test_all_clear_counts_as_b2b_and_sends_five():
    rules = tetrio_s2_ruleset()
    state = ClearState()
    comp = compute_clear(rules, state, 4, False, False, True)
    assert comp.perfect_clear
    assert comp.difficult
    assert state.b2b == 1
    assert rules.attack.all_clear in comp.attack_events
    assert comp.total_attack >= 4 + 5


def test_spin_counts_as_difficult_and_keeps_b2b():
    rules = tetrio_s2_ruleset()
    state = ClearState()
    compute_clear(rules, state, 4, False, False, False)
    assert state.b2b == 1
    comp = compute_clear(rules, state, 2, True, False, False)
    assert comp.difficult
    assert state.b2b == 2
    assert comp.b2b_flat == 1


def test_garbage_cancel_partial_fifo():
    q = GarbageQueue(GarbageConfig(insertion_delay_pieces=0), seed=1)
    q.add(5)
    assert q.total() == 5
    cancelled, remaining = q.cancel(3)
    assert (cancelled, remaining) == (3, 0)
    assert q.total() == 2
    cancelled, remaining = q.cancel(10)
    assert (cancelled, remaining) == (2, 8)
    assert q.total() == 0


def test_garbage_tank_cap():
    q = GarbageQueue(GarbageConfig(tank_cap=8, insertion_delay_pieces=0), seed=1)
    q.add(12)
    board = Board()
    inserted, events = q.tank(board, 8)
    assert inserted == 8
    assert q.total() == 4
    # Remaining garbage enters on the next tank.
    inserted2, _ = q.tank(board, 8)
    assert inserted2 == 4


def test_garbage_batch_shares_hole():
    q = GarbageQueue(GarbageConfig(hole_mode="per_batch", messiness_within=0.0), seed=5)
    q.add(3, ready_in=0)
    board = Board()
    inserted, events = q.tank(board, 8)
    assert inserted == 3
    hole = events[0]["hole"]
    for row in board.rows[-3:]:
        assert row == board.full_row_mask & ~(1 << hole)


def test_garbage_per_row_holes_can_differ():
    q = GarbageQueue(GarbageConfig(hole_mode="per_row", messiness_within=1.0), seed=9)
    q.add(6, ready_in=0)
    board = Board()
    inserted, events = q.tank(board, 8)
    holes = set()
    for row in board.rows[-6:]:
        for x in range(10):
            if not (row >> x) & 1:
                holes.add(x)
    assert inserted == 6
    assert len(holes) >= 2


def test_garbage_delay_ticks():
    q = GarbageQueue(GarbageConfig(insertion_delay_pieces=2), seed=1)
    q.add(2)
    q.tick(1)
    assert len(q.ready_entries()) == 0
    q.tick(1)
    assert len(q.ready_entries()) == 1
