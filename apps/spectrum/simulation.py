"""Keep the structured example's NumPy and SciPy work independent of Bokeh."""

from __future__ import annotations

import numpy as np
from scipy.signal import ellip, get_window, periodogram, sosfreqz

SEED = 3102026
SAMPLE_RATE = 2400.0
NYQUIST = SAMPLE_RATE / 2
BLOCK_SIZE = 512
SPECTRUM_FLOOR = -72.0
SPECTRUM_CEILING = 4.0


def generate_signal_block(
    scene: str, start_time: float, noise: float, rng: np.random.Generator, burst: bool
) -> tuple[np.ndarray, np.ndarray]:
    time = start_time + np.arange(BLOCK_SIZE) / SAMPLE_RATE
    match scene:
        case "Telemetry link":
            phase = 2 * np.pi * 420 * time + 1.25 * np.sin(2 * np.pi * 3.2 * time)
            signal = np.sin(phase) + 0.34 * np.sin(2 * np.pi * 505 * time)
        case "Radar sweep":
            sweep_period = 3.2
            local_time = np.mod(time, sweep_period)
            sweep_rate = (1050 - 130) / sweep_period
            phase = 2 * np.pi * (130 * local_time + 0.5 * sweep_rate * local_time**2)
            signal = 1.15 * np.sin(phase) + 0.22 * np.sin(2 * np.pi * 760 * time)
        case "Frequency hopping":
            channels = np.array([210, 335, 480, 625, 810, 1010], dtype=float)
            channel = channels[np.floor(time / 0.24).astype(int) % len(channels)]
            phase = 2 * np.pi * np.cumsum(channel) / SAMPLE_RATE
            signal = np.sin(phase) + 0.18 * np.sin(2 * np.pi * 90 * time)
        case "Crowded band":
            signal = (
                0.72 * np.sin(2 * np.pi * 185 * time)
                + 0.5 * np.sin(2 * np.pi * 380 * time + 0.4 * np.sin(2 * np.pi * 2 * time))
                + 0.82 * np.sin(2 * np.pi * 690 * time)
                + 0.42 * np.sin(2 * np.pi * 940 * time)
            )
            scheduled_burst = np.mod(time, 2.7) < 0.055
            signal += scheduled_burst * rng.normal(0, 2.0, BLOCK_SIZE)
        case "Satellite Doppler pass":
            pass_period = 8.0
            orbit_phase = 2 * np.pi * time / pass_period
            carrier_phase = 2 * np.pi * 600 * time + 370 * pass_period * np.sin(orbit_phase)
            visibility = 0.25 + 0.9 * (0.5 + 0.5 * np.sin(orbit_phase)) ** 2
            signal = visibility * np.sin(carrier_phase) + 0.14 * np.sin(2 * np.pi * 110 * time)
        case "Drifting interferer":
            drift_period = 7.5
            drift_phase = 2 * np.pi * 620 * time - 390 * drift_period * np.cos(
                2 * np.pi * time / drift_period
            )
            telemetry_phase = 2 * np.pi * 420 * time + 0.8 * np.sin(2 * np.pi * 2.4 * time)
            signal = 1.45 * np.sin(drift_phase) + 0.36 * np.sin(telemetry_phase)
        case "Intermodulation products":
            drive = 0.82 * np.sin(2 * np.pi * 240 * time) + 0.68 * np.sin(2 * np.pi * 370 * time)
            signal = drive + 0.22 * drive**3
        case "Packet radio traffic":
            slot_length = 0.22
            slot = np.floor(time / slot_length).astype(np.int64)
            local_time = np.mod(time, slot_length) / slot_length
            active = ((slot * 5 + 3) % 11) < 7
            channels = np.array([170, 315, 505, 735, 980], dtype=float)
            channel = channels[(slot * 7 + 2) % len(channels)]
            amplitude = 0.8 + 0.5 * ((slot * 3 + 1) % 5) / 4
            envelope = active * amplitude * np.sin(np.pi * local_time) ** 2
            signal = envelope * np.sin(2 * np.pi * channel * time) + 0.10 * np.sin(
                2 * np.pi * 95 * time
            )
        case "Spread-spectrum link":
            chip_index = np.floor(time * 260).astype(np.int64)
            chips = np.where(((chip_index * 13 + 7) % 31) < 15, 1.0, -1.0)
            carrier = np.sin(2 * np.pi * 650 * time)
            signal = 0.9 * chips * carrier + 0.12 * carrier
        case _:
            raise ValueError(f"Unknown spectrum scene: {scene}")

    if burst:
        envelope = np.exp(-0.5 * ((np.arange(BLOCK_SIZE) - BLOCK_SIZE * 0.52) / 42) ** 2)
        signal += 2.6 * envelope * np.sin(2 * np.pi * 870 * time)
    signal += rng.normal(0, noise, BLOCK_SIZE)
    return time, signal


def filter_response(
    frequencies: np.ndarray,
    mode: str,
    center: float,
    bandwidth: float,
    second_center: float,
    gain_db: float,
) -> np.ndarray:
    sigma = max(bandwidth / 2.355, 1.0)
    bell = np.exp(-0.5 * ((frequencies - center) / sigma) ** 2)
    transition = max(bandwidth / 8, 2.0)
    low_pass = 1 / (1 + np.exp(np.clip((frequencies - center) / transition, -60, 60)))
    band_left = 1 / (
        1 + np.exp(np.clip((center - bandwidth / 2 - frequencies) / transition, -60, 60))
    )
    band_right = 1 / (
        1 + np.exp(np.clip((frequencies - center - bandwidth / 2) / transition, -60, 60))
    )
    flat_band = band_left * band_right
    match mode:
        case "No filter":
            return np.ones_like(frequencies)
        case "Low-pass":
            return low_pass
        case "High-pass":
            return 1 - low_pass
        case "Band-pass":
            return bell
        case "Wide band-stop":
            return 1 - 0.985 * flat_band
        case "Dual band-pass":
            second_bell = np.exp(-0.5 * ((frequencies - second_center) / sigma) ** 2)
            return np.maximum(bell, second_bell)
        case "Adaptive notch":
            return 1 - 0.985 * bell
        case "Peaking":
            boost = 10 ** (gain_db / 20)
            return 1 + (boost - 1) * bell
        case "Elliptic band-pass":
            low = max(1.0, center - bandwidth / 2)
            high = min(NYQUIST - 1.0, center + bandwidth / 2)
            sos = ellip(5, 1, 45, [low, high], btype="bandpass", fs=SAMPLE_RATE, output="sos")
            _frequencies, response = sosfreqz(sos, worN=frequencies, fs=SAMPLE_RATE)
            return np.abs(response)
        case "Notch":
            return 1 - 0.97 * bell
        case "Comb reject":
            spacing = max(bandwidth, 50.0)
            distance = np.abs((frequencies - center + spacing / 2) % spacing - spacing / 2)
            tooth_width = max(7.0, spacing * 0.06)
            rejection = np.exp(-0.5 * (distance / tooth_width) ** 2)
            return 1 - 0.96 * rejection
        case _:
            raise ValueError(f"Unknown filter: {mode}")


def apply_filter(
    signal: np.ndarray,
    mode: str,
    center: float,
    bandwidth: float,
    second_center: float,
    gain_db: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    frequencies = np.fft.rfftfreq(len(signal), 1 / SAMPLE_RATE)
    effective_center = center
    if mode == "Adaptive notch":
        window = np.asarray(get_window("hann", len(signal)), dtype=np.float64)
        magnitude = np.abs(np.fft.rfft(signal * window))
        magnitude[frequencies < 25] = 0
        effective_center = float(frequencies[np.argmax(magnitude)])
    response = filter_response(
        frequencies, mode, effective_center, bandwidth, second_center, gain_db
    )
    filtered = np.fft.irfft(np.fft.rfft(signal) * response, n=len(signal))
    return filtered, response, effective_center


def power_spectrum_db(signal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    frequencies, power = periodogram(signal, fs=SAMPLE_RATE, window="hann", scaling="spectrum")
    decibels = 10 * np.log10(np.maximum(power, 10 ** (SPECTRUM_FLOOR / 10)))
    return frequencies, decibels


def apply_response_db(power: np.ndarray, response: np.ndarray) -> np.ndarray:
    attenuation = 20 * np.log10(np.maximum(response, 1e-4))
    return np.clip(power + attenuation, SPECTRUM_FLOOR, SPECTRUM_CEILING).astype(np.float32)
