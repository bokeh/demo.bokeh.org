"""Test the cellular automata demo."""

from __future__ import annotations

import numpy as np
from bokeh.document import Document
from bokeh.events import ButtonClick, Tap
from bokeh.models import (
    Button,
    ColumnDataSource,
    Div,
    LinearColorMapper,
    MultiChoice,
    Select,
    Slider,
)

from catalog import load_applications


def test_cellular_automata_evolves_and_supports_live_editing() -> None:
    document = Document()
    load_applications()["/cellular-automata"](document)
    field = document.select_one({"type": ColumnDataSource, "name": "automata-field"})
    history = document.select_one({"type": ColumnDataSource, "name": "automata-history"})
    field_plot = document.select_one({"name": "automata-field-plot"})
    history_plot = document.select_one({"name": "automata-history-plot"})
    rule = next(
        select for select in document.select({"type": Select}) if select.title == "Rule set"
    )
    seed = next(
        select for select in document.select({"type": Select}) if select.title == "Seed pattern"
    )
    density = next(
        slider for slider in document.select({"type": Slider}) if slider.title == "Random density"
    )
    step = next(
        button for button in document.select({"type": Button}) if button.label == "Single step"
    )
    clear = next(
        button for button in document.select({"type": Button}) if button.label == "Clear field"
    )
    rule_note = document.select_one({"type": Div, "name": "automata-rule-note"})

    assert field_plot.toolbar.tools == []
    assert history_plot.toolbar.tools == []
    assert field_plot.match_aspect
    assert field.data["image"][0].size > 10_000
    assert field.data["image"][0].dtype == np.uint16
    age_image = field_plot.select_one({"name": "automata-age-image"})
    assert isinstance(age_image.glyph.color_mapper, LinearColorMapper)
    assert age_image.glyph.color_mapper.high_color == age_image.glyph.color_mapper.palette[-1]
    cell_grid = field_plot.select_one({"name": "automata-cell-grid"})
    assert len(cell_grid.data_source.data["xs"]) == 210
    assert cell_grid.glyph.line_alpha < 0.2
    assert history_plot.select_one({"name": "automata-births-step"}).glyph.mode == "after"
    assert history_plot.select_one({"name": "automata-deaths-step"}).glyph.mode == "after"
    assert set(rule.options) == {
        "Conway's Life",
        "HighLife",
        "Seeds",
        "Day & Night",
        "Life without Death",
        "Custom rule",
    }
    assert len(seed.options) >= 6
    assert history.data["generation"] == [0]
    initial = field.data["image"][0].copy()

    step._trigger_event(ButtonClick(step))
    assert history.data["generation"][-1] == 1
    assert not np.array_equal(field.data["image"][0], initial)

    rule.value = "HighLife"
    assert "B36/S23" in rule_note.text
    assert history.data["generation"][-1] == 1

    seed.value = "Random soup"
    assert density.visible
    assert history.data["generation"] == [0]
    assert history.data["population"][0] > 0

    clear._trigger_event(ButtonClick(clear))
    assert history.data["population"] == [0]
    empty = field.data["image"][0].copy()
    field_plot._trigger_event(Tap(field_plot, sx=0, sy=0, x=12.4, y=18.7))
    assert history.data["population"] == [1]
    assert not np.array_equal(field.data["image"][0], empty)


def test_cellular_automata_history_follows_a_250_generation_window() -> None:
    document = Document()
    load_applications()["/cellular-automata"](document)
    history = document.select_one({"type": ColumnDataSource, "name": "automata-history"})
    history_plot = document.select_one({"name": "automata-history-plot"})
    step = next(
        button for button in document.select({"type": Button}) if button.label == "Single step"
    )

    for _ in range(275):
        step._trigger_event(ButtonClick(step))

    assert len(history.data["generation"]) == 250
    assert history.data["generation"][-1] == 275
    assert history_plot.x_range.end == 276
    assert history_plot.x_range.start == 26


def test_cellular_automata_compares_rules_from_the_same_state() -> None:
    document = Document()
    load_applications()["/cellular-automata"](document)
    field = document.select_one({"type": ColumnDataSource, "name": "automata-field"})
    history = document.select_one({"type": ColumnDataSource, "name": "automata-history"})
    field_plot = document.select_one({"name": "automata-field-plot"})
    history_plot = document.select_one({"name": "automata-history-plot"})
    experiment = next(
        select for select in document.select({"type": Select}) if select.title == "Experiment"
    )
    rule = next(
        select for select in document.select({"type": Select}) if select.title == "Rule set"
    )
    comparison_rule = next(
        select for select in document.select({"type": Select}) if select.title == "Rule B"
    )
    seed = next(
        select for select in document.select({"type": Select}) if select.title == "Seed pattern"
    )
    step = next(
        button for button in document.select({"type": Button}) if button.label == "Single step"
    )
    comparison_legend = document.select_one({"name": "automata-comparison-legend"})
    births = history_plot.select_one({"name": "automata-births-step"})
    comparison_population = history_plot.select_one({"name": "automata-comparison-population"})
    divergence = history_plot.select_one({"name": "automata-divergence-step"})

    seed.value = "Random soup"
    experiment.value = "Compare rules"
    assert rule.title == "Rule A"
    assert comparison_rule.visible
    assert rule.value != comparison_rule.value
    assert field_plot.title.text == "Rule divergence"
    assert comparison_legend.visible
    assert not births.visible
    assert comparison_population.visible
    assert divergence.visible
    assert field.data["image"][0].dtype == np.uint8
    assert history.data["divergence"][-1] == 0

    for _ in range(4):
        step._trigger_event(ButtonClick(step))

    assert history.data["divergence"][-1] > 0
    assert history.data["population"][-1] != history.data["comparison_population"][-1]


def test_cellular_automata_pattern_brush_rotates_and_stamps() -> None:
    document = Document()
    load_applications()["/cellular-automata"](document)
    history = document.select_one({"type": ColumnDataSource, "name": "automata-history"})
    field_plot = document.select_one({"name": "automata-field-plot"})
    brush = next(
        select for select in document.select({"type": Select}) if select.title == "Drawing tool"
    )
    clear = next(
        button for button in document.select({"type": Button}) if button.label == "Clear field"
    )
    rotate = next(
        button
        for button in document.select({"type": Button})
        if button.label.startswith("Rotation")
    )
    flip = next(
        button for button in document.select({"type": Button}) if button.label.startswith("Mirror")
    )
    playing = next(
        button for button in document.select({"type": Button}) if button.label == "Pause evolution"
    )

    clear._trigger_event(ButtonClick(clear))
    brush.value = "Glider"
    assert playing.label == "Resume evolution"
    assert rotate.visible
    assert flip.visible
    rotate._trigger_event(ButtonClick(rotate))
    flip._trigger_event(ButtonClick(flip))
    assert rotate.label == "Rotation · 90°"
    assert flip.label == "Mirror · on"

    field_plot._trigger_event(Tap(field_plot, sx=0, sy=0, x=64, y=40))
    assert history.data["population"] == [5]
    assert history.data["comparison_population"] == [5]


def test_cellular_automata_builds_independent_custom_rules() -> None:
    document = Document()
    load_applications()["/cellular-automata"](document)
    history = document.select_one({"type": ColumnDataSource, "name": "automata-history"})
    field_plot = document.select_one({"name": "automata-field-plot"})
    rule_note = document.select_one({"type": Div, "name": "automata-rule-note"})
    experiment = next(
        select for select in document.select({"type": Select}) if select.title == "Experiment"
    )
    rule = next(
        select for select in document.select({"type": Select}) if select.title == "Rule set"
    )
    comparison_rule = next(
        select for select in document.select({"type": Select}) if select.title == "Rule B"
    )
    primary_birth = document.select_one({"type": MultiChoice, "name": "automata-primary-birth"})
    primary_survival = document.select_one(
        {"type": MultiChoice, "name": "automata-primary-survival"}
    )
    comparison_birth = document.select_one(
        {"type": MultiChoice, "name": "automata-comparison-birth"}
    )
    comparison_survival = document.select_one(
        {"type": MultiChoice, "name": "automata-comparison-survival"}
    )
    step = next(
        button for button in document.select({"type": Button}) if button.label == "Single step"
    )
    clear = next(
        button for button in document.select({"type": Button}) if button.label == "Clear field"
    )

    rule.value = "Custom rule"
    primary_birth.value = ["1"]
    primary_survival.value = []
    assert primary_birth.visible
    assert primary_survival.visible
    assert "B1/S" in rule_note.text

    clear._trigger_event(ButtonClick(clear))
    field_plot._trigger_event(Tap(field_plot, sx=0, sy=0, x=64, y=40))
    step._trigger_event(ButtonClick(step))
    assert history.data["population"][-1] == 8

    experiment.value = "Compare rules"
    comparison_rule.value = "Custom rule"
    comparison_birth.value = ["2"]
    comparison_survival.value = []
    assert comparison_birth.visible
    assert comparison_survival.visible
    assert "B · B2/S" in rule_note.text

    clear._trigger_event(ButtonClick(clear))
    field_plot._trigger_event(Tap(field_plot, sx=0, sy=0, x=64, y=40))
    step._trigger_event(ButtonClick(step))
    assert history.data["population"][-1] == 8
    assert history.data["comparison_population"][-1] == 0
    assert history.data["divergence"][-1] == 8


def test_cellular_automata_classifies_extinction_still_life_and_period() -> None:
    document = Document()
    load_applications()["/cellular-automata"](document)
    seed = next(
        select for select in document.select({"type": Select}) if select.title == "Seed pattern"
    )
    step = next(
        button for button in document.select({"type": Button}) if button.label == "Single step"
    )
    clear = next(
        button for button in document.select({"type": Button}) if button.label == "Clear field"
    )
    field_plot = document.select_one({"name": "automata-field-plot"})
    status = document.select_one({"type": Div, "name": "automata-status"})

    clear._trigger_event(ButtonClick(clear))
    assert "CLASSIFICATION" in status.text
    assert "Extinct" in status.text

    for x, y in ((60, 40), (61, 40), (60, 41), (61, 41)):
        field_plot._trigger_event(Tap(field_plot, sx=0, sy=0, x=x, y=y))
    step._trigger_event(ButtonClick(step))
    assert "Still life" in status.text

    seed.value = "Pulsar constellation"
    for _ in range(3):
        step._trigger_event(ButtonClick(step))

    assert "Oscillator · period 3" in status.text
    for _ in range(9):
        step._trigger_event(ButtonClick(step))
    assert "Oscillator · period 3" in status.text
