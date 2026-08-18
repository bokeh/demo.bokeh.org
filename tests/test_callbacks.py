"""Test shared callback helpers."""

from __future__ import annotations

from bokeh.models import Slider

from apps._common.callbacks import on_throttled_value


def test_on_throttled_value_forwards_requests_and_flushes_on_release() -> None:
    slider = Slider(start=0, end=10, value=2)
    changes: list[tuple[object, object]] = []

    request = on_throttled_value(
        slider,
        lambda _attr, old, new: changes.append((old, new)),
        wait=100,
        name="test-slider-request",
    )
    request.data = {"value": [7]}

    assert not slider.syncable
    assert slider.value == 7
    assert changes == [(2, 7)]
    callbacks = slider.js_property_callbacks
    assert set(callbacks) == {"change:value", "change:value_throttled"}
    assert all(
        "const wait = 100" in callback.code for group in callbacks.values() for callback in group
    )
    assert all("setTimeout" in callback.code for group in callbacks.values() for callback in group)
