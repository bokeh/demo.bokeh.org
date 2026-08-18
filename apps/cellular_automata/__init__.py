"""Build the cellular automata comparison demo."""

from __future__ import annotations

from typing import cast

import numpy as np
from bokeh.events import Event, Tap
from bokeh.layouts import column
from bokeh.models import (
    Button,
    ColumnDataSource,
    Div,
    GlyphRenderer,
    Image,
    Legend,
    LegendItem,
    LinearColorMapper,
    MultiChoice,
    Range1d,
    Select,
    Slider,
    Title,
)
from bokeh.plotting import figure

from apps._common import (
    match_background,
    monitor_document,
    prepare_document,
    responsive_row,
    style_figure,
    wrap_row,
)
from apps._common.colors import CORAL, GOLD, GRID, INK, MUTED, PAPER, TEAL, WARM
from apps.cellular_automata.model import (
    BRUSHES,
    COLUMNS,
    CUSTOM_RULE,
    CYCLE_MEMORY,
    NEIGHBOR_COUNTS,
    PRESET_DESCRIPTIONS,
    ROWS,
    RULES,
    Rule,
    SimulationState,
    custom_rule,
    cycle_label,
    evolve,
    orient_pattern,
    remember_state,
    seed_field,
    stamp,
    state_key,
)

HISTORY_WINDOW = 250
BACKGROUND = "#21141e"
SPEEDS = {"Slow · 2 steps/s": 5, "Medium · 5 steps/s": 2, "Fast · 10 steps/s": 1}
AGE_PALETTE = (
    BACKGROUND,
    "#d95b43",
    "#e07447",
    "#db913f",
    "#cda449",
    "#a29d5b",
    "#6f907e",
    "#4f7b7c",
    "#67918f",
    "#86a49d",
    "#b1beb1",
    "#e1d9ca",
)
COMPARISON_A = "#9b493a"
COMPARISON_B = "#3d6061"
COMPARISON_SHARED = "#f0e7d8"
COMPARISON_PALETTE = (BACKGROUND, COMPARISON_A, COMPARISON_B, COMPARISON_SHARED)


def modify_document(document) -> None:
    performance = monitor_document(document, "/cellular-automata")
    experiment = Select(
        title="Experiment", value="Single rule", options=["Single rule", "Compare rules"]
    )
    rule = Select(title="Rule set", value="Conway's Life", options=[*RULES, CUSTOM_RULE])
    primary_birth = MultiChoice(
        title="Birth counts",
        value=["3"],
        options=list(NEIGHBOR_COUNTS),
        visible=False,
        name="automata-primary-birth",
    )
    primary_survival = MultiChoice(
        title="Survival counts",
        value=["2", "3"],
        options=list(NEIGHBOR_COUNTS),
        visible=False,
        name="automata-primary-survival",
    )
    comparison_rule = Select(
        title="Rule B", value="HighLife", options=[*RULES, CUSTOM_RULE], visible=False
    )
    comparison_birth = MultiChoice(
        title="Rule B birth counts",
        value=["3", "6"],
        options=list(NEIGHBOR_COUNTS),
        visible=False,
        name="automata-comparison-birth",
    )
    comparison_survival = MultiChoice(
        title="Rule B survival counts",
        value=["2", "3"],
        options=list(NEIGHBOR_COUNTS),
        visible=False,
        name="automata-comparison-survival",
    )
    seed = Select(
        title="Seed pattern", value="Gosper glider gun", options=list(PRESET_DESCRIPTIONS)
    )
    density = Slider(
        title="Random density", start=0.05, end=0.5, value=0.22, step=0.01, visible=False
    )
    brush = Select(title="Drawing tool", value="Toggle one cell", options=list(BRUSHES))
    rotate_pattern = Button(label="Rotation · 0°", visible=False)
    flip_pattern = Button(label="Mirror · off", visible=False)
    speed = Select(title="Evolution speed", value="Medium · 5 steps/s", options=list(SPEEDS))
    playing = Button(label="Pause evolution", button_type="primary")
    step = Button(label="Single step")
    restart = Button(label="Restart pattern")
    clear = Button(label="Clear field")
    wrap_edges = Button(label="Edges wrap · on")
    rule_note = Div(name="automata-rule-note")
    seed_note = Div(name="automata-seed-note")
    brush_note = Div(name="automata-brush-note")
    status = Div(name="automata-status")
    field_note = Div(name="automata-field-note")
    classification_note = Div(
        text=(
            f'<p style="margin-top:0;color:{MUTED}">Exact states are checked automatically across the latest '
            f"{CYCLE_MEMORY} generations.</p>"
        )
    )

    image_source = ColumnDataSource(
        data={"image": [np.zeros((ROWS, COLUMNS), dtype=np.uint16)]}, name="automata-field"
    )
    history_source = ColumnDataSource(
        data={
            "generation": [],
            "population": [],
            "comparison_population": [],
            "divergence": [],
            "births": [],
            "deaths": [],
        },
        name="automata-history",
    )
    empty_field = np.zeros((ROWS, COLUMNS), dtype=bool)
    state = SimulationState(
        rng=np.random.default_rng(20260808),
        field=empty_field.copy(),
        age=np.zeros_like(empty_field, dtype=np.uint16),
        comparison_field=empty_field.copy(),
        comparison_age=np.zeros_like(empty_field, dtype=np.uint16),
    )

    field_title = Title(text="Colony field")
    field_plot = figure(
        title=field_title,
        height=570,
        sizing_mode="stretch_width",
        x_range=Range1d(start=0, end=COLUMNS),
        y_range=Range1d(start=0, end=ROWS),
        toolbar_location=None,
        tools="",
        match_aspect=True,
        name="automata-field-plot",
    )
    age_mapper = LinearColorMapper(
        palette=list(AGE_PALETTE),
        low=0,
        high=len(AGE_PALETTE),
        high_color=AGE_PALETTE[-1],
        name="automata-age-mapper",
    )
    age_image = Image(image="image", x=0, y=0, dw=COLUMNS, dh=ROWS, color_mapper=age_mapper)
    field_plot.add_glyph(image_source, age_image, name="automata-age-image")
    grid_xs = [[x, x] for x in range(COLUMNS + 1)] + [[0, COLUMNS] for _ in range(ROWS + 1)]
    grid_ys = [[0, ROWS] for _ in range(COLUMNS + 1)] + [[y, y] for y in range(ROWS + 1)]
    field_plot.multi_line(
        xs=grid_xs,
        ys=grid_ys,
        line_color="#8b7181",
        line_alpha=0.13,
        line_width=0.55,
        name="automata-cell-grid",
    )
    field_plot.axis.visible = False
    field_plot.grid.visible = False
    field_plot.background_fill_color = BACKGROUND
    field_plot.border_fill_color = PAPER
    field_plot.outline_line_color = "#5e4957"
    field_plot.outline_line_width = 2
    field_plot.min_border = 8
    field_title.text_color = INK

    history_range = Range1d(start=0, end=30)
    history_title = Title(text="Population and cell turnover")
    history = figure(
        title=history_title,
        height=235,
        sizing_mode="stretch_width",
        x_range=history_range,
        toolbar_location=None,
        tools="",
        name="automata-history-plot",
    )
    history.varea(
        x="generation",
        y1=0,
        y2="population",
        source=history_source,
        fill_color=TEAL,
        fill_alpha=0.12,
    )
    population_line = history.line(
        "generation", "population", source=history_source, color=TEAL, line_width=2.5
    )
    births_line = history.step(
        "generation",
        "births",
        source=history_source,
        color=CORAL,
        line_width=1.8,
        mode="after",
        name="automata-births-step",
    )
    deaths_line = history.step(
        "generation",
        "deaths",
        source=history_source,
        color=GOLD,
        line_width=1.8,
        mode="after",
        name="automata-deaths-step",
    )
    comparison_population_line = history.line(
        "generation",
        "comparison_population",
        source=history_source,
        color=GOLD,
        line_width=2.5,
        visible=False,
        name="automata-comparison-population",
    )
    divergence_line = history.step(
        "generation",
        "divergence",
        source=history_source,
        color=CORAL,
        line_width=2.0,
        mode="after",
        visible=False,
        name="automata-divergence-step",
    )
    single_legend = Legend(
        location="top_left",
        orientation="horizontal",
        click_policy="mute",
        background_fill_alpha=0.78,
        name="automata-single-legend",
    )
    single_legend.items = [
        LegendItem(label="Population", renderers=[cast(GlyphRenderer, population_line)]),
        LegendItem(label="Births", renderers=[cast(GlyphRenderer, births_line)]),
        LegendItem(label="Deaths", renderers=[cast(GlyphRenderer, deaths_line)]),
    ]
    comparison_legend = Legend(
        location="top_left",
        orientation="horizontal",
        click_policy="mute",
        background_fill_alpha=0.78,
        visible=False,
        name="automata-comparison-legend",
    )
    comparison_legend.items = [
        LegendItem(label="Rule A", renderers=[cast(GlyphRenderer, population_line)]),
        LegendItem(label="Rule B", renderers=[cast(GlyphRenderer, comparison_population_line)]),
        LegendItem(label="Different cells", renderers=[cast(GlyphRenderer, divergence_line)]),
    ]
    history.add_layout(single_legend)
    history.add_layout(comparison_legend)
    history.xaxis.axis_label = "Generation"
    history.yaxis.axis_label = "Cells"
    style_figure(history)

    def comparing() -> bool:
        return experiment.value == "Compare rules"

    def configured_rule(selector: Select, birth: MultiChoice, survival: MultiChoice) -> Rule:
        if selector.value != CUSTOM_RULE:
            return RULES[selector.value]
        birth_counts = tuple(sorted(int(count) for count in birth.value))
        survival_counts = tuple(sorted(int(count) for count in survival.value))
        return custom_rule(birth_counts, survival_counts)

    def update_rule_builder_visibility() -> None:
        primary_custom = rule.value == CUSTOM_RULE
        comparison_custom = comparing() and comparison_rule.value == CUSTOM_RULE
        primary_birth.visible = primary_custom
        primary_survival.visible = primary_custom
        comparison_birth.visible = comparison_custom
        comparison_survival.visible = comparison_custom

    def update_notes() -> None:
        primary = configured_rule(rule, primary_birth, primary_survival)
        if comparing():
            secondary = configured_rule(comparison_rule, comparison_birth, comparison_survival)
            rule_note.text = (
                f'<p><strong style="color:{CORAL}">A · {primary.notation}</strong> {primary.description}</p>'
                f'<p style="margin-top:8px"><strong style="color:{TEAL}">B · {secondary.notation}</strong> '
                f"{secondary.description}</p>"
            )
        else:
            rule_note.text = (
                f"<p><strong>{primary.notation}</strong><br>"
                f'<span style="color:{MUTED}">{primary.description}</span></p>'
            )
        seed_note.text = (
            f"<p><strong>{seed.value}</strong><br>"
            f'<span style="color:{MUTED}">{PRESET_DESCRIPTIONS[seed.value]}</span></p>'
        )

    def update_brush_note() -> None:
        pattern = BRUSHES[brush.value]
        if pattern is None:
            brush_note.text = "<p>Tap any cell to toggle it in the current starting state.</p>"
        else:
            brush_note.text = (
                f"<p>Tap the field to stamp a <strong>{brush.value.lower()}</strong>. "
                "The same pattern is added to both fields during comparison.</p>"
            )

    def reset_cycle_tracking() -> None:
        state.primary_seen.clear()
        state.comparison_seen.clear()
        state.primary_seen[state_key(state.field)] = state.generation
        state.comparison_seen[state_key(state.comparison_field)] = state.generation
        state.primary_cycle = cycle_label(state.field, None)
        state.comparison_cycle = cycle_label(state.comparison_field, None)

    def update_status() -> None:
        population = int(state.field.sum())
        comparison_population = int(state.comparison_field.sum())
        divergence = int(np.count_nonzero(state.field != state.comparison_field))
        if comparing():
            population_label = "A / B CELLS"
            population_value = f"{population:,} / {comparison_population:,}"
            activity_label = "DIFFERENT CELLS"
            activity_value = f"{divergence:,}"
            cycle_value = f"A: {state.primary_cycle}<br>B: {state.comparison_cycle}"
        else:
            population_label = "LIVING CELLS"
            population_value = f"{population:,}"
            activity_label = "BIRTHS / DEATHS"
            activity_value = f"{state.births:,} / {state.deaths:,}"
            cycle_value = state.primary_cycle
        status.text = (
            '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;'
            f'background:{GRID};border:1px solid {GRID}">'
            f'<div style="background:{PAPER};padding:10px"><small style="color:{MUTED}">GENERATION</small>'
            f'<strong style="display:block;font:24px Georgia,serif">{state.generation:,}</strong></div>'
            f'<div style="background:{PAPER};padding:10px"><small style="color:{MUTED}">{population_label}</small>'
            f'<strong style="display:block;font:22px Georgia,serif">{population_value}</strong></div>'
            f'<div style="background:{PAPER};padding:10px"><small style="color:{MUTED}">{activity_label}</small>'
            f'<strong style="display:block;font:20px Georgia,serif">{activity_value}</strong></div>'
            f'<div style="background:{PAPER};padding:10px"><small style="color:{MUTED}">CLASSIFICATION</small>'
            f'<strong style="display:block;font:16px/1.3 Georgia,serif">{cycle_value}</strong></div>'
            "</div>"
        )

    def render() -> None:
        if comparing():
            comparison_image = np.zeros((ROWS, COLUMNS), dtype=np.uint8)
            comparison_image[state.field & ~state.comparison_field] = 1
            comparison_image[~state.field & state.comparison_field] = 2
            comparison_image[state.field & state.comparison_field] = 3
            image_source.patch({"image": [(0, comparison_image)]})
        else:
            image_source.patch({"image": [(0, state.age)]})
        update_status()

    def reset_history() -> None:
        generation = state.generation
        population = int(state.field.sum())
        comparison_population = int(state.comparison_field.sum())
        history_source.data = {
            "generation": [generation],
            "population": [population],
            "comparison_population": [comparison_population],
            "divergence": [int(np.count_nonzero(state.field != state.comparison_field))],
            "births": [0],
            "deaths": [0],
        }
        history_range.end = max(30, generation + 1)
        history_range.start = max(0, history_range.end - 30)

    def load_seed() -> None:
        field = seed_field(seed.value, density.value, state.rng)
        state.field = field
        state.age = field.astype(np.uint16)
        state.comparison_field = field.copy()
        state.comparison_age = state.age.copy()
        state.generation = 0
        state.births = 0
        state.deaths = 0
        state.comparison_births = 0
        state.comparison_deaths = 0
        state.ticks = 0
        density.visible = seed.value == "Random soup"
        update_notes()
        reset_cycle_tracking()
        reset_history()
        render()

    def advance(*, force: bool = False) -> None:
        if not state.running and not force:
            return
        if not force:
            state.ticks += 1
            if state.ticks < SPEEDS[speed.value]:
                return
            state.ticks = 0

        state.field, state.age, state.births, state.deaths = evolve(
            state.field,
            state.age,
            configured_rule(rule, primary_birth, primary_survival),
            wrap=state.wrap,
        )
        if comparing():
            (
                state.comparison_field,
                state.comparison_age,
                state.comparison_births,
                state.comparison_deaths,
            ) = evolve(
                state.comparison_field,
                state.comparison_age,
                configured_rule(comparison_rule, comparison_birth, comparison_survival),
                wrap=state.wrap,
            )
        else:
            state.comparison_field = state.field.copy()
            state.comparison_age = state.age.copy()
            state.comparison_births = state.births
            state.comparison_deaths = state.deaths
        state.generation += 1
        primary_period = remember_state(state.field, state.generation, state.primary_seen)
        comparison_period = remember_state(
            state.comparison_field, state.generation, state.comparison_seen
        )
        state.primary_cycle = cycle_label(state.field, primary_period)
        state.comparison_cycle = cycle_label(state.comparison_field, comparison_period)
        history_source.stream(
            {
                "generation": [state.generation],
                "population": [int(state.field.sum())],
                "comparison_population": [int(state.comparison_field.sum())],
                "divergence": [int(np.count_nonzero(state.field != state.comparison_field))],
                "births": [state.births],
                "deaths": [state.deaths],
            },
            rollover=HISTORY_WINDOW,
        )
        history_range.end = max(30, state.generation + 1)
        history_range.start = max(0, history_range.end - HISTORY_WINDOW)
        render()
        if not state.field.any() and (not comparing() or not state.comparison_field.any()):
            state.running = False
            playing.label = "Resume evolution"
            playing.button_type = "default"

    def update_latest_history() -> None:
        last = len(history_source.data["generation"]) - 1
        history_source.patch(
            {
                "population": [(last, int(state.field.sum()))],
                "comparison_population": [(last, int(state.comparison_field.sum()))],
                "divergence": [
                    (last, int(np.count_nonzero(state.field != state.comparison_field)))
                ],
                "births": [(last, 0)],
                "deaths": [(last, 0)],
            }
        )

    def edit_field(event: Event) -> None:
        if not isinstance(event, Tap) or event.x is None or event.y is None:
            return
        column_index = int(event.x)
        row_index = int(event.y)
        if not (0 <= row_index < ROWS and 0 <= column_index < COLUMNS):
            return
        pattern = BRUSHES[brush.value]
        primary_field = state.field.copy()
        comparison_field = state.comparison_field.copy()
        if pattern is None:
            alive = ~primary_field[row_index, column_index]
            primary_field[row_index, column_index] = alive
            comparison_field[row_index, column_index] = alive
        else:
            oriented = orient_pattern(pattern, state.brush_rotation, state.brush_flipped)
            pattern_width = max(x for x, _ in oriented) + 1
            pattern_height = max(y for _, y in oriented) + 1
            anchor_x = column_index - pattern_width // 2
            anchor_y = row_index - pattern_height // 2
            stamp(primary_field, oriented, anchor_x, anchor_y)
            stamp(comparison_field, oriented, anchor_x, anchor_y)

        primary_age = state.age.copy()
        comparison_age = state.comparison_age.copy()
        primary_age[~primary_field] = 0
        comparison_age[~comparison_field] = 0
        primary_age[primary_field & (primary_age == 0)] = 1
        comparison_age[comparison_field & (comparison_age == 0)] = 1
        state.field = primary_field
        state.age = primary_age
        state.comparison_field = comparison_field
        state.comparison_age = comparison_age
        state.births = 0
        state.deaths = 0
        state.comparison_births = 0
        state.comparison_deaths = 0
        reset_cycle_tracking()
        update_latest_history()
        render()

    def clear_field() -> None:
        state.running = False
        playing.label = "Resume evolution"
        playing.button_type = "default"
        field = np.zeros((ROWS, COLUMNS), dtype=bool)
        state.field = field
        state.age = np.zeros_like(field, dtype=np.uint16)
        state.comparison_field = field.copy()
        state.comparison_age = np.zeros_like(field, dtype=np.uint16)
        state.generation = 0
        state.births = 0
        state.deaths = 0
        state.comparison_births = 0
        state.comparison_deaths = 0
        state.ticks = 0
        reset_cycle_tracking()
        reset_history()
        render()

    def seed_changed(_attr: str, _old: object, _new: object) -> None:
        load_seed()

    def rule_changed(_attr: str, _old: object, _new: object) -> None:
        update_rule_builder_visibility()
        reset_cycle_tracking()
        update_notes()
        update_status()

    def comparison_rule_changed(_attr: str, _old: object, _new: object) -> None:
        update_rule_builder_visibility()
        state.comparison_seen.clear()
        state.comparison_seen[state_key(state.comparison_field)] = state.generation
        state.comparison_cycle = cycle_label(state.comparison_field, None)
        update_notes()
        update_status()

    def primary_custom_rule_changed(_attr: str, _old: object, _new: object) -> None:
        if rule.value == CUSTOM_RULE:
            reset_cycle_tracking()
            update_notes()
            update_status()

    def comparison_custom_rule_changed(_attr: str, _old: object, _new: object) -> None:
        if comparing() and comparison_rule.value == CUSTOM_RULE:
            state.comparison_seen.clear()
            state.comparison_seen[state_key(state.comparison_field)] = state.generation
            state.comparison_cycle = cycle_label(state.comparison_field, None)
            update_notes()
            update_status()

    def density_changed(_attr: str, _old: object, _new: object) -> None:
        if seed.value == "Random soup":
            load_seed()

    def set_running(running: bool) -> None:
        state.running = running
        playing.label = "Pause evolution" if running else "Resume evolution"
        playing.button_type = "primary" if running else "default"

    def toggle_playing() -> None:
        set_running(not state.running)

    def toggle_wrap() -> None:
        state.wrap = not state.wrap
        wrap_edges.label = f"Edges wrap · {'on' if state.wrap else 'off'}"
        reset_cycle_tracking()
        update_status()

    def update_visual_mode() -> None:
        is_comparison = comparing()
        comparison_rule.visible = is_comparison
        rule.title = "Rule A" if is_comparison else "Rule set"
        primary_birth.title = "Rule A birth counts" if is_comparison else "Birth counts"
        primary_survival.title = "Rule A survival counts" if is_comparison else "Survival counts"
        update_rule_builder_visibility()
        age_mapper.palette = list(COMPARISON_PALETTE if is_comparison else AGE_PALETTE)
        age_mapper.high = len(COMPARISON_PALETTE if is_comparison else AGE_PALETTE)
        age_mapper.high_color = COMPARISON_PALETTE[-1] if is_comparison else AGE_PALETTE[-1]
        births_line.visible = not is_comparison
        deaths_line.visible = not is_comparison
        comparison_population_line.visible = is_comparison
        divergence_line.visible = is_comparison
        single_legend.visible = not is_comparison
        comparison_legend.visible = is_comparison
        field_title.text = "Rule divergence" if is_comparison else "Colony field"
        history_title.text = (
            "Rule populations and divergence" if is_comparison else "Population and cell turnover"
        )
        field_note.text = (
            (
                '<div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px 20px">'
                "<strong>Comparison overlay</strong>"
                f'<span><i style="display:inline-block;width:15px;height:15px;margin-right:7px;'
                f'vertical-align:-2px;background:{COMPARISON_A};border:1px solid #6c3128"></i>Rule A only</span>'
                f'<span><i style="display:inline-block;width:15px;height:15px;margin-right:7px;'
                f'vertical-align:-2px;background:{COMPARISON_B};border:1px solid #294748"></i>Rule B only</span>'
                '<span><i style="display:inline-block;width:15px;height:15px;margin-right:7px;'
                f'vertical-align:-2px;background:{COMPARISON_SHARED};border:1px solid #746d68"></i>'
                "Shared cells · brightest</span>"
                "</div>"
            )
            if is_comparison
            else (
                "<p><strong>Cell age:</strong> new cells start coral, then age through gold and teal "
                "toward chalk.</p>"
            )
        )
        update_notes()
        render()

    def experiment_changed(_attr: str, _old: object, _new: object) -> None:
        if comparing():
            state.comparison_field = state.field.copy()
            state.comparison_age = state.age.copy()
            state.comparison_births = state.births
            state.comparison_deaths = state.deaths
            reset_cycle_tracking()
            update_latest_history()
        update_visual_mode()

    def brush_changed(_attr: str, _old: object, _new: object) -> None:
        is_pattern = BRUSHES[brush.value] is not None
        rotate_pattern.visible = is_pattern
        flip_pattern.visible = is_pattern
        if is_pattern:
            set_running(False)
        update_brush_note()

    def rotate_brush() -> None:
        state.brush_rotation = (state.brush_rotation + 1) % 4
        rotate_pattern.label = f"Rotation · {90 * state.brush_rotation}°"

    def flip_brush() -> None:
        state.brush_flipped = not state.brush_flipped
        flip_pattern.label = f"Mirror · {'on' if state.brush_flipped else 'off'}"

    experiment.on_change("value", performance.measure(experiment_changed))
    seed.on_change("value", performance.measure(seed_changed))
    rule.on_change("value", performance.measure(rule_changed))
    comparison_rule.on_change("value", performance.measure(comparison_rule_changed))
    primary_birth.on_change("value", performance.measure(primary_custom_rule_changed))
    primary_survival.on_change("value", performance.measure(primary_custom_rule_changed))
    comparison_birth.on_change("value", performance.measure(comparison_custom_rule_changed))
    comparison_survival.on_change("value", performance.measure(comparison_custom_rule_changed))
    brush.on_change("value", performance.measure(brush_changed))
    density.on_change("value_throttled", performance.measure(density_changed))
    playing.on_click(performance.measure(toggle_playing))
    wrap_edges.on_click(performance.measure(toggle_wrap))
    rotate_pattern.on_click(performance.measure(rotate_brush))
    flip_pattern.on_click(performance.measure(flip_brush))
    restart.on_click(performance.measure(load_seed))
    step.on_click(performance.measure(lambda: advance(force=True), name="step_once"))
    clear.on_click(performance.measure(clear_field))
    field_plot.on_event(Tap, performance.measure(edit_field))

    update_notes()
    update_brush_note()
    load_seed()
    update_visual_mode()
    document.add_periodic_callback(performance.measure(advance), 100)

    controls = column(
        Div(
            text=(
                "<h2>Run one rule or compare two</h2>"
                "<p>Start from the same cells, then watch different local rules agree, diverge, settle, or repeat.</p>"
            )
        ),
        status,
        classification_note,
        experiment,
        rule,
        primary_birth,
        primary_survival,
        comparison_rule,
        comparison_birth,
        comparison_survival,
        rule_note,
        speed,
        wrap_edges,
        wrap_row(playing, step),
        wrap_row(restart, clear),
        width=340,
        styles={"background": WARM, "padding": "20px", "border": f"1px solid {GRID}"},
    )
    match_background(controls, WARM)

    brush_panel = column(
        Div(
            text=(
                "<h3>Seed and edit the field</h3>"
                "<p>Load a known pattern or use the field as a canvas. Pattern tools pause evolution while you stamp.</p>"
            )
        ),
        wrap_row(seed, density, brush, sizing_mode="stretch_width"),
        wrap_row(rotate_pattern, flip_pattern, sizing_mode="stretch_width"),
        seed_note,
        brush_note,
        sizing_mode="stretch_width",
        styles={"background": WARM, "padding": "14px 16px", "border": f"1px solid {GRID}"},
    )
    match_background(brush_panel, WARM)

    runtime_note = Div(
        text=(
            "<p><strong>Computation:</strong> every generation, comparison, pattern edit, and cycle check runs "
            "in the Python session served through ASGI.</p>"
        )
    )
    field_stack = column(
        brush_panel, field_note, field_plot, history, sizing_mode="stretch_width", spacing=14
    )
    document.add_root(
        column(
            responsive_row(controls, field_stack, sizing_mode="stretch_width"),
            runtime_note,
            sizing_mode="stretch_width",
            spacing=18,
        )
    )
    prepare_document(document, "/cellular-automata")
