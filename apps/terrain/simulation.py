"""Generate synthetic elevation fields and sample terrain transects."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np
from scipy.interpolate import interpn

X = np.linspace(-6.0, 6.0, 151)
Y = np.linspace(-4.5, 4.5, 121)
XX, YY = np.meshgrid(X, Y)
LEVELS = np.arange(-900, 3001, 300)


def gaussian_surface(
    x: np.ndarray, y: np.ndarray, x0: float, y0: float, sx: float, sy: float
) -> np.ndarray:
    return np.exp(-(((x - x0) / sx) ** 2 + ((y - y0) / sy) ** 2))


def coastal_headlands() -> np.ndarray:
    shoreline = -0.75 + 0.72 * np.sin(XX / 1.25) + 0.22 * np.sin(XX * 1.7)
    coastal_rise = 2050 / (1 + np.exp(-1.65 * (YY - shoreline)))
    headlands = 620 * gaussian_surface(XX, YY, -3.0, 1.25, 1.0, 1.5)
    headlands += 760 * gaussian_surface(XX, YY, 2.5, 1.65, 1.2, 1.4)
    drainage = 520 * np.exp(-(((XX - 0.35 * YY) / 0.75) ** 2)) * np.clip((YY + 1.0) / 5.0, 0, 1)
    return -420 + coastal_rise + headlands - drainage


def volcanic_caldera() -> np.ndarray:
    radius = np.hypot(XX + 0.25, YY - 0.1)
    mountain = 2550 * np.exp(-((radius / 2.6) ** 2))
    crater = 1450 * np.exp(-((radius / 0.82) ** 2))
    flank = 420 * gaussian_surface(XX, YY, 2.8, -1.3, 1.25, 1.0)
    return 180 + mountain - crater + flank


def glacial_basin() -> np.ndarray:
    west_wall = 1500 * gaussian_surface(XX, YY, -3.2, 0.5, 1.8, 3.7)
    east_wall = 1750 * gaussian_surface(XX, YY, 3.4, 0.2, 1.6, 3.4)
    headwall = 1150 * gaussian_surface(XX, YY, 0.4, 3.4, 4.2, 1.25)
    valley = 760 * np.exp(-(((YY + 0.65 * np.sin(XX / 1.7)) / 1.05) ** 2))
    overdeepening = 520 * gaussian_surface(XX, YY, 0.0, -0.4, 2.6, 0.9)
    return 420 + west_wall + east_wall + headwall - valley - overdeepening


def ridge_and_saddle() -> np.ndarray:
    ridge = 1780 * np.exp(-(((YY - 0.65 * np.sin(XX / 1.8)) / 1.15) ** 2))
    north_peak = 950 * gaussian_surface(XX, YY, -2.7, 1.4, 1.2, 1.15)
    south_peak = 1150 * gaussian_surface(XX, YY, 2.8, -1.2, 1.35, 1.3)
    saddle = 720 * gaussian_surface(XX, YY, 0.0, 0.0, 1.1, 0.95)
    return 260 + ridge + north_peak + south_peak - saddle


def river_canyon() -> np.ndarray:
    upland = 2100 + 180 * np.tanh(XX / 3.5) + 220 * np.cos(YY / 1.8)
    river = 1680 * np.exp(-(((YY - 0.75 * np.sin(XX / 1.45)) / 0.52) ** 2))
    tributary = 620 * gaussian_surface(XX, YY, -2.2, 1.55, 0.65, 2.3)
    mesa = 420 * gaussian_surface(XX, YY, 3.4, 2.2, 1.8, 1.4)
    return upland - river - tributary + mesa


def karst_peaks() -> np.ndarray:
    z = 130 + 90 * np.cos(XX / 1.3) * np.cos(YY / 1.1)
    peaks = (
        (-4.1, -1.8, 1550, 0.75, 0.8),
        (-2.8, 1.4, 2100, 0.72, 0.9),
        (-1.0, -0.5, 1850, 0.85, 0.75),
        (0.7, 2.2, 2300, 0.7, 0.8),
        (2.1, -1.6, 2050, 0.82, 0.9),
        (4.1, 0.8, 1750, 0.78, 0.78),
    )
    for x0, y0, height, sx, sy in peaks:
        z += height * gaussian_surface(XX, YY, x0, y0, sx, sy)
    return z


def impact_crater() -> np.ndarray:
    radius = np.hypot(XX + 0.35, YY - 0.15)
    angle = np.arctan2(YY - 0.15, XX + 0.35)
    rim = 2200 * np.exp(-(((radius - 2.45) / 0.38) ** 2))
    central_uplift = 1650 * np.exp(-((radius / 0.58) ** 2))
    ejecta = 360 * np.exp(-((radius / 4.3) ** 2)) * (1 + 0.32 * np.cos(7 * angle + 1.2 * radius))
    return 150 + rim + central_uplift + ejecta


def fault_escarpment() -> np.ndarray:
    fault = YY - 0.3 * XX + 0.28 * np.sin(XX * 0.9)
    uplift = 1850 / (1 + np.exp(-4.8 * fault))
    fault_ridge = 720 * np.exp(-((fault / 0.34) ** 2))
    tilted_block = 260 * (XX + 6) / 12
    hanging_valley = 520 * gaussian_surface(XX, YY, -2.7, 2.0, 1.15, 0.8)
    return 170 + uplift + fault_ridge + tilted_block - hanging_valley


def alpine_massif() -> np.ndarray:
    z = 180 + 650 * np.exp(-(((YY - 0.22 * XX) / 1.55) ** 2))
    peaks = (
        (-3.5, 1.35, 2150, 1.0, 1.1),
        (-1.1, -0.35, 2550, 0.92, 0.86),
        (1.45, 1.55, 2380, 0.88, 1.0),
        (3.65, -1.25, 2200, 1.05, 0.92),
    )
    for x0, y0, height, sx, sy in peaks:
        z += height * gaussian_surface(XX, YY, x0, y0, sx, sy)
    main_valley = 880 * np.exp(-(((YY + 1.35 + 0.18 * XX) / 0.48) ** 2))
    hanging_valley = 620 * np.exp(-(((XX - 0.45 * YY - 0.2) / 0.52) ** 2))
    return z - main_valley - hanging_valley


def island_arc() -> np.ndarray:
    z = np.full_like(XX, -420.0)
    islands = (
        (-4.35, -1.8, 1250, 0.72, 0.62),
        (-2.65, -0.55, 1900, 0.82, 0.72),
        (-0.55, 0.8, 2650, 1.0, 0.88),
        (1.8, 1.55, 2250, 0.86, 0.78),
        (3.85, 0.65, 1650, 0.78, 0.68),
    )
    for x0, y0, height, sx, sy in islands:
        z += (height + 400) * gaussian_surface(XX, YY, x0, y0, sx, sy)
    return z - 1100 * gaussian_surface(XX, YY, -0.55, 0.8, 0.35, 0.31)


type TerrainGenerator = Callable[[], np.ndarray]
type LandformName = Literal[
    "Coastal headlands",
    "Volcanic caldera",
    "Glacial basin",
    "Ridge and saddle",
    "River canyon",
    "Karst peaks",
    "Impact crater",
    "Fault escarpment",
    "Alpine massif",
    "Island arc",
]

LANDFORMS: dict[LandformName, TerrainGenerator] = {
    "Coastal headlands": coastal_headlands,
    "Volcanic caldera": volcanic_caldera,
    "Glacial basin": glacial_basin,
    "Ridge and saddle": ridge_and_saddle,
    "River canyon": river_canyon,
    "Karst peaks": karst_peaks,
    "Impact crater": impact_crater,
    "Fault escarpment": fault_escarpment,
    "Alpine massif": alpine_massif,
    "Island arc": island_arc,
}


def generate_terrain(kind: LandformName) -> np.ndarray:
    try:
        z = LANDFORMS[kind]()
    except KeyError:
        raise ValueError(f"Unknown landform: {kind}") from None
    return np.clip(z, LEVELS[0] + 1, 2800)


def sample_transect(
    z: np.ndarray, x0: float, y0: float, x1: float, y1: float
) -> tuple[np.ndarray, np.ndarray]:
    sample_x = np.linspace(x0, x1, 241)
    sample_y = np.linspace(y0, y1, 241)
    points = np.column_stack((np.clip(sample_y, Y[0], Y[-1]), np.clip(sample_x, X[0], X[-1])))
    values = interpn((Y, X), z, points)
    distance = np.linspace(0, np.hypot(x1 - x0, y1 - y0), len(values))
    return distance, values
