"""Simulate nonlinear oscillators and inspect their phase-space behavior."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from bokeh.layouts import column
from bokeh.models import (
    BasicTicker,
    Button,
    ColumnDataSource,
    CustomJSTickFormatter,
    Div,
    Range1d,
    Slider,
    TabPanel,
    Tabs,
    Title,
    Toggle,
)
from bokeh.plotting import figure
from scipy.integrate import solve_ivp

from apps._common import (
    PeriodicCoalescer,
    match_background,
    monitor_document,
    prepare_document,
    responsive_row,
    style_figure,
    wrap_row,
)
from apps._common.colors import CORAL, GOLD, PAPER, PLUM, TEAL, VIOLET

Acceleration = Callable[[float, float, float], float]
STATE_BACKGROUND = "#e5ddd4"
STATE_GRID = "#2a1723"

NARROW_CONTENT_CSS = """
@media (max-width: 700px) {
  :host {
    min-width: 0 !important;
    width: 100% !important;
  }
}
"""


def modify_document(document) -> None:
    performance = monitor_document(document, "/chaotic-motion")
    advances: list[Callable[[int], None]] = []
    coalescer = PeriodicCoalescer(0.1)

    def build_oscillator(
        *,
        key: str,
        tab_title: str,
        heading: str,
        equation: str,
        position_symbol: str,
        description: str,
        controls: tuple[Slider, ...],
        acceleration: Acceleration,
        initial_position: float,
        initial_velocity: float,
        phase_x_range: tuple[float, float],
        phase_y_range: tuple[float, float],
        trace_color: str,
        phase_color: str,
        diagnostic_color: str,
        diagnostic: str,
        forcing_frequency: Slider | None = None,
        fixed_step: float = 0.025,
    ) -> TabPanel:
        state = {
            "n": 0,
            "t": 0.0,
            "x": initial_position,
            "velocity": initial_velocity,
            "previous_velocity": initial_velocity,
            "sample": 0,
            "updates": 0,
        }
        steps_per_period = 120
        steps_per_update = 40
        trace_history_limit = 1800
        phase_history_limit = 3600
        phase_focus_limit = 1800
        phase_position_scale = np.pi if key == "pendulum" else 1.0
        initial_phase_position = initial_position / phase_position_scale
        display_phase_x_range = (
            phase_x_range[0] / phase_position_scale,
            phase_x_range[1] / phase_position_scale,
        )

        running = Toggle(label="Pause integration", active=True, button_type="primary")
        reset = Button(label="Reset initial state")

        trace_source = ColumnDataSource(
            data={"time": [0.0], "cycles": [0.0], "x": [initial_position]}, name=f"{key}-trace"
        )
        phase_source = ColumnDataSource(
            data={"x": [initial_phase_position], "velocity": [initial_velocity]},
            name=f"{key}-phase",
        )
        phase_focus_source = ColumnDataSource(
            data={"x": [initial_phase_position], "velocity": [initial_velocity]},
            name=f"{key}-phase-focus",
        )
        sample_source = ColumnDataSource(
            data={"index": [], "x": [], "velocity": []}, name=f"{key}-diagnostic"
        )
        status = Div(text="")

        trace = figure(
            height=260, sizing_mode="stretch_width", toolbar_location=None, name=f"{key}-trace-plot"
        )
        trace_x = "cycles" if forcing_frequency is not None else "time"
        trace.line(trace_x, "x", source=trace_source, color=trace_color, line_width=2)
        trace.xaxis.axis_label = r"$$t/T$$" if forcing_frequency is not None else r"$$t$$"
        trace.yaxis.axis_label = f"$${position_symbol}(t)$$"
        style_figure(trace)

        phase_name = "chaotic-phase-plot" if key == "duffing" else f"{key}-phase-plot"
        path_name = "chaotic-phase-path" if key == "duffing" else f"{key}-phase-path"
        phase_x_model = Range1d(start=display_phase_x_range[0], end=display_phase_x_range[1])
        phase_y_model = Range1d(start=phase_y_range[0], end=phase_y_range[1])
        phase_title = Title(text="Phase path", text_font_size="16px")
        phase = figure(
            title=phase_title,
            height=410,
            sizing_mode="stretch_width",
            x_range=phase_x_model,
            y_range=phase_y_model,
            tools="",
            toolbar_location=None,
            name=phase_name,
        )
        phase.line(
            "x",
            "velocity",
            source=phase_source,
            color=phase_color,
            line_width=0.7,
            line_alpha=0.14,
            name=f"{key}-phase-history",
        )
        phase.line(
            "x",
            "velocity",
            source=phase_focus_source,
            color=phase_color,
            line_width=0.8,
            line_alpha=0.48,
            name=path_name,
        )
        phase.xaxis.axis_label = f"$${position_symbol}$$"
        phase.yaxis.axis_label = rf"$$\dot{{{position_symbol}}}$$"
        style_figure(phase)
        phase.background_fill_color = STATE_BACKGROUND
        phase.grid.grid_line_color = STATE_GRID
        phase.grid.grid_line_alpha = 0.12
        phase.grid.grid_line_width = 0.5

        def reset_phase_range() -> None:
            phase_x_model.start, phase_x_model.end = display_phase_x_range
            phase_y_model.start, phase_y_model.end = phase_y_range

        def expand_phase_range() -> None:
            def expand(
                values: Any, axis_range: Range1d, initial_range: tuple[float, float]
            ) -> None:
                finite = np.asarray(values, dtype=float)
                finite = finite[np.isfinite(finite)]
                if finite.size == 0:
                    return
                low = float(np.min(finite))
                high = float(np.max(finite))
                start = axis_range.start
                end = axis_range.end
                assert isinstance(start, (int, float))
                assert isinstance(end, (int, float))
                current_span = end - start
                data_span = max(high - low, current_span * 0.25)
                edge_margin = current_span * 0.06
                padding = max(data_span * 0.08, (initial_range[1] - initial_range[0]) * 0.04)
                if low < start + edge_margin:
                    axis_range.start = min(start, low - padding)
                if high > end - edge_margin:
                    axis_range.end = max(end, high + padding)

            expand(phase_source.data["x"], phase_x_model, display_phase_x_range)
            expand(phase_source.data["velocity"], phase_y_model, phase_y_range)

        diagnostic_title = "Peak convergence" if diagnostic == "peaks" else "Stroboscopic section"
        diagnostic_title_model = Title(text=diagnostic_title, text_font_size="16px")
        diagnostic_plot = figure(
            title=diagnostic_title_model,
            height=410,
            sizing_mode="stretch_width",
            tools="",
            toolbar_location=None,
            name=f"{key}-diagnostic-plot",
        )
        sample_style = {
            "fill_color": diagnostic_color,
            "fill_alpha": 0.78,
            "line_color": diagnostic_color,
            "line_alpha": 0.9,
            "line_width": 1,
        }
        if diagnostic == "peaks":
            diagnostic_plot.min_border_left = 65
            diagnostic_plot.line(
                "index", "x", source=sample_source, color=diagnostic_color, line_width=2
            )
            diagnostic_plot.scatter(
                "index",
                "x",
                source=sample_source,
                size=6,
                name=f"{key}-diagnostic-samples",
                **sample_style,
            )
            diagnostic_plot.xaxis.axis_label = "Peak number"
            diagnostic_plot.yaxis.axis_label = f"$${position_symbol}_{{max}}$$"
        else:
            diagnostic_plot.scatter(
                "x",
                "velocity",
                source=sample_source,
                size=7,
                name=f"{key}-diagnostic-samples",
                **sample_style,
            )
            diagnostic_plot.x_range = phase_x_model
            diagnostic_plot.y_range = phase_y_model
            diagnostic_plot.xaxis.axis_label = f"$${position_symbol}(nT)$$"
            diagnostic_plot.yaxis.axis_label = rf"$$\dot{{{position_symbol}}}(nT)$$"
        style_figure(diagnostic_plot)
        diagnostic_plot.background_fill_color = STATE_BACKGROUND
        diagnostic_plot.grid.grid_line_color = STATE_GRID
        diagnostic_plot.grid.grid_line_alpha = 0.12
        diagnostic_plot.grid.grid_line_width = 0.5
        if key == "pendulum":
            ticker = BasicTicker(desired_num_ticks=7, min_interval=1)
            formatter = CustomJSTickFormatter(
                code="""
                    const multiple = Math.round(tick)
                    if (multiple == 0)
                        return "0"
                    if (multiple == 1)
                        return "π"
                    if (multiple == -1)
                        return "−π"
                    return `${multiple < 0 ? "−" : ""}${Math.abs(multiple)}π`
                """
            )
            for plot in (phase, diagnostic_plot):
                plot.xaxis.ticker = ticker
                plot.xaxis.formatter = formatter

        def restart() -> None:
            state.update(
                n=0,
                t=0.0,
                x=initial_position,
                velocity=initial_velocity,
                previous_velocity=initial_velocity,
                sample=0,
                updates=0,
            )
            trace_source.data = {"time": [0.0], "cycles": [0.0], "x": [initial_position]}
            phase_source.data = {"x": [initial_phase_position], "velocity": [initial_velocity]}
            phase_focus_source.data = {
                "x": [initial_phase_position],
                "velocity": [initial_velocity],
            }
            sample_source.data = {"index": [], "x": [], "velocity": []}
            reset_phase_range()
            status.text = "<p>Ready from the initial state.</p>"

        def advance(ticks: int = 1) -> None:
            if not running.active:
                return
            if forcing_frequency is None:
                step = fixed_step
                frequency = None
            else:
                frequency = float(forcing_frequency.value)
                step = 2 * np.pi / (frequency * steps_per_period)

            total_steps = steps_per_update * ticks
            times = state["t"] + step * np.arange(1, total_steps + 1)

            def derivatives(time: float, values_at_time: np.ndarray) -> tuple[float, float]:
                position, velocity = values_at_time
                return velocity, acceleration(time, position, velocity)

            solution = solve_ivp(
                derivatives,
                (state["t"], float(times[-1])),
                (state["x"], state["velocity"]),
                method="RK45",
                t_eval=times,
                max_step=step,
            )
            if not solution.success:
                running.active = False
                status.text = f"<p>Integration stopped: {solution.message}</p>"
                return

            positions = solution.y[0]
            velocities = solution.y[1]
            phase_positions = positions / phase_position_scale
            sample_indices: list[int] = []
            sample_positions: list[float] = []
            sample_velocities: list[float] = []

            for position, velocity in zip(positions, velocities, strict=True):
                state["n"] += 1

                if diagnostic == "peaks":
                    if state["previous_velocity"] > 0 and velocity <= 0:
                        state["sample"] += 1
                        sample_indices.append(state["sample"])
                        sample_positions.append(position / phase_position_scale)
                        sample_velocities.append(velocity)
                elif state["n"] % steps_per_period == 0:
                    state["sample"] += 1
                    sample_indices.append(state["sample"])
                    sample_positions.append(position / phase_position_scale)
                    sample_velocities.append(velocity)
                state["previous_velocity"] = velocity

            state["t"] = float(times[-1])
            state["x"] = float(positions[-1])
            state["velocity"] = float(velocities[-1])

            cycles = times * frequency / (2 * np.pi) if frequency is not None else times
            trace_source.stream(
                {
                    "time": times.astype(np.float32),
                    "cycles": cycles.astype(np.float32),
                    "x": positions.astype(np.float32),
                },
                rollover=trace_history_limit,
            )
            phase_source.stream(
                {
                    "x": phase_positions.astype(np.float32),
                    "velocity": velocities.astype(np.float32),
                },
                rollover=phase_history_limit,
            )
            phase_focus_source.stream(
                {
                    "x": phase_positions.astype(np.float32),
                    "velocity": velocities.astype(np.float32),
                },
                rollover=phase_focus_limit,
            )
            expand_phase_range()
            if sample_positions:
                sample_source.stream(
                    {
                        "index": np.asarray(sample_indices, dtype=np.int32),
                        "x": np.asarray(sample_positions, dtype=np.float32),
                        "velocity": np.asarray(sample_velocities, dtype=np.float32),
                    },
                    rollover=500,
                )
            state["updates"] += 1
            if state["updates"] % 5 == 0 or sample_positions:
                status.text = (
                    f"<p><strong>{state['n']:,}</strong> integration steps &nbsp; "
                    f"<strong>{len(sample_source.data['x'])}</strong> diagnostic samples</p>"
                )

        def parameters_changed(_attr: str, _old: object, _new: object) -> None:
            restart()

        def running_changed(_attr: str, _old: bool, active: bool) -> None:
            running.label = "Pause integration" if active else "Resume integration"

        for slider in controls:
            slider.on_change("value_throttled", performance.measure(parameters_changed))
        running.on_change("active", performance.measure(running_changed))
        reset.on_click(performance.measure(restart))
        restart()
        advance()
        advances.append(advance)

        explanation = Div(
            text=(
                f"<h2>{heading}</h2>"
                f"<p class='math-display' style='margin-bottom:18px'>$${equation}$$</p>"
                f"<p>{description}</p>"
            ),
            name=f"{key}-explanation",
            styles={"padding": "4px 8px 10px 0"},
        )
        control_panel = column(explanation, *controls, wrap_row(running, reset), status, width=340)
        content = column(
            responsive_row(control_panel, trace, sizing_mode="stretch_width"),
            responsive_row(phase, diagnostic_plot, sizing_mode="stretch_width"),
            Div(
                text=(
                    "<p><strong>Computation:</strong> SciPy's adaptive RK45 integration in Python. "
                    "Each model keeps separate state for every browser session.</p>"
                )
            ),
            sizing_mode="stretch_width",
            min_width=1080,
            stylesheets=[NARROW_CONTENT_CSS],
            spacing=18,
        )
        match_background(content, PAPER)
        return TabPanel(title=tab_title, child=content)

    duffing_damping = Slider(
        title=r"$$\delta\text{, damping}$$", start=0.05, end=0.6, value=0.25, step=0.025
    )
    duffing_forcing = Slider(
        title=r"$$\gamma\text{, forcing amplitude}$$", start=0.1, end=0.65, value=0.5, step=0.025
    )
    duffing_frequency = Slider(
        title=r"$$\omega\text{, forcing frequency}$$", start=0.5, end=2.5, value=1.35, step=0.025
    )

    def duffing_acceleration(time: float, position: float, velocity: float) -> float:
        return (
            -duffing_damping.value * velocity
            + position
            - position**3
            + duffing_forcing.value * np.cos(duffing_frequency.value * time)
        )

    van_der_pol_nonlinearity = Slider(
        title=r"$$\mu\text{, nonlinearity}$$", start=0.1, end=5.0, value=1.6, step=0.1
    )

    def van_der_pol_acceleration(_time: float, position: float, velocity: float) -> float:
        return van_der_pol_nonlinearity.value * (1 - position**2) * velocity - position

    pendulum_damping = Slider(
        title=r"$$b\text{, damping}$$", start=0.05, end=0.8, value=0.5, step=0.025
    )
    pendulum_drive = Slider(
        title=r"$$A\text{, drive amplitude}$$", start=0.0, end=2.0, value=1.2, step=0.05
    )
    pendulum_frequency = Slider(
        title=r"$$\omega\text{, drive frequency}$$", start=0.4, end=2.0, value=0.675, step=0.025
    )

    def pendulum_acceleration(time: float, position: float, velocity: float) -> float:
        return (
            -pendulum_damping.value * velocity
            - np.sin(position)
            + pendulum_drive.value * np.cos(pendulum_frequency.value * time)
        )

    mathieu_damping = Slider(
        title=r"$$\zeta\text{, damping ratio}$$", start=0.02, end=0.25, value=0.10, step=0.01
    )
    mathieu_stiffness = Slider(
        title=r"$$a\text{, baseline stiffness}$$", start=0.5, end=2.0, value=1.0, step=0.05
    )
    mathieu_modulation = Slider(
        title=r"$$q\text{, modulation depth}$$", start=0.0, end=0.26, value=0.21, step=0.01
    )
    mathieu_frequency = Slider(
        title=r"$$\omega\text{, modulation frequency}$$", start=0.8, end=3.0, value=2.0, step=0.05
    )

    def mathieu_acceleration(time: float, position: float, velocity: float) -> float:
        stiffness = mathieu_stiffness.value - 2 * mathieu_modulation.value * np.cos(
            mathieu_frequency.value * time
        )
        return -2 * mathieu_damping.value * velocity - stiffness * position

    panels = [
        build_oscillator(
            key="duffing",
            tab_title="Duffing",
            heading="Driven Duffing oscillator",
            equation=r"\ddot{x}+\delta\dot{x}-x+x^3=\gamma\cos(\omega t)",
            position_symbol="x",
            description=(
                "Competing wells and periodic forcing can produce stable loops, period doubling, "
                "or a chaotic attractor."
            ),
            controls=(duffing_damping, duffing_forcing, duffing_frequency),
            acceleration=duffing_acceleration,
            initial_position=0.0,
            initial_velocity=0.0,
            phase_x_range=(-2, 2),
            phase_y_range=(-2, 2),
            trace_color=CORAL,
            phase_color=PLUM,
            diagnostic_color=VIOLET,
            diagnostic="strobe",
            forcing_frequency=duffing_frequency,
        ),
        build_oscillator(
            key="van-der-pol",
            tab_title="Van der Pol",
            heading="Van der Pol oscillator",
            equation=r"\ddot{x}-\mu(1-x^2)\dot{x}+x=0",
            position_symbol="x",
            description=(
                "Negative damping at small amplitudes and positive damping at large amplitudes "
                "pull trajectories toward a self-sustaining limit cycle."
            ),
            controls=(van_der_pol_nonlinearity,),
            acceleration=van_der_pol_acceleration,
            initial_position=2.0,
            initial_velocity=0.0,
            phase_x_range=(-3.2, 3.2),
            phase_y_range=(-5, 5),
            trace_color=TEAL,
            phase_color=VIOLET,
            diagnostic_color=GOLD,
            diagnostic="peaks",
        ),
        build_oscillator(
            key="pendulum",
            tab_title="Driven pendulum",
            heading="Driven nonlinear pendulum",
            equation=r"\ddot{\theta}+b\dot{\theta}+\sin(\theta)=A\cos(\omega t)",
            position_symbol=r"\theta",
            description=(
                "Damping and periodic torque compete with gravity, producing libration, "
                "phase locking, rotations, and chaotic transitions."
            ),
            controls=(pendulum_damping, pendulum_drive, pendulum_frequency),
            acceleration=pendulum_acceleration,
            initial_position=0.2,
            initial_velocity=0.0,
            phase_x_range=(-4, 4),
            phase_y_range=(-4, 4),
            trace_color=GOLD,
            phase_color=PLUM,
            diagnostic_color=CORAL,
            diagnostic="strobe",
            forcing_frequency=pendulum_frequency,
        ),
        build_oscillator(
            key="mathieu",
            tab_title="Mathieu",
            heading="Damped Mathieu oscillator",
            equation=r"\ddot{x}+2\zeta\dot{x}+[a-2q\cos(\omega t)]x=0",
            position_symbol="x",
            description=(
                "Periodic stiffness modulation creates alternating stable and unstable bands, "
                "allowing small motions to decay, lock, or grow through parametric resonance."
            ),
            controls=(mathieu_damping, mathieu_stiffness, mathieu_modulation, mathieu_frequency),
            acceleration=mathieu_acceleration,
            initial_position=0.4,
            initial_velocity=0.0,
            phase_x_range=(-2, 2),
            phase_y_range=(-2, 2),
            trace_color=VIOLET,
            phase_color=TEAL,
            diagnostic_color=CORAL,
            diagnostic="strobe",
            forcing_frequency=mathieu_frequency,
        ),
    ]

    tabs = Tabs(tabs=panels, active=0, sizing_mode="stretch_width", name="oscillator-tabs")

    def advance_active() -> None:
        advances[tabs.active](coalescer.due_ticks())

    document.add_periodic_callback(performance.measure(advance_active), 100)
    document.add_root(tabs)
    prepare_document(document, "/chaotic-motion")
