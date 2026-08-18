"""Replay a synthetic market with linked price, volume, and MACD views."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import numpy as np
import pandas as pd
from bokeh.layouts import column
from bokeh.models import (
    Button,
    ColumnDataSource,
    Div,
    FixedTicker,
    HoverTool,
    Range1d,
    Select,
    Slider,
    Span,
    Toggle,
)
from bokeh.plotting import figure

from apps._common import (
    PeriodicCoalescer,
    match_background,
    metric,
    metric_row,
    monitor_document,
    prepare_document,
    responsive_row,
    set_metric,
    style_figure,
    wrap_row,
)
from apps._common.colors import CORAL, GOLD, MUTED, TEAL, VIOLET, WARM

SEED = 3102026
BAR_MINUTES = 15
BARS_PER_SESSION = 390 // BAR_MINUTES
SEED_BARS = 64
WINDOW_BARS = 64
BAR_WIDTH = 0.8
FAST_ALPHA = 2 / 13
SLOW_ALPHA = 2 / 27
SIGNAL_ALPHA = 2 / 10
UPDATE_TICKS = {"Slow": 6, "Medium": 3, "Fast": 1}
REGIMES = {
    "Steady growth": {"drift": 0.010, "reversion": 0.010, "volume": 2.8, "volatility": 0.65},
    "Range-bound": {"drift": 0.0, "reversion": 0.35, "volume": 1.8, "volatility": 0.45},
    "Stress test": {"drift": -0.004, "reversion": 0.015, "volume": 5.5, "volatility": 1.8},
}
REGIME_DESCRIPTIONS = {
    "Steady growth": "An upward drift with moderate volume and lower volatility. Price can still pull back along the way.",
    "Range-bound": "No built-in drift. Strong pull toward $100 and the lowest volatility keep price in a tighter band.",
    "Stress test": "A downward drift with weak anchoring, heavy volume, and the highest volatility.",
}


def modify_document(document) -> None:
    performance = monitor_document(document, "/market-monitor")
    coalescer = PeriodicCoalescer(0.15)
    regime = Select(title="Market regime", value="Steady growth", options=list(REGIMES))
    regime_note = Div(
        name="market-regime-note",
        styles={"color": MUTED, "font-size": "12px", "line-height": "1.5"},
    )
    volatility = Slider(title="Volatility multiplier", start=0.5, end=2.5, value=1.0, step=0.1)
    speed = Select(title="Replay pace", value="Fast", options=list(UPDATE_TICKS))
    playing = Toggle(label="Pause simulation", active=True, button_type="primary")
    selloff = Button(label="Inject an 8% selloff")
    restart = Button(label="Restart seeded run")
    price_source = ColumnDataSource(
        data={
            "index": [],
            "date": [],
            "open": [],
            "high": [],
            "low": [],
            "close": [],
            "volume": [],
            "volume_millions": [],
            "body_top": [],
            "body_bottom": [],
            "color": [],
        },
        name="market-price",
    )
    indicator_source = ColumnDataSource(
        data={
            "index": [],
            "date": [],
            "macd": [],
            "signal": [],
            "positive_macd": [],
            "positive_signal": [],
            "negative_macd": [],
            "negative_signal": [],
        },
        name="market-macd",
    )
    state: dict[str, Any] = {}
    close_card = metric("Latest close", "...", accent=CORAL)
    move_card = metric("15-minute move", "...", accent=TEAL)
    volatility_card = metric("20-bar volatility", "...", accent=GOLD)
    drawdown_card = metric("Window drawdown", "...", accent=VIOLET)
    simulation_status = Div()

    def update_regime_note() -> None:
        regime_note.text = (
            f"<p><strong>{regime.value}:</strong> {REGIME_DESCRIPTIONS[regime.value]}</p>"
            '<p style="margin-top:6px">The volatility multiplier applies on top of this regime and affects new bars only.</p>'
        )

    update_regime_note()

    bar_range = Range1d()
    bar_ticker = FixedTicker(ticks=[])
    price = figure(
        height=430,
        sizing_mode="stretch_width",
        x_range=bar_range,
        tools="xpan,xwheel_zoom,reset",
        active_scroll=None,
        name="market-price-plot",
    )
    price.segment(
        "index", "high", "index", "low", source=price_source, line_color="color", line_width=2
    )
    bodies = price.vbar(
        "index",
        width=BAR_WIDTH,
        top="body_top",
        bottom="body_bottom",
        source=price_source,
        fill_color="color",
        line_color="color",
        fill_alpha=0.84,
    )
    price.add_tools(
        HoverTool(
            renderers=[bodies],
            tooltips=[
                ("Bar", "@date{%F %H:%M}"),
                ("Open", "$@open{0.00}"),
                ("High", "$@high{0.00}"),
                ("Low", "$@low{0.00}"),
                ("Close", "$@close{0.00}"),
                ("Volume", "@volume{0,0}"),
            ],
            formatters={"@date": "datetime"},
            mode="vline",
        )
    )
    price.yaxis.axis_label = "Simulated price (USD)"
    price.xaxis.ticker = bar_ticker
    style_figure(price)

    volume = figure(
        title="Volume (millions)",
        height=180,
        sizing_mode="stretch_width",
        x_range=bar_range,
        tools="",
        toolbar_location=None,
        name="market-volume-plot",
    )
    volume.vbar(
        "index",
        width=BAR_WIDTH,
        top="volume_millions",
        source=price_source,
        fill_color="color",
        line_color=None,
        fill_alpha=0.68,
    )
    volume.xaxis.ticker = bar_ticker
    style_figure(volume)

    macd = figure(
        height=225,
        sizing_mode="stretch_width",
        x_range=bar_range,
        tools="",
        toolbar_location=None,
        title="Momentum · MACD (12, 26, 9)",
        name="market-macd-plot",
    )
    macd.varea(
        "index",
        "positive_signal",
        "positive_macd",
        source=indicator_source,
        fill_color=TEAL,
        fill_alpha=0.14,
        name="market-macd-positive",
    )
    macd.varea(
        "index",
        "negative_signal",
        "negative_macd",
        source=indicator_source,
        fill_color=CORAL,
        fill_alpha=0.14,
        name="market-macd-negative",
    )
    macd.line(
        "index", "macd", source=indicator_source, color=CORAL, line_width=2.5, legend_label="MACD"
    )
    macd.line(
        "index",
        "signal",
        source=indicator_source,
        color=TEAL,
        line_width=2.5,
        legend_label="Signal",
    )
    macd.add_layout(
        Span(location=0, dimension="width", line_color="#a89fa3", line_dash="dashed", line_width=1)
    )
    macd.yaxis.axis_label = "Price difference (USD)"
    macd.xaxis.ticker = bar_ticker
    macd.legend.location = "top_left"
    macd.legend.orientation = "horizontal"
    macd.legend.click_policy = "mute"
    style_figure(macd)

    def next_bar_time(current: pd.Timestamp) -> pd.Timestamp:
        candidate = cast(pd.Timestamp, current + timedelta(minutes=BAR_MINUTES))
        normalized = cast(pd.Timestamp, current.normalize())
        session_close = cast(pd.Timestamp, normalized + timedelta(hours=16))
        if candidate < session_close:
            return candidate
        return cast(pd.Timestamp, normalized + pd.offsets.BDay() + timedelta(hours=9, minutes=30))

    def next_candle() -> dict[str, list[Any]]:
        rng = state["rng"]
        assert isinstance(rng, np.random.Generator)
        settings = REGIMES[regime.value]
        previous_close = float(state["close"])
        previous_date = cast(pd.Timestamp, pd.Timestamp(state["date"]))
        date = next_bar_time(previous_date)
        bar_index = int(state["index"]) + 1
        opening_bar = date.hour == 9 and date.minute == 30
        anchor = 100.0
        bar_fraction = 1 / BARS_PER_SESSION
        sigma = 0.012 * settings["volatility"] * volatility.value * np.sqrt(bar_fraction)
        drift = settings["drift"] * bar_fraction
        pull = settings["reversion"] * bar_fraction * np.log(anchor / previous_close)
        gap_scale = 0.55 if opening_bar else 0.08
        opening_move = rng.normal(drift * gap_scale, sigma * gap_scale)
        bar_move = rng.normal(drift + pull, sigma)
        shock = float(state["shock"])
        state["shock"] = 0.0
        open_price = previous_close * np.exp(opening_move)
        close_price = open_price * np.exp(bar_move + shock)
        excursion = abs(rng.normal(sigma * 0.55, sigma * 0.2))
        high = max(open_price, close_price) * (1 + excursion)
        low = min(open_price, close_price) * max(0.05, 1 - excursion * rng.uniform(0.72, 1.18))
        move = abs(close_price / previous_close - 1)
        minutes_since_open = (date.hour * 60 + date.minute) - (9 * 60 + 30)
        session_position = minutes_since_open / (390 - BAR_MINUTES)
        activity = 0.72 + 0.65 * abs(2 * session_position - 1) ** 1.5
        volume = rng.lognormal(np.log(settings["volume"] * activity * 1_000_000), 0.25) * (
            1 + 12 * move
        )
        color = TEAL if close_price >= open_price else CORAL
        state.update(index=bar_index, date=date, close=close_price)
        return {
            "index": [bar_index],
            "date": [date],
            "open": [open_price],
            "high": [high],
            "low": [low],
            "close": [close_price],
            "volume": [int(volume)],
            "volume_millions": [volume / 1_000_000],
            "body_top": [max(open_price, close_price)],
            "body_bottom": [min(open_price, close_price)],
            "color": [color],
        }

    def reset_indicators() -> None:
        shown = cast(pd.DataFrame, pd.DataFrame(price_source.data))
        fast_average = shown["close"].ewm(span=12, adjust=False).mean()
        slow_average = shown["close"].ewm(span=26, adjust=False).mean()
        macd_values = fast_average - slow_average
        signal_values = macd_values.ewm(span=9, adjust=False).mean()
        indicator_source.data = {
            "index": shown["index"].to_numpy(dtype=np.int32),
            "date": shown["date"].to_list(),
            "macd": macd_values.to_numpy(dtype=np.float32),
            "signal": signal_values.to_numpy(dtype=np.float32),
            "positive_macd": np.maximum(macd_values, signal_values).to_numpy(dtype=np.float32),
            "positive_signal": signal_values.to_numpy(dtype=np.float32),
            "negative_macd": np.minimum(macd_values, signal_values).to_numpy(dtype=np.float32),
            "negative_signal": signal_values.to_numpy(dtype=np.float32),
        }
        state["fast_ema"] = float(fast_average.iloc[-1])
        state["slow_ema"] = float(slow_average.iloc[-1])
        state["signal_ema"] = float(signal_values.iloc[-1])

    def append_indicators(candles: dict[str, list[Any]]) -> None:
        values = {name: [] for name in indicator_source.data}
        for index, date, close in zip(
            candles["index"], candles["date"], candles["close"], strict=True
        ):
            fast = FAST_ALPHA * close + (1 - FAST_ALPHA) * state["fast_ema"]
            slow = SLOW_ALPHA * close + (1 - SLOW_ALPHA) * state["slow_ema"]
            macd_value = fast - slow
            signal_value = SIGNAL_ALPHA * macd_value + (1 - SIGNAL_ALPHA) * state["signal_ema"]
            state.update(fast_ema=fast, slow_ema=slow, signal_ema=signal_value)
            values["index"].append(index)
            values["date"].append(date)
            values["macd"].append(macd_value)
            values["signal"].append(signal_value)
            values["positive_macd"].append(max(macd_value, signal_value))
            values["positive_signal"].append(signal_value)
            values["negative_macd"].append(min(macd_value, signal_value))
            values["negative_signal"].append(signal_value)
        indicator_source.stream(cast(Any, values), rollover=WINDOW_BARS)

    def update_summary() -> None:
        shown = cast(pd.DataFrame, pd.DataFrame(price_source.data))
        latest = shown.iloc[-1]
        previous = shown.iloc[-2]
        returns = shown["close"].pct_change().dropna().tail(20)
        move = latest["close"] / previous["close"] - 1
        annualized = (
            float(returns.std() * np.sqrt(252 * BARS_PER_SESSION)) if len(returns) > 1 else 0.0
        )
        drawdown = latest["close"] / shown["close"].max() - 1
        set_metric(close_card, f"${latest['close']:.2f}")
        set_metric(move_card, f"{move:+.2%}")
        set_metric(volatility_card, f"{annualized:.1%}")
        set_metric(drawdown_card, f"{drawdown:.1%}")
        latest_date = cast(pd.Timestamp, pd.Timestamp(latest["date"]))
        simulation_status.text = (
            f"<p><strong>{latest_date:%B %d, %Y · %H:%M}</strong><br>"
            f"Showing {len(shown)} generated 15-minute bars in the rolling window.</p>"
        )
        bar_range.start = float(shown["index"].min()) - 2
        bar_range.end = float(shown["index"].max()) + 2
        tick_positions = np.linspace(0, len(shown) - 1, 6, dtype=int)
        bar_ticker.ticks = [int(shown.iloc[position]["index"]) for position in tick_positions]
        labels = {
            int(shown.iloc[position]["index"]): cast(
                pd.Timestamp, pd.Timestamp(shown.iloc[position]["date"])
            ).strftime("%b %d %H:%M")
            for position in tick_positions
        }
        for plot in (price, volume, macd):
            plot.xaxis[0].major_label_overrides = cast(Any, labels)

    @performance.measure
    def reset_simulation() -> None:
        state.update(
            rng=np.random.default_rng(SEED),
            index=-1,
            date=pd.Timestamp("2025-01-06 09:15"),
            close=100.0,
            shock=0.0,
            ticks=0,
        )
        columns: dict[str, list[Any]] = {name: [] for name in price_source.data}
        for _ in range(SEED_BARS):
            candle = next_candle()
            for name, values in candle.items():
                columns[name].extend(values)
        price_source.data = cast(Any, columns)
        reset_indicators()
        update_summary()
        coalescer.reset()

    @performance.measure
    def advance(*, force: bool = False) -> None:
        if not playing.active and not force:
            return
        if force:
            updates = 1
        else:
            state["ticks"] = int(state["ticks"]) + coalescer.due_ticks()
            updates, state["ticks"] = divmod(int(state["ticks"]), UPDATE_TICKS[speed.value])
        if not updates:
            return
        candles: dict[str, list[Any]] = {name: [] for name in price_source.data}
        for _ in range(updates):
            for name, values in next_candle().items():
                candles[name].extend(values)
        price_source.stream(cast(Any, candles), rollover=WINDOW_BARS)
        append_indicators(candles)
        update_summary()

    @performance.measure
    def regime_changed(_attr: str, _old: object, _new: object) -> None:
        update_regime_note()
        reset_simulation()

    @performance.measure
    def playback_changed(_attr: str, _old: bool, active: bool) -> None:
        playing.label = "Pause simulation" if active else "Resume simulation"
        if active:
            coalescer.reset()

    @performance.measure
    def inject_selloff() -> None:
        state["shock"] = -0.08
        if not playing.active:
            advance(force=True)

    regime.on_change("value", regime_changed)
    playing.on_change("active", playback_changed)
    selloff.on_click(inject_selloff)
    restart.on_click(reset_simulation)
    reset_simulation()
    document.add_periodic_callback(advance, 150)

    key = Div(
        text=(
            f'<p style="color:{MUTED};font-size:12px"><span style="color:{TEAL}">&#9632;</span> Closed at or above the open'
            f'<br><span style="color:{CORAL}">&#9632;</span> Closed below the open</p>'
        )
    )
    note = Div(
        text=(
            f"<p><strong>Simulation:</strong> a seeded stochastic model generates an unlimited 15-minute OHLC and "
            "volume stream during regular market hours; the chart compresses non-trading gaps. "
            f"Seed <code>{SEED}</code> makes each restart reproducible. These values are synthetic and are not market "
            "data or investment guidance.</p>"
        )
    )
    controls = column(
        Div(text="<h2>Test a live market view</h2>"),
        regime,
        regime_note,
        volatility,
        speed,
        playing,
        wrap_row(selloff, restart),
        simulation_status,
        key,
        width=320,
        sizing_mode="stretch_height",
        styles={"background": "#f7f3ec", "padding": "20px", "border": "1px solid #ded7ce"},
    )
    match_background(controls, WARM)

    metrics = metric_row(
        close_card, move_card, volatility_card, drawdown_card, sizing_mode="stretch_width"
    )

    document.add_root(
        column(
            metrics,
            responsive_row(controls, price, sizing_mode="stretch_width"),
            volume,
            macd,
            note,
            sizing_mode="stretch_width",
            spacing=16,
        )
    )
    prepare_document(document, "/market-monitor")
