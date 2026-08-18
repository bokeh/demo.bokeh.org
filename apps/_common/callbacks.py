"""Connect browser-throttled controls to Python callbacks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bokeh.models import ColumnDataSource, CustomJS, Slider

THROTTLED_SLIDER_JS = Path(__file__).with_name("throttled_slider.js").read_text()


def on_throttled_value(
    slider: Slider,
    callback: Callable[[str, object, object], None],
    *,
    wait: int = 100,
    name: str | None = None,
) -> ColumnDataSource:
    """Run a Python slider callback at most once per ``wait`` milliseconds while dragging."""
    if wait <= 0:
        raise ValueError("wait must be positive")

    slider.syncable = False
    request = ColumnDataSource(data={"value": [slider.value]}, name=name)
    browser_callback = CustomJS(
        args={"request": request}, code=f"const wait = {wait}\n{THROTTLED_SLIDER_JS}"
    )
    slider.js_on_change("value", browser_callback)
    slider.js_on_change("value_throttled", browser_callback)

    def forward_value(_attr: str, _old: object, new: dict[str, list[float]]) -> None:
        old_value = slider.value
        new_value = new["value"][0]
        slider.value = new_value
        callback("value", old_value, new_value)

    request.on_change("data", forward_value)
    return request
