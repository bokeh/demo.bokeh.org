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
    value_callback = callbacks["change:value"][0]
    final_callback = callbacks["change:value_throttled"][0]
    assert "const wait = 100" in value_callback.code
    assert "const flush = false" in value_callback.code
    assert "value_throttled" not in value_callback.code
    assert "const flush = true" in final_callback.code
    assert "setTimeout" in value_callback.code
