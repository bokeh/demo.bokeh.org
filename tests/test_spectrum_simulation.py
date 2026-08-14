"""Test the Bokeh-independent signal and filter calculations."""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from apps.spectrum.simulation import (
    BLOCK_SIZE,
    NYQUIST,
    SAMPLE_RATE,
    SPECTRUM_CEILING,
    SPECTRUM_FLOOR,
    apply_filter,
    apply_response_db,
    filter_response,
    generate_signal_block,
    power_spectrum_db,
)
from apps.spectrum.view import SCENES


@pytest.mark.parametrize("scene", list(SCENES))
def test_generate_signal_block_is_finite_deterministic_and_regular(scene: str) -> None:
    time, signal = generate_signal_block(scene, 1.25, 0.15, np.random.default_rng(7), False)
    repeated_time, repeated_signal = generate_signal_block(
        scene, 1.25, 0.15, np.random.default_rng(7), False
    )

    assert time.shape == signal.shape == (BLOCK_SIZE,)
    assert time[0] == pytest.approx(1.25)
    assert np.diff(time) == pytest.approx(1 / SAMPLE_RATE)
    assert np.isfinite(signal).all()
    assert np.array_equal(time, repeated_time)
    assert np.array_equal(signal, repeated_signal)


def test_scenes_generate_distinct_noise_free_signals() -> None:
    signals = [
        generate_signal_block(scene, 0, 0, np.random.default_rng(2), False)[1] for scene in SCENES
    ]

    assert all(not np.array_equal(first, second) for first, second in pairwise(signals))


def test_transient_burst_adds_localized_energy() -> None:
    _, ordinary = generate_signal_block("Telemetry link", 0, 0, np.random.default_rng(2), False)
    _, burst = generate_signal_block("Telemetry link", 0, 0, np.random.default_rng(2), True)
    difference = np.abs(burst - ordinary)

    assert difference[BLOCK_SIZE // 2] > difference[0] * 100
    assert np.mean(burst**2) > np.mean(ordinary**2)


def test_generate_signal_block_rejects_unknown_scene() -> None:
    with pytest.raises(ValueError, match="Unknown spectrum scene"):
        generate_signal_block("Missing", 0, 0, np.random.default_rng(0), False)


@pytest.mark.parametrize(
    "mode",
    [
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
    ],
)
def test_filter_response_is_finite_nonnegative_and_shape_preserving(mode: str) -> None:
    frequencies = np.linspace(0, NYQUIST, 1025)
    response = filter_response(frequencies, mode, 420, 100, 760, 12)

    assert response.shape == frequencies.shape
    assert np.isfinite(response).all()
    assert (response >= 0).all()


def test_low_and_high_pass_responses_are_complements() -> None:
    frequencies = np.linspace(0, NYQUIST, 1025)
    low = filter_response(frequencies, "Low-pass", 420, 100, 760, 0)
    high = filter_response(frequencies, "High-pass", 420, 100, 760, 0)

    assert np.all(np.diff(low) <= 0)
    assert np.all(np.diff(high) >= 0)
    assert low + high == pytest.approx(1)


def test_band_filters_peak_or_reject_at_their_centers() -> None:
    frequencies = np.linspace(0, NYQUIST, 2401)
    center = int(np.argmin(np.abs(frequencies - 420)))
    second = int(np.argmin(np.abs(frequencies - 760)))
    band_pass = filter_response(frequencies, "Band-pass", 420, 100, 760, 0)
    notch = filter_response(frequencies, "Notch", 420, 100, 760, 0)
    dual = filter_response(frequencies, "Dual band-pass", 420, 100, 760, 0)

    assert band_pass[center] == pytest.approx(1)
    assert notch[center] < 0.04
    assert dual[center] == pytest.approx(1)
    assert dual[second] == pytest.approx(1)
    assert dual[int(np.argmin(np.abs(frequencies - 590)))] < 0.01


def test_peaking_filter_converts_decibel_gain_to_amplitude() -> None:
    frequencies = np.array([0.0, 420.0, 1200.0])
    response = filter_response(frequencies, "Peaking", 420, 100, 760, 12)

    assert response[1] == pytest.approx(10 ** (12 / 20))
    assert response[[0, 2]] == pytest.approx(1, abs=1e-8)


def test_elliptic_band_pass_has_strong_out_of_band_rejection() -> None:
    frequencies = np.linspace(0, NYQUIST, 2401)
    response = filter_response(frequencies, "Elliptic band-pass", 420, 100, 760, 0)

    center = int(np.argmin(np.abs(frequencies - 420)))
    assert response[center] > 0.8
    assert response[0] < 0.01
    assert response[-1] < 0.01


def test_comb_reject_repeats_notches_at_requested_spacing() -> None:
    frequencies = np.array([420.0, 520.0, 620.0, 470.0])
    response = filter_response(frequencies, "Comb reject", 420, 100, 760, 0)

    assert np.all(response[:3] < 0.05)
    assert response[3] > 0.95


def test_filter_response_rejects_unknown_filter() -> None:
    with pytest.raises(ValueError, match="Unknown filter"):
        filter_response(np.arange(4), "Missing", 420, 100, 760, 0)


def test_no_filter_reconstructs_the_original_signal() -> None:
    signal = np.random.default_rng(3).normal(size=BLOCK_SIZE)
    filtered, response, center = apply_filter(signal, "No filter", 420, 100, 760, 0)

    assert filtered == pytest.approx(signal, abs=1e-12)
    assert np.all(response == 1)
    assert center == 420


def test_adaptive_notch_detects_and_suppresses_the_strongest_tone() -> None:
    time = np.arange(BLOCK_SIZE) / SAMPLE_RATE
    signal = np.sin(2 * np.pi * 600 * time) + 0.1 * np.sin(2 * np.pi * 200 * time)
    filtered, response, center = apply_filter(signal, "Adaptive notch", 420, 80, 760, 0)

    frequencies = np.fft.rfftfreq(BLOCK_SIZE, 1 / SAMPLE_RATE)
    detected = int(np.argmin(np.abs(frequencies - center)))
    assert center == pytest.approx(600, abs=SAMPLE_RATE / BLOCK_SIZE)
    assert response[detected] < 0.03
    assert np.std(filtered) < np.std(signal) / 2


def test_power_spectrum_finds_tone_and_applies_floor() -> None:
    time = np.arange(BLOCK_SIZE) / SAMPLE_RATE
    signal = np.sin(2 * np.pi * 300 * time)
    frequencies, power = power_spectrum_db(signal)

    assert frequencies[np.argmax(power)] == pytest.approx(300, abs=SAMPLE_RATE / BLOCK_SIZE)
    assert power.min() >= SPECTRUM_FLOOR
    assert np.isfinite(power).all()


def test_apply_response_db_clips_and_returns_compact_array() -> None:
    power = np.array([-80.0, -10.0, 3.0, 10.0])
    unchanged = apply_response_db(power, np.ones(4))
    attenuated = apply_response_db(power, np.full(4, 0.1))

    assert unchanged.dtype == np.float32
    assert unchanged.tolist() == [SPECTRUM_FLOOR, -10.0, 3.0, SPECTRUM_CEILING]
    assert attenuated[1] == pytest.approx(-30)
    assert attenuated.min() >= SPECTRUM_FLOOR
