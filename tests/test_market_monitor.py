"""Test the market monitor demo."""

from __future__ import annotations

import numpy as np
import pytest
from bokeh.document import Document
from bokeh.models import ColumnDataSource, Div, FixedTicker, HoverTool, Select, Slider, Toggle

from apps._common.colors import CORAL, TEAL
from catalog import load_applications


def test_market_simulation_can_be_paused() -> None:
    document = Document()
    load_applications()["/market-monitor"](document)
    playback = next(
        toggle for toggle in document.select({"type": Toggle}) if toggle.label == "Pause simulation"
    )
    playback.active = False
    assert playback.label == "Resume simulation"
    volume = document.select_one({"name": "market-volume-plot"})
    macd = document.select_one({"name": "market-macd-plot"})
    price = document.select_one({"name": "market-price-plot"})
    hover = next(tool for tool in price.toolbar.tools if isinstance(tool, HoverTool))
    assert len(hover.renderers) == 1
    assert volume.title.text == "Volume (millions)"
    assert volume.yaxis[0].axis_label is None
    assert volume.xaxis[0].axis_label is None
    assert macd.xaxis[0].axis_label is None
    assert volume.toolbar.tools == []
    assert macd.toolbar.tools == []
    positive_fill = document.select_one({"name": "market-macd-positive"})
    negative_fill = document.select_one({"name": "market-macd-negative"})
    assert positive_fill.glyph.fill_color == TEAL
    assert negative_fill.glyph.fill_color == CORAL
    assert positive_fill.glyph.fill_alpha == 0.14
    assert negative_fill.glyph.fill_alpha == 0.14
    regime_note = document.select_one({"type": Div, "name": "market-regime-note"})
    assert "upward drift" in regime_note.text
    source = document.select_one({"type": ColumnDataSource, "name": "market-price"})
    steady_closes = np.asarray(source.data["close"])
    regime = next(
        select for select in document.select({"type": Select}) if select.title == "Market regime"
    )
    regime.value = "Range-bound"
    assert "tighter band" in regime_note.text
    range_closes = np.asarray(source.data["close"])
    regime.value = "Stress test"
    assert "highest volatility" in regime_note.text
    assert "affects new bars only" in regime_note.text
    assert "margin-top:6px" in regime_note.text
    stress_closes = np.asarray(source.data["close"])
    assert steady_closes[-1] > steady_closes[0]
    assert np.ptp(range_closes) < np.ptp(steady_closes)
    assert stress_closes[-1] < stress_closes[0]
    assert np.std(np.diff(stress_closes)) > np.std(np.diff(steady_closes))


def test_market_streams_one_intraday_bar_at_each_update() -> None:
    document = Document()
    load_applications()["/market-monitor"](document)
    source = document.select_one({"type": ColumnDataSource, "name": "market-price"})
    indicator = document.select_one({"type": ColumnDataSource, "name": "market-macd"})
    speed = next(
        select for select in document.select({"type": Select}) if select.title == "Replay pace"
    )
    assert speed.value == "Fast"
    assert len(source.data["date"]) == 64
    assert len(indicator.data["date"]) == 64
    assert np.equal(np.diff(source.data["index"]), 1).all()
    price_plot = document.select_one({"name": "market-price-plot"})
    assert isinstance(price_plot.xaxis[0].ticker, FixedTicker)
    assert len(price_plot.xaxis[0].ticker.ticks) == 6
    assert all(":" in label for label in price_plot.xaxis[0].major_label_overrides.values())
    for date in source.data["date"]:
        minutes = date.hour * 60 + date.minute
        assert minutes >= 9 * 60 + 30
        assert minutes <= 15 * 60 + 45
        assert date.dayofweek < 5
    for index, (macd, signal) in enumerate(
        zip(indicator.data["macd"], indicator.data["signal"], strict=True)
    ):
        assert indicator.data["positive_macd"][index] == pytest.approx(max(macd, signal), abs=5e-8)
        assert indicator.data["negative_macd"][index] == pytest.approx(min(macd, signal), abs=5e-8)
        assert indicator.data["positive_signal"][index] == pytest.approx(signal, abs=5e-8)
        assert indicator.data["negative_signal"][index] == pytest.approx(signal, abs=5e-8)
    previous_indices = list(source.data["index"])
    volatility = next(
        slider
        for slider in document.select({"type": Slider})
        if slider.title == "Volatility multiplier"
    )
    volatility.value = 2.0
    assert source.data["index"] == previous_indices
    previous_date = source.data["date"][-1]
    speed.value = "Fast"
    min(document.session_callbacks, key=lambda callback: callback.period).callback()
    assert len(source.data["date"]) == 64
    assert source.data["index"] == [*previous_indices[1:], previous_indices[-1] + 1]
    assert source.data["date"][-1] > previous_date
