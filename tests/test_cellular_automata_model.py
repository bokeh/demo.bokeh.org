"""Test the Bokeh-independent cellular automata model."""

from __future__ import annotations

from collections import OrderedDict

import numpy as np
import pytest

from apps.cellular_automata import model
from apps.cellular_automata.model import (
    ACORN,
    COLUMNS,
    CYCLE_MEMORY,
    GLIDER,
    GOSPER_GLIDER_GUN,
    ROWS,
    RULES,
    Rule,
    custom_rule,
    cycle_label,
    evolve,
    neighbor_count,
    neighbor_phrase,
    orient_pattern,
    remember_state,
    seed_field,
    stamp,
    state_key,
)


def empty_field() -> np.ndarray:
    return np.zeros((ROWS, COLUMNS), dtype=bool)


def test_rule_builds_read_only_lookup_tables_and_notation() -> None:
    rule = Rule(frozenset({6, 3}), frozenset({3, 2}), "HighLife")

    assert rule.notation == "B36/S23"
    assert np.flatnonzero(rule.birth_lookup).tolist() == [3, 6]
    assert np.flatnonzero(rule.survive_lookup).tolist() == [2, 3]
    assert not rule.birth_lookup.flags.writeable
    assert not rule.survive_lookup.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        rule.birth_lookup[3] = False


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ((1,), "1 neighbor"),
        ((2,), "2 neighbors"),
        ((1, 3), "1 or 3 neighbors"),
        ((0, 2, 4), "0, 2 or 4 neighbors"),
    ],
)
def test_neighbor_phrase(counts: tuple[int, ...], expected: str) -> None:
    assert neighbor_phrase(counts) == expected


def test_custom_rule_is_cached_and_describes_empty_choices() -> None:
    first = custom_rule((3, 6), ())
    second = custom_rule((3, 6), ())

    assert first is second
    assert first.notation == "B36/S"
    assert "3 or 6 neighbors" in first.description
    assert "always die" in first.description


def test_stamp_clips_pattern_at_field_boundaries() -> None:
    field = empty_field()
    stamp(field, ((0, 0), (1, 0), (0, 1), (-1, 0)), COLUMNS - 1, ROWS - 1)

    assert field.sum() == 2
    assert field[ROWS - 1, COLUMNS - 1]
    assert field[ROWS - 1, COLUMNS - 2]


@pytest.mark.parametrize(
    ("name", "population"),
    [
        ("Gosper glider gun", len(GOSPER_GLIDER_GUN)),
        ("Pulsar constellation", 3 * 48),
        ("Glider fleet", 5 * len(GLIDER)),
        ("R-pentomino", 5),
        ("Acorn", len(ACORN)),
    ],
)
def test_seed_field_places_each_named_pattern(name: str, population: int) -> None:
    field = seed_field(name, 0.25, np.random.default_rng(10))

    assert field.shape == (ROWS, COLUMNS)
    assert field.dtype == np.bool_
    assert int(field.sum()) == population


def test_random_seed_field_honors_density_and_rng_seed() -> None:
    first = seed_field("Random soup", 0.3, np.random.default_rng(42))
    second = seed_field("Random soup", 0.3, np.random.default_rng(42))

    assert np.array_equal(first, second)
    assert 0.27 < first.mean() < 0.33
    assert not seed_field("Random soup", 0.0, np.random.default_rng(0)).any()
    assert seed_field("Random soup", 1.0, np.random.default_rng(0)).all()


def test_seed_field_rejects_unknown_pattern() -> None:
    with pytest.raises(ValueError, match="Unknown seed pattern"):
        seed_field("Missing", 0.2, np.random.default_rng(0))


def test_neighbor_count_distinguishes_wrapped_and_bounded_edges() -> None:
    field = empty_field()
    field[0, 0] = True

    bounded = neighbor_count(field, wrap=False)
    wrapped = neighbor_count(field, wrap=True)

    assert int(bounded.sum()) == 3
    assert int(wrapped.sum()) == 8
    assert bounded[-1, -1] == 0
    assert wrapped[-1, -1] == 1


def test_evolve_preserves_a_block_and_increments_ages() -> None:
    field = empty_field()
    field[39:41, 63:65] = True
    age = field.astype(np.uint16)

    next_field, next_age, births, deaths = evolve(field, age, RULES["Conway's Life"], wrap=False)

    assert np.array_equal(next_field, field)
    assert np.all(next_age[field] == 2)
    assert births == 0
    assert deaths == 0


def test_evolve_turns_a_blinker_and_reports_turnover() -> None:
    field = empty_field()
    field[40, 63:66] = True
    age = field.astype(np.uint16)

    next_field, next_age, births, deaths = evolve(field, age, RULES["Conway's Life"], wrap=False)

    expected = empty_field()
    expected[39:42, 64] = True
    assert np.array_equal(next_field, expected)
    assert next_age[40, 64] == 2
    assert next_age[39, 64] == next_age[41, 64] == 1
    assert births == deaths == 2


@pytest.mark.parametrize(("turns", "flipped"), [(0, False), (1, False), (4, False), (1, True)])
def test_orient_pattern_preserves_population_and_normalizes_origin(
    turns: int, flipped: bool
) -> None:
    oriented = orient_pattern(GLIDER, turns, flipped)

    assert len(oriented) == len(GLIDER)
    assert len(set(oriented)) == len(GLIDER)
    assert min(x for x, _ in oriented) == 0
    assert min(y for _, y in oriented) == 0
    if turns == 4 and not flipped:
        assert oriented == tuple(sorted(GLIDER))


def test_state_key_is_stable_and_sensitive_to_cells() -> None:
    field = empty_field()
    initial = state_key(field)
    field[12, 34] = True

    assert state_key(empty_field()) == initial
    assert state_key(field) != initial


def test_remember_state_reports_period_and_refreshes_generation() -> None:
    seen: OrderedDict[bytes, int] = OrderedDict()
    field = empty_field()

    assert remember_state(field, 4, seen) is None
    assert remember_state(field, 7, seen) == 3
    assert seen[state_key(field)] == 7


def test_remember_state_bounds_cycle_memory() -> None:
    seen: OrderedDict[bytes, int] = OrderedDict()
    field = empty_field()
    first_key = state_key(field)

    for value in range(CYCLE_MEMORY + 1):
        field.flat[:10] = [bool(value & (1 << bit)) for bit in range(10)]
        assert remember_state(field, value, seen) is None

    assert len(seen) == CYCLE_MEMORY
    assert first_key not in seen


@pytest.mark.parametrize(
    ("alive", "period", "expected"),
    [
        (False, None, "Extinct"),
        (True, 1, "Still life"),
        (True, 4, "Oscillator · period 4"),
        (True, None, "Evolving"),
    ],
)
def test_cycle_label(alive: bool, period: int | None, expected: str) -> None:
    field = empty_field()
    field[0, 0] = alive
    assert cycle_label(field, period) == expected


def test_model_constants_match_the_simulation_grid() -> None:
    expected_counts = tuple(str(value) for value in range(9))
    assert expected_counts == model.NEIGHBOR_COUNTS
    assert all(rule.birth_lookup.shape == (9,) for rule in RULES.values())
