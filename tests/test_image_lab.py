"""Test the image processing demo."""

from __future__ import annotations

import numpy as np
from bokeh.document import Document
from bokeh.models import BoxAnnotation, Button, ColumnDataSource, Div, PanTool, Select, Slider

from catalog import load_applications


def test_hubble_filters_and_editable_crop_update_the_result() -> None:
    document = Document()
    load_applications()["/image-processing"](document)
    operation = next(
        select for select in document.select({"type": Select}) if select.title == "Processing step"
    )
    reset_crop = next(
        button for button in document.select({"type": Button}) if button.label == "Reset crop"
    )
    processed = document.select_one({"type": ColumnDataSource, "name": "hubble-processed-image"})
    crop_box = document.select_one({"type": BoxAnnotation, "name": "hubble-crop-box"})
    crop_handles = document.select_one({"type": ColumnDataSource, "name": "hubble-crop-handles"})
    report = document.select_one({"type": Div, "name": "hubble-processing-report"})
    source_plot = document.select_one({"name": "hubble-source-plot"})
    processed_plot = document.select_one({"name": "hubble-processed-plot"})
    source_heading = document.select_one({"type": Div, "name": "hubble-source-heading"})
    processed_heading = document.select_one({"type": Div, "name": "hubble-processed-heading"})

    assert len(operation.options) >= 8
    assert reset_crop.margin == (22, 0, 0, 0)
    assert reset_crop.height == 31
    assert not crop_box.editable
    assert set(source_plot.js_event_callbacks) == {"panstart", "pan", "panend"}
    pan_callback = source_plot.js_event_callbacks["pan"][0]
    assert "box.update" in pan_callback.code
    assert "handles.change.emit()" in pan_callback.code
    assert len(crop_handles.data["x"]) == 4
    assert len(source_plot.toolbar.tools) == 1
    assert isinstance(source_plot.toolbar.active_drag, PanTool)
    assert processed_plot.toolbar.tools == []
    assert source_heading.height == processed_heading.height
    assert "01" in source_heading.text
    assert "Source image" in source_heading.text
    assert "Editable crop" in source_heading.text
    assert "border-bottom" in source_heading.text
    strength = next(
        slider for slider in document.select({"type": Slider}) if slider.title == "Edge gain"
    )
    results = []
    for option in operation.options:
        operation.value = option
        results.append(processed.data["image"][0].copy())
        assert f"<strong>{option}</strong> applied" in report.text
        assert option in processed_heading.text
        assert strength.visible == (option not in {"Natural color", "Luminance"})
    assert all(not np.array_equal(results[0], result) for result in results[1:])

    operation.value = "Sobel edges"
    edges = processed.data["image"][0].copy()
    strength.value = 3.0
    assert not np.array_equal(edges, processed.data["image"][0])

    crop_box.update(left=0, right=0.48, bottom=1 - 480 / 872, top=1)
    assert "x=0:480" in report.text
    assert "y=0:480" in report.text
