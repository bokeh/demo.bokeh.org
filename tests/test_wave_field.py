"""Test the wave field demo."""

from __future__ import annotations

import math

import numpy as np
import pytest
from bokeh.document import Document
from bokeh.models import ColorBar, ColumnDataSource, Plot, Select, Slider

from catalog import load_applications


def test_wave_field_uses_webgl() -> None:
    document = Document()
    load_applications()["/wave-field"](document)
    plots = list(document.select({"type": Plot}))
    assert any(plot.output_backend == "webgl" for plot in plots)
    assert all(plot.toolbar.tools == [] for plot in plots)
    field_plot = document.select_one({"name": "wave-field-plot"})
    assert field_plot.x_range.start == pytest.approx(-field_plot.x_range.end, abs=5e-8)
    assert field_plot.x_range.end < 3.1
    color_bar = document.select_one({"type": ColorBar})
    assert color_bar.width == 14
    assert color_bar.margin == 0
    assert color_bar.padding == 0
    assert color_bar.location == (6, 0)
    section = document.select_one({"type": ColumnDataSource, "name": "wave-cross-section"})
    assert len(section.data["x"]) >= 400
    field_source = document.select_one({"type": ColumnDataSource, "name": "wave-field-values"})
    assert len(field_source.data["z"]) > 2025
    field_model = next(
        select for select in document.select({"type": Select}) if select.title == "Field model"
    )
    assert len(field_model.options) >= 9
    assert {"Quasicrystal interference", "Airy diffraction"} <= set(field_model.options)
    model_samples = []
    for option in field_model.options:
        field_model.value = option
        model_samples.append(tuple(np.round(field_source.data["z"][:20], 6)))
        assert np.isfinite(section.data["z"]).all()
    assert len(set(model_samples)) == len(field_model.options)
    field_model.value = "Interference"
    cross_section = next(
        slider for slider in document.select({"type": Slider}) if slider.title == "Cross-section y"
    )
    cross_section.value = 0.05
    cross_section.trigger("value_throttled", cross_section.value_throttled, cross_section.value)
    x = section.data["x"][0]
    expected = math.sin(1.8 * x) * math.cos(1.8 * cross_section.value) + 0.7 * math.sin(
        x * cross_section.value
    )
    assert section.data["z"][0] == pytest.approx(expected, abs=5e-8)
