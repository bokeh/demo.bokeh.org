"""Test the spectrum monitor demo."""

from __future__ import annotations

import numpy as np
from bokeh.document import Document
from bokeh.models import ColumnDataSource, Select, Slider

from apps._common.colors import PLUM
from catalog import load_applications


def test_spectrum_streams_float32_history_and_filtered_power() -> None:
    document = Document()
    load_applications()["/spectrum-monitor"](document)
    history = document.select_one({"type": ColumnDataSource, "name": "spectrum-history"})
    latest = document.select_one({"type": ColumnDataSource, "name": "spectrum-latest-row"})
    power = document.select_one({"type": ColumnDataSource, "name": "spectrum-power"})
    response = document.select_one({"type": ColumnDataSource, "name": "spectrum-filter-response"})
    response_plot = document.select_one({"name": "spectrum-filter-response-plot"})
    assert history.data["image"][0].dtype == np.float32
    assert history.data["image"][0].shape[0] > 80
    assert history.data["image"][0].shape[1] > 200
    assert latest.data["image"][0].shape == (1, history.data["image"][0].shape[1])
    assert len(power.data["frequency"]) == history.data["image"][0].shape[1]
    assert len(response.data["frequency"]) == len(power.data["frequency"])
    assert response_plot.x_range == document.select_one({"name": "spectrum-power-plot"}).x_range
    assert min(response.data["gain"]) <= -50
    assert max(response.data["gain"]) > -0.01
    previous_history = history.data["image"][0].copy()
    previous_latest = latest.data["image"][0].copy()
    previous_response = response.data["gain"].copy()
    periodic = min(document.session_callbacks, key=lambda callback: callback.period)
    periodic.callback()
    periodic.callback()
    assert np.array_equal(history.data["image"][0], previous_history)
    assert not np.array_equal(latest.data["image"][0], previous_latest)
    assert np.array_equal(response.data["gain"], previous_response)
    signal_scene = next(
        select for select in document.select({"type": Select}) if select.title == "Signal scene"
    )
    assert {
        "Satellite Doppler pass",
        "Drifting interferer",
        "Intermodulation products",
        "Packet radio traffic",
        "Spread-spectrum link",
    } <= set(signal_scene.options)
    scene_histories = {}
    for option in signal_scene.options:
        signal_scene.value = option
        scene_histories[option] = history.data["image"][0].copy()
    for first, second in zip(signal_scene.options, signal_scene.options[1:], strict=False):
        assert not np.array_equal(scene_histories[first], scene_histories[second])
    signal_scene.value = "Telemetry link"
    receiver_filter = next(
        select for select in document.select({"type": Select}) if select.title == "Receiver filter"
    )
    assert {
        "Low-pass",
        "High-pass",
        "Wide band-stop",
        "Dual band-pass",
        "Adaptive notch",
        "Peaking",
        "Elliptic band-pass",
        "Comb reject",
    } <= set(receiver_filter.options)
    band_pass_history = history.data["image"][0].copy()
    receiver_filter.value = "Notch"
    assert not np.array_equal(history.data["image"][0], band_pass_history)
    assert not np.array_equal(response.data["gain"], previous_response)
    notch_history = history.data["image"][0].copy()
    receiver_filter.value = "No filter"
    assert not np.array_equal(history.data["image"][0], notch_history)
    receiver_filter.value = "Notch"
    periodic = min(document.session_callbacks, key=lambda callback: callback.period)
    periodic.callback()
    periodic.callback()
    assert not np.array_equal(power.data["raw"], power.data["filtered"])
    filter_histories = {}
    for option in receiver_filter.options:
        receiver_filter.value = option
        filter_histories[option] = history.data["image"][0].copy()
    for first, second in zip(receiver_filter.options, receiver_filter.options[1:], strict=False):
        if "Adaptive notch" in (first, second):
            assert np.array_equal(filter_histories[first], filter_histories[second])
            continue
        assert not np.array_equal(filter_histories[first], filter_histories[second])
    spectrum = document.select_one({"name": "spectrum-power-plot"})
    assert spectrum.output_backend == "canvas"
    center = document.select_one({"type": Slider, "name": "spectrum-center-frequency"})
    bandwidth = document.select_one({"type": Slider, "name": "spectrum-bandwidth"})
    primary_controls = document.select_one({"name": "spectrum-primary-controls"})
    specialized_controls = document.select_one({"name": "spectrum-specialized-controls"})
    noise_control = document.select_one({"type": Slider, "name": "spectrum-noise"})
    update_rate = next(
        select for select in document.select({"type": Select}) if select.title == "Update rate"
    )
    assert update_rate.value == "Fast"
    assert update_rate in primary_controls.children
    assert (noise_control.max_width, noise_control.sizing_mode) == (420, "stretch_width")
    receiver_filter.value = "Dual band-pass"
    second = document.select_one({"type": Slider, "name": "spectrum-second-frequency"})
    assert second.visible
    assert primary_controls.children[-2:] == [center, second]
    assert specialized_controls.children[:2] == [bandwidth, noise_control]
    assert bandwidth.value == 100
    layout_updates = []
    specialized_controls.on_change("children", lambda _attr, _old, new: layout_updates.append(new))
    bandwidth.value += 5
    bandwidth.trigger("value_throttled", bandwidth.value_throttled, bandwidth.value)
    assert layout_updates == []
    frequency = response.data["frequency"]
    first_index = int(np.argmin(np.abs(frequency - center.value)))
    second_index = int(np.argmin(np.abs(frequency - second.value)))
    middle_index = int(np.argmin(np.abs(frequency - (center.value + second.value) / 2)))
    assert response.data["gain"][first_index] > -0.1
    assert response.data["gain"][second_index] > -0.1
    assert response.data["gain"][middle_index] < -10
    receiver_filter.value = "Peaking"
    gain = document.select_one({"type": Slider, "name": "spectrum-boost-gain"})
    assert gain.visible
    assert specialized_controls.children[:2] == [gain, noise_control]
    assert max(response.data["gain"]) > 11.5
    assert response_plot.y_range.end == 20
    receiver_filter.value = "Adaptive notch"
    assert not center.visible
    adaptive_history = history.data["image"][0].copy()
    adaptive_latest = latest.data["image"][0].copy()
    adaptive_response = response.data["gain"].copy()
    bandwidth.value += 10
    bandwidth.trigger("value_throttled", bandwidth.value_throttled, bandwidth.value)
    assert np.array_equal(history.data["image"][0], adaptive_history)
    assert np.array_equal(latest.data["image"][0], adaptive_latest)
    assert not np.array_equal(response.data["gain"], adaptive_response)
    receiver_filter.value = "No filter"
    assert np.array_equal(history.data["image"][0], adaptive_history)
    console = document.select_one({"name": "spectrum-console"})
    assert console.styles["background"] == PLUM
