"""Simulation rules, patterns, and state for the cellular automata demo."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from functools import lru_cache

import numpy as np

ROWS = 80
COLUMNS = 128
CYCLE_MEMORY = 512
CUSTOM_RULE = "Custom rule"
NEIGHBOR_COUNTS = tuple(str(count) for count in range(9))


@dataclass(frozen=True)
class Rule:
    birth: frozenset[int]
    survive: frozenset[int]
    description: str
    birth_lookup: np.ndarray = dataclass_field(init=False, repr=False, compare=False)
    survive_lookup: np.ndarray = dataclass_field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        birth_lookup = np.zeros(9, dtype=bool)
        survive_lookup = np.zeros(9, dtype=bool)
        birth_lookup[list(self.birth)] = True
        survive_lookup[list(self.survive)] = True
        birth_lookup.flags.writeable = False
        survive_lookup.flags.writeable = False
        object.__setattr__(self, "birth_lookup", birth_lookup)
        object.__setattr__(self, "survive_lookup", survive_lookup)

    @property
    def notation(self) -> str:
        births = "".join(str(value) for value in sorted(self.birth))
        survives = "".join(str(value) for value in sorted(self.survive))
        return f"B{births}/S{survives}"


@dataclass
class SimulationState:
    rng: np.random.Generator
    field: np.ndarray
    age: np.ndarray
    comparison_field: np.ndarray
    comparison_age: np.ndarray
    generation: int = 0
    births: int = 0
    deaths: int = 0
    comparison_births: int = 0
    comparison_deaths: int = 0
    ticks: int = 0
    running: bool = True
    wrap: bool = True
    primary_seen: OrderedDict[bytes, int] = dataclass_field(default_factory=OrderedDict)
    comparison_seen: OrderedDict[bytes, int] = dataclass_field(default_factory=OrderedDict)
    primary_cycle: str = "Evolving"
    comparison_cycle: str = "Evolving"
    brush_rotation: int = 0
    brush_flipped: bool = False


RULES = {
    "Conway's Life": Rule(
        frozenset({3}),
        frozenset({2, 3}),
        "Birth with three neighbors; survive with two or three. Gliders, oscillators, and "
        "universal computation all emerge from this rule.",
    ),
    "HighLife": Rule(
        frozenset({3, 6}),
        frozenset({2, 3}),
        "Conway's rule plus birth at six neighbors. That one addition permits a small "
        "self-replicating pattern.",
    ),
    "Seeds": Rule(
        frozenset({2}),
        frozenset(),
        "Every live cell dies each step; empty cells with exactly two neighbors are born. "
        "Sparse seeds expand into branching wave fronts.",
    ),
    "Day & Night": Rule(
        frozenset({3, 6, 7, 8}),
        frozenset({3, 4, 6, 7, 8}),
        "Live and dead cells follow nearly symmetric dynamics, so dense islands and empty "
        "voids can propagate through one another.",
    ),
    "Life without Death": Rule(
        frozenset({3}),
        frozenset(range(9)),
        "Birth still requires three neighbors, but cells never die. Growth freezes into "
        "branching, maze-like structures.",
    ),
}


def neighbor_phrase(counts: tuple[int, ...]) -> str:
    values = [str(count) for count in counts]
    joined = values[0] if len(values) == 1 else f"{', '.join(values[:-1])} or {values[-1]}"
    return f"{joined} {'neighbor' if counts == (1,) else 'neighbors'}"


@lru_cache(maxsize=256)
def custom_rule(birth: tuple[int, ...], survive: tuple[int, ...]) -> Rule:
    birth_description = f"are born with {neighbor_phrase(birth)}" if birth else "are never born"
    survival_description = f"survive with {neighbor_phrase(survive)}" if survive else "always die"
    return Rule(
        frozenset(birth),
        frozenset(survive),
        f"Empty cells {birth_description}; living cells {survival_description}. "
        "Edit either list to change the rule.",
    )


PRESET_DESCRIPTIONS = {
    "Gosper glider gun": "A 36-cell machine that emits a new glider every 30 generations.",
    "Pulsar constellation": "Three period-three oscillators arranged across the field.",
    "Glider fleet": "Small translating patterns launched on different headings.",
    "R-pentomino": "Five cells that take 1,103 generations to settle under Conway's rule.",
    "Acorn": "Seven cells with a 5,206-generation Conway lifespan.",
    "Random soup": "A new seeded random field using the density control below.",
}


GOSPER_GLIDER_GUN = (
    (0, 4),
    (0, 5),
    (1, 4),
    (1, 5),
    (10, 4),
    (10, 5),
    (10, 6),
    (11, 3),
    (11, 7),
    (12, 2),
    (12, 8),
    (13, 2),
    (13, 8),
    (14, 5),
    (15, 3),
    (15, 7),
    (16, 4),
    (16, 5),
    (16, 6),
    (17, 5),
    (20, 2),
    (20, 3),
    (20, 4),
    (21, 2),
    (21, 3),
    (21, 4),
    (22, 1),
    (22, 5),
    (24, 0),
    (24, 1),
    (24, 5),
    (24, 6),
    (34, 2),
    (34, 3),
    (35, 2),
    (35, 3),
)
PULSAR = tuple(
    [(x, y) for x in (2, 3, 4, 8, 9, 10) for y in (0, 5, 7, 12)]
    + [(x, y) for x in (0, 5, 7, 12) for y in (2, 3, 4, 8, 9, 10)]
)
GLIDER = ((1, 0), (2, 1), (0, 2), (1, 2), (2, 2))
LIGHTWEIGHT_SPACESHIP = ((1, 0), (4, 0), (0, 1), (0, 2), (4, 2), (0, 3), (1, 3), (2, 3), (3, 3))
R_PENTOMINO = ((1, 0), (2, 0), (0, 1), (1, 1), (1, 2))
ACORN = ((1, 0), (3, 1), (0, 2), (1, 2), (4, 2), (5, 2), (6, 2))
BRUSHES = {
    "Toggle one cell": None,
    "Glider": GLIDER,
    "Lightweight spaceship": LIGHTWEIGHT_SPACESHIP,
    "Pulsar": PULSAR,
    "R-pentomino": R_PENTOMINO,
}


def stamp(field: np.ndarray, pattern: tuple[tuple[int, int], ...], x: int, y: int) -> None:
    for offset_x, offset_y in pattern:
        column = x + offset_x
        row = y + offset_y
        if 0 <= row < ROWS and 0 <= column < COLUMNS:
            field[row, column] = True


def seed_field(name: str, density: float, rng: np.random.Generator) -> np.ndarray:
    field = np.zeros((ROWS, COLUMNS), dtype=bool)
    match name:
        case "Gosper glider gun":
            stamp(field, GOSPER_GLIDER_GUN, COLUMNS // 2 - 18, ROWS // 2 - 4)
        case "Pulsar constellation":
            for x, y in ((14, 12), (COLUMNS // 2 - 6, ROWS - 24), (COLUMNS - 28, 13)):
                stamp(field, PULSAR, x, y)
        case "Glider fleet":
            for x, y in ((10, 10), (34, 24), (61, 9), (88, 42), (112, 18)):
                stamp(field, GLIDER, x, y)
        case "R-pentomino":
            stamp(field, R_PENTOMINO, COLUMNS // 2 - 1, ROWS // 2 - 1)
        case "Acorn":
            stamp(field, ACORN, COLUMNS // 2 - 3, ROWS // 2 - 1)
        case "Random soup":
            field = rng.random((ROWS, COLUMNS)) < density
        case _:
            raise ValueError(f"Unknown seed pattern: {name}")
    return field


def neighbor_count(field: np.ndarray, *, wrap: bool) -> np.ndarray:
    neighbors = np.zeros(field.shape, dtype=np.uint8)
    if wrap:
        for row in (-1, 0, 1):
            for column in (-1, 0, 1):
                if row != 0 or column != 0:
                    neighbors += np.roll(np.roll(field, row, axis=0), column, axis=1)
        return neighbors

    padded = np.pad(field, 1)
    for row in (-1, 0, 1):
        for column in (-1, 0, 1):
            if row != 0 or column != 0:
                neighbors += padded[1 + row : 1 + row + ROWS, 1 + column : 1 + column + COLUMNS]
    return neighbors


def evolve(
    field: np.ndarray, age: np.ndarray, rule: Rule, *, wrap: bool
) -> tuple[np.ndarray, np.ndarray, int, int]:
    neighbors = neighbor_count(field, wrap=wrap)
    born = ~field & rule.birth_lookup[neighbors]
    survives = field & rule.survive_lookup[neighbors]
    next_field = born | survives
    next_age = np.where(next_field, np.where(field, age + 1, 1), 0).astype(np.uint16)
    return next_field, next_age, int(born.sum()), int((field & ~next_field).sum())


def orient_pattern(
    pattern: tuple[tuple[int, int], ...], turns: int, flipped: bool
) -> tuple[tuple[int, int], ...]:
    points = [(-x if flipped else x, y) for x, y in pattern]
    for _ in range(turns % 4):
        points = [(-y, x) for x, y in points]
    minimum_x = min(x for x, _ in points)
    minimum_y = min(y for _, y in points)
    return tuple(sorted((x - minimum_x, y - minimum_y) for x, y in points))


def state_key(field: np.ndarray) -> bytes:
    return np.packbits(field, axis=None).tobytes()


def remember_state(field: np.ndarray, generation: int, seen: OrderedDict[bytes, int]) -> int | None:
    key = state_key(field)
    previous = seen.get(key)
    if previous is not None:
        period = generation - previous
        seen[key] = generation
        seen.move_to_end(key)
        return period
    seen[key] = generation
    if len(seen) > CYCLE_MEMORY:
        seen.popitem(last=False)
    return None


def cycle_label(field: np.ndarray, period: int | None) -> str:
    if not field.any():
        return "Extinct"
    if period == 1:
        return "Still life"
    if period is not None:
        return f"Oscillator · period {period}"
    return "Evolving"
