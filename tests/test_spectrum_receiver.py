"""Test receiver state and text helpers independently of the Bokeh view."""

from __future__ import annotations

import numpy as np
import pytest

from apps.spectrum.receiver import ReceiverState, filter_explanation, receiver_status_html
from apps.spectrum.simulation import BLOCK_SIZE, SEED, SPECTRUM_FLOOR

FILTER_MODES = (
    "No filter",
    "Low-pass",
    "High-pass",
    "Band-pass",
    "Wide band-stop",
    "Dual band-pass",
    "Adaptive notch",
    "Peaking",
    "Elliptic band-pass",
    "Notch",
    "Comb reject",
)


def test_receiver_state_reset_clears_history_and_restores_seed() -> None:
    state = ReceiverState(
        rng=np.random.default_rng(99),
        raw_history=np.ones((3, 5), dtype=np.float32),
        raw=np.ones(BLOCK_SIZE),
        time=12.5,
        ticks=4,
        burst=True,
    )
    state.reset()

    assert np.all(state.raw_history == SPECTRUM_FLOOR)
    assert not state.raw.any()
    assert state.time == 0
    assert state.ticks == 0
    assert not state.burst
    assert state.rng.random() == np.random.default_rng(SEED).random()


@pytest.mark.parametrize("mode", FILTER_MODES)
def test_filter_explanation_describes_every_filter(mode: str) -> None:
    explanation = filter_explanation(mode, 437.4, 12)

    assert explanation.endswith(".")
    if mode == "Adaptive notch":
        assert "437 Hz" in explanation
    if mode == "Peaking":
        assert "12 dB" in explanation


def test_filter_explanation_rejects_unknown_filter() -> None:
    with pytest.raises(ValueError, match="Missing"):
        filter_explanation("Missing", 420, 0)


def test_receiver_status_reports_peak_band_power_and_removed_power() -> None:
    frequencies = np.array([0.0, 100.0, 200.0, 300.0])
    raw = np.array([-15.0, -5.0, -20.0, -30.0])
    filtered = np.array([-30.0, -8.0, -12.0, -40.0])

    html = receiver_status_html(frequencies, raw, filtered, "Band-pass", 150, 700, 200, 4.25)

    assert "Peak <span" in html
    assert ">100</span> Hz" in html
    assert "Band power" in html
    assert "of received power removed" in html
    assert ">4.2</b> s" in html
    assert "font-variant-numeric:tabular-nums" in html


def test_receiver_status_describes_added_power_for_peaking_filter() -> None:
    frequencies = np.array([0.0, 100.0, 200.0])
    raw = np.full(3, -30.0)
    filtered = np.array([-30.0, -10.0, -30.0])

    html = receiver_status_html(frequencies, raw, filtered, "Peaking", 100, 700, 50, 1)
    assert "of received power added" in html
