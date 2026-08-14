"""Coordinate the per-session state and callbacks for the structured example."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from bokeh.document import Document
from bokeh.events import Event, Tap

from apps._common.colors import PLUM
from apps.spectrum.simulation import (
    BLOCK_SIZE,
    NYQUIST,
    SAMPLE_RATE,
    SEED,
    SPECTRUM_FLOOR,
    apply_filter,
    apply_response_db,
    generate_signal_block,
    power_spectrum_db,
)
from apps.spectrum.view import (
    CHALK,
    HISTORY_ROWS,
    HISTORY_SECONDS,
    SCENES,
    UPDATE_TICKS,
    SpectrumView,
)

type HistoryUpdate = Literal["append", "preserve", "replace"]
type FilterSignature = tuple[str, float, float, float, float]


@dataclass(slots=True)
class ReceiverState:
    rng: np.random.Generator
    raw_history: np.ndarray
    raw: np.ndarray
    time: float = 0.0
    ticks: int = 0
    burst: bool = False
    filter_signature: FilterSignature | None = None

    def reset(self) -> None:
        self.rng = np.random.default_rng(SEED)
        self.raw_history.fill(SPECTRUM_FLOOR)
        self.raw.fill(0)
        self.time = 0.0
        self.ticks = 0
        self.burst = False


def filter_explanation(mode: str, effective_center: float, gain_db: float) -> str:
    match mode:
        case "No filter":
            return "No filter is active, so every track and the full noise floor remain visible."
        case "Low-pass":
            return "Only frequencies below the gold cutoff pass; higher-frequency tracks darken immediately."
        case "High-pass":
            return "Only frequencies above the gold cutoff pass; lower-frequency tracks darken immediately."
        case "Band-pass":
            return "Only energy inside the gold band passes; everything outside it darkens immediately."
        case "Wide band-stop":
            return "A broad interval inside the gold band is rejected while frequencies on both sides pass."
        case "Dual band-pass":
            return "Two separated gold passbands isolate a pair of channels while rejecting the spectrum between them."
        case "Adaptive notch":
            return (
                f"The notch follows the strongest detected tone automatically—currently {effective_center:.0f} "
                "Hz—and suppresses it as the signal moves."
            )
        case "Peaking":
            return f"A {gain_db:.0f} dB bell-shaped boost emphasizes energy around the gold center frequency."
        case "Elliptic band-pass":
            return "A steep SciPy-designed elliptic response passes the gold band with visible ripple and strong rejection outside it."
        case "Notch":
            return "Energy inside the gold band is rejected, leaving a dark vertical gap at that frequency."
        case "Comb reject":
            return "A repeating bank of narrow notches removes regularly spaced frequencies; the gold line marks one tooth."
        case _:
            raise ValueError(mode)


def receiver_status_html(
    frequencies: np.ndarray,
    raw_power: np.ndarray,
    filtered_power: np.ndarray,
    mode: str,
    effective_center: float,
    second_center: float,
    bandwidth: float,
    signal_time: float,
) -> str:
    peak_index = int(np.argmax(filtered_power[1:]) + 1)
    raw_linear = np.sum(10 ** (raw_power / 10))
    filtered_linear = np.sum(10 ** (filtered_power / 10))
    band = np.abs(frequencies - effective_center) <= bandwidth / 2
    if mode == "Dual band-pass":
        band |= np.abs(frequencies - second_center) <= bandwidth / 2
    band_power = 10 * np.log10(max(np.sum(10 ** (filtered_power[band] / 10)), 1e-12))
    power_ratio = filtered_linear / max(raw_linear, 1e-12)
    if mode == "Peaking":
        power_change = 100 * max(0.0, power_ratio - 1)
        power_change_label = "of received power added"
    else:
        power_change = 100 * max(0.0, 1 - power_ratio)
        power_change_label = "of received power removed"
    return (
        f'<div style="display:grid;width:100%;box-sizing:border-box;'
        f"grid-template-columns:1fr 1fr 1.35fr .9fr;gap:clamp(8px,2vw,28px);"
        f"align-items:baseline;padding:11px 13px;background:{PLUM};color:{CHALK};"
        f"white-space:nowrap;overflow:hidden;"
        'font-size:clamp(12px,1.4vw,16px);font-variant-numeric:tabular-nums">'
        f'<strong style="font:400 clamp(18px,2vw,24px) Georgia,serif">Peak '
        f'<span style="display:inline-block;min-width:3ch;text-align:right">{frequencies[peak_index]:.0f}</span> Hz</strong>'
        f'<span>Band power <b style="display:inline-block;min-width:5ch;text-align:right">{band_power:.1f}</b> dB</span>'
        f'<span><b style="display:inline-block;min-width:3ch;text-align:right">{power_change:.0f}</b>% {power_change_label}</span>'
        f'<span>Signal time <b style="display:inline-block;min-width:5ch;text-align:right">{signal_time:.1f}</b> s</span>'
        "</div>"
    )


@dataclass(slots=True)
class Receiver:
    view: SpectrumView
    state: ReceiverState = field(init=False)

    def __post_init__(self) -> None:
        self.state = ReceiverState(
            rng=np.random.default_rng(SEED),
            raw_history=self.view.sources.empty_history.copy(),
            raw=np.zeros(BLOCK_SIZE),
        )

    def connect(self, document: Document) -> None:
        controls = self.view.controls
        controls.scene.on_change("value", self.scene_changed)
        controls.filter_mode.on_change("value", self.filter_mode_changed)
        for control in (
            controls.center_frequency,
            controls.second_frequency,
            controls.bandwidth,
            controls.boost_gain,
        ):
            control.on_change("value", self.filter_settings_changed)
        controls.playing.on_change("active", self.playback_changed)
        self.view.plots.spectrogram.on_event(Tap, self.tune_filter)
        controls.inject_transient.on_click(self.queue_transient)
        controls.restart.on_click(self.reset_signal)
        self.configure_filter_controls()
        self.reset_signal()
        document.add_periodic_callback(self.update_receiver, 150)

    def replace_waterfall(self, response: np.ndarray) -> None:
        self.view.sources.history.data = {
            "image": [apply_response_db(self.state.raw_history, response)],
            "x": [0.0],
            "y": [-HISTORY_SECONDS],
            "dw": [NYQUIST],
            "dh": [HISTORY_SECONDS],
        }

    def append_waterfall_row(self, response: np.ndarray) -> None:
        latest = apply_response_db(self.state.raw_history[-1], response)[np.newaxis, :]
        self.view.sources.latest.data = {"image": [latest]}

    def update_filter_view(self, *, history_update: HistoryUpdate) -> None:
        controls = self.view.controls
        sources = self.view.sources
        filtered, response, effective_center = apply_filter(
            self.state.raw,
            controls.filter_mode.value,
            controls.center_frequency.value,
            controls.bandwidth.value,
            controls.second_frequency.value,
            controls.boost_gain.value,
        )
        frequencies, raw_power = power_spectrum_db(self.state.raw)
        _frequencies, filtered_power = power_spectrum_db(filtered)
        filter_signature = (
            controls.filter_mode.value,
            effective_center,
            controls.second_frequency.value,
            controls.bandwidth.value,
            controls.boost_gain.value,
        )
        if self.state.filter_signature != filter_signature:
            sources.response.data = {
                "frequency": frequencies.astype(np.float32),
                "gain": np.maximum(20 * np.log10(np.maximum(response, 1e-4)), -60).astype(
                    np.float32
                ),
            }
            self.state.filter_signature = filter_signature
        sources.power.data = {
            "frequency": frequencies,
            "raw": raw_power,
            "filtered": filtered_power,
        }
        match history_update:
            case "replace":
                self.replace_waterfall(response)
            case "append":
                self.append_waterfall_row(response)
            case "preserve":
                pass
            case _:
                raise ValueError(history_update)

        self.update_filter_guides(effective_center)
        self.view.status.text = receiver_status_html(
            frequencies,
            raw_power,
            filtered_power,
            controls.filter_mode.value,
            effective_center,
            controls.second_frequency.value,
            controls.bandwidth.value,
            self.state.time,
        )
        explanation = filter_explanation(
            controls.filter_mode.value, effective_center, controls.boost_gain.value
        )
        controls.watch_note.text = (
            f'<p style="margin:0"><strong>What to watch:</strong> '
            f"{SCENES[controls.scene.value]} {explanation} New measurements enter at the top of the "
            "waterfall and move downward as they age.</p>"
        )

    def update_filter_guides(self, effective_center: float) -> None:
        controls = self.view.controls
        match controls.filter_mode.value:
            case "Low-pass":
                left, right = 0.0, controls.center_frequency.value
            case "High-pass":
                left, right = controls.center_frequency.value, NYQUIST
            case _:
                left = max(0.0, effective_center - controls.bandwidth.value / 2)
                right = min(NYQUIST, effective_center + controls.bandwidth.value / 2)
        visible = controls.filter_mode.value not in ("No filter", "Comb reject")
        center_visible = controls.filter_mode.value != "No filter"
        for region, center in self.view.plots.filter_guides:
            region.left = left
            region.right = right
            region.visible = visible
            center.location = effective_center
            center.visible = center_visible

        second_visible = controls.filter_mode.value == "Dual band-pass"
        second_left = max(0.0, controls.second_frequency.value - controls.bandwidth.value / 2)
        second_right = min(NYQUIST, controls.second_frequency.value + controls.bandwidth.value / 2)
        for region, center in self.view.plots.second_filter_guides:
            region.left = second_left
            region.right = second_right
            region.visible = second_visible
            center.location = controls.second_frequency.value
            center.visible = second_visible

    def advance_signal(self) -> None:
        controls = self.view.controls
        block_time, raw = generate_signal_block(
            controls.scene.value,
            self.state.time,
            controls.noise.value,
            self.state.rng,
            self.state.burst,
        )
        self.state.burst = False
        self.state.raw = raw
        self.state.time = float(block_time[-1] + 1 / SAMPLE_RATE)
        _frequencies, raw_power = power_spectrum_db(raw)
        self.state.raw_history[:-1] = self.state.raw_history[1:]
        self.state.raw_history[-1] = raw_power.astype(np.float32)

    def update_receiver(self, *, force: bool = False) -> None:
        controls = self.view.controls
        if not controls.playing.active and not force:
            return
        if not force:
            self.state.ticks += 1
            if self.state.ticks < UPDATE_TICKS[controls.update_rate.value]:
                return
            self.state.ticks = 0
        self.advance_signal()
        self.update_filter_view(history_update="append")

    def reset_signal(self) -> None:
        self.state.reset()
        # Prime the waterfall so the first render is already informative.
        for _ in range(HISTORY_ROWS):
            self.advance_signal()
        self.update_filter_view(history_update="replace")

    def scene_changed(self, _attr: str, _old: object, _new: object) -> None:
        self.reset_signal()

    def configure_filter_controls(self) -> None:
        controls = self.view.controls
        match controls.filter_mode.value:
            case "Dual band-pass":
                controls.primary.children = [
                    controls.scene,
                    controls.filter_mode,
                    controls.update_rate,
                    controls.center_frequency,
                    controls.second_frequency,
                ]
                controls.specialized.children = [
                    controls.bandwidth,
                    controls.noise,
                    controls.playing,
                    controls.inject_transient,
                    controls.restart,
                ]
            case _:
                controls.primary.children = [
                    controls.scene,
                    controls.filter_mode,
                    controls.update_rate,
                    controls.center_frequency,
                    controls.bandwidth,
                ]
                controls.specialized.children = [
                    controls.boost_gain,
                    controls.noise,
                    controls.playing,
                    controls.inject_transient,
                    controls.restart,
                ]

        controls.center_frequency.visible = controls.filter_mode.value != "Adaptive notch"
        controls.second_frequency.visible = controls.filter_mode.value == "Dual band-pass"
        controls.boost_gain.visible = controls.filter_mode.value == "Peaking"
        self.view.plots.response_range.end = 20 if controls.filter_mode.value == "Peaking" else 1
        self.view.plots.spectrogram.xaxis.axis_label = (
            "Frequency (Hz) · adaptive notch tracks automatically"
            if controls.filter_mode.value == "Adaptive notch"
            else "Frequency (Hz) · tap anywhere to retune"
        )

        controls.center_frequency.title = "Center frequency (Hz)"
        controls.bandwidth.title = "Filter width (Hz)"
        controls.center_frequency.disabled = controls.filter_mode.value == "No filter"
        controls.bandwidth.disabled = controls.filter_mode.value == "No filter"
        match controls.filter_mode.value:
            case "No filter":
                controls.center_frequency.title = "Center frequency (unused)"
                controls.bandwidth.title = "Filter width (unused)"
            case "Low-pass" | "High-pass":
                controls.center_frequency.title = "Cutoff frequency (Hz)"
                controls.bandwidth.title = "Transition width (Hz)"
            case "Dual band-pass":
                controls.center_frequency.title = "First passband center (Hz)"
                controls.second_frequency.title = "Second passband center (Hz)"
                controls.bandwidth.title = "Passband width (Hz)"
            case "Adaptive notch":
                controls.bandwidth.title = "Adaptive notch width (Hz)"
            case "Peaking":
                controls.center_frequency.title = "Boost center (Hz)"
                controls.bandwidth.title = "Boost width (Hz)"
            case "Elliptic band-pass":
                controls.center_frequency.title = "Passband center (Hz)"
                controls.bandwidth.title = "Passband width (Hz)"
            case "Comb reject":
                controls.center_frequency.title = "First notch near (Hz)"
                controls.bandwidth.title = "Notch spacing (Hz)"

    def filter_settings_changed(self, _attr: str, _old: object, _new: object) -> None:
        # Adaptive settings affect new measurements; manual settings reprocess visible history.
        self.update_filter_view(
            history_update=(
                "preserve"
                if self.view.controls.filter_mode.value == "Adaptive notch"
                else "replace"
            )
        )

    def filter_mode_changed(self, _attr: str, old: object, new: object) -> None:
        self.configure_filter_controls()
        history_update: HistoryUpdate = "preserve" if "Adaptive notch" in (old, new) else "replace"
        self.update_filter_view(history_update=history_update)

    def playback_changed(self, _attr: str, _old: bool, active: bool) -> None:
        self.view.controls.playing.label = "Pause" if active else "Resume"

    def tune_filter(self, event: Event) -> None:
        controls = self.view.controls
        if (
            not isinstance(event, Tap)
            or event.x is None
            or controls.filter_mode.value == "Adaptive notch"
        ):
            return
        controls.center_frequency.value = min(
            controls.center_frequency.end,
            max(controls.center_frequency.start, round(event.x / 5) * 5),
        )

    def queue_transient(self) -> None:
        self.state.burst = True
        if not self.view.controls.playing.active:
            self.update_receiver(force=True)
