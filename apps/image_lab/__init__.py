"""Apply interactive image-processing operations to Hubble imagery."""

from __future__ import annotations

from html import escape
from time import perf_counter

import numpy as np
import xarray as xr
from bokeh.events import Pan, PanEnd, PanStart
from bokeh.layouts import column
from bokeh.models import (
    BoxAnnotation,
    Button,
    ColumnDataSource,
    CustomJS,
    Div,
    PanTool,
    Range1d,
    Select,
    Slider,
)
from bokeh.plotting import figure
from skimage import data

from apps._common import load_javascript, prepare_document, responsive_row, style_figure, wrap_row
from apps._common.colors import CORAL, GOLD
from apps.image_lab.processing import FILTERS


def image_heading(number: str, label: str, title: str, accent: str) -> str:
    return (
        '<div style="display:flex;align-items:center;gap:12px;min-height:46px;padding:0 0 10px;'
        'border-bottom:1px solid #ded7ce">'
        f'<span style="display:grid;place-items:center;width:30px;height:30px;flex:0 0 30px;'
        f'border:1px solid {accent};color:{accent};font:700 10px Arial,sans-serif;letter-spacing:.08em">'
        f"{escape(number)}</span>"
        '<span style="display:block">'
        f'<small style="display:block;color:#6f686c;font:700 9px Arial,sans-serif;letter-spacing:.12em;'
        f'text-transform:uppercase">{escape(label)}</small>'
        f'<strong style="display:block;margin-top:2px;color:#211f20;font:400 21px Georgia,serif">'
        f"{escape(title)}</strong></span></div>"
    )


def rgba_view(image: np.ndarray) -> np.ndarray:
    rgba = np.empty(image.shape[:2], dtype=np.uint32)
    channels = rgba.view(dtype=np.uint8).reshape((*image.shape[:2], 4))
    channels[..., :3] = image
    channels[..., 3] = 255
    return np.flipud(rgba)


def modify_document(document) -> None:
    raw = data.hubble_deep_field()
    cube = xr.DataArray(
        raw,
        dims=("y", "x", "channel"),
        coords={
            "y": np.arange(raw.shape[0]),
            "x": np.arange(raw.shape[1]),
            "channel": ["red", "green", "blue"],
        },
        name="Hubble Deep Field",
        attrs={"source": "NASA/STScI", "units": "8-bit intensity"},
    )
    sample = np.ascontiguousarray(raw[:8, :8])
    for image_filter in FILTERS.values():
        amount = image_filter.slider.value if image_filter.slider is not None else 1.0
        image_filter.processor(sample, amount)

    operation = Select(title="Processing step", value="Sobel edges", options=list(FILTERS))
    strength = Slider(title="Edge gain", start=0.5, end=5.0, value=2.2, step=0.1)
    reset_crop = Button(label="Reset crop", height=31, margin=(22, 0, 0, 0))
    crop = {"x": (260, 740), "y": (196, 676)}
    source_image = ColumnDataSource(data={"image": [rgba_view(raw)]})
    processed_source = ColumnDataSource(data={"image": []}, name="hubble-processed-image")
    initial_crop_box = {
        "left": 260 / raw.shape[1],
        "right": 740 / raw.shape[1],
        "bottom": 1 - 676 / raw.shape[0],
        "top": 1 - 196 / raw.shape[0],
    }
    initial_crop_handles = {
        "x": [
            initial_crop_box["left"],
            initial_crop_box["right"],
            initial_crop_box["right"],
            initial_crop_box["left"],
        ],
        "y": [
            initial_crop_box["bottom"],
            initial_crop_box["bottom"],
            initial_crop_box["top"],
            initial_crop_box["top"],
        ],
    }
    crop_handles = ColumnDataSource(data=dict(initial_crop_handles), name="hubble-crop-handles")
    crop_interaction = ColumnDataSource(
        data={
            "mode": [""],
            "start_x": [0.0],
            "start_y": [0.0],
            "left": [initial_crop_box["left"]],
            "right": [initial_crop_box["right"]],
            "bottom": [initial_crop_box["bottom"]],
            "top": [initial_crop_box["top"]],
        }
    )
    crop_pan = PanTool(dimensions="both")
    report = Div(
        name="hubble-processing-report",
        styles={
            "min-height": "68px",
            "padding": "14px 18px",
            "border-left": f"4px solid {CORAL}",
            "background": "#f3efe8",
        },
    )
    operation_note = Div()
    source_title = Div(
        text=image_heading("01", "Source image", "Editable crop", GOLD),
        height=57,
        name="hubble-source-heading",
    )
    processed_title = Div(
        text=image_heading("02", "Processed view", "Processed crop", CORAL),
        height=57,
        name="hubble-processed-heading",
    )

    original = figure(
        height=470,
        sizing_mode="stretch_width",
        x_range=Range1d(start=0, end=1, bounds=(0, 1), min_interval=1, max_interval=1),
        y_range=Range1d(start=0, end=1, bounds=(0, 1), min_interval=1, max_interval=1),
        x_axis_location=None,
        y_axis_location=None,
        tools=[crop_pan],
        active_drag=crop_pan,
        toolbar_location=None,
        name="hubble-source-plot",
    )
    original.image_rgba(image="image", x=0, y=0, dw=1, dh=1, source=source_image)
    original.grid.visible = False
    style_figure(original)
    crop_box = BoxAnnotation(
        **initial_crop_box,
        name="hubble-crop-box",
        fill_color=CORAL,
        fill_alpha=0.1,
        line_color=GOLD,
        line_width=2.5,
        hover_fill_color=CORAL,
        hover_fill_alpha=0.15,
        hover_line_color=GOLD,
        hover_line_width=3,
    )
    original.add_layout(crop_box)
    original.scatter(
        x="x",
        y="y",
        source=crop_handles,
        marker="square",
        size=11,
        fill_color=GOLD,
        line_color="#fffdf9",
        line_width=1.5,
    )

    start_crop = CustomJS(
        args={"box": crop_box, "state": crop_interaction},
        code=load_javascript(__file__, "start_crop.js"),
    )
    update_crop_box = CustomJS(
        args={"box": crop_box, "handles": crop_handles, "state": crop_interaction},
        code=load_javascript(__file__, "update_crop_box.js"),
    )
    end_crop = CustomJS(
        args={"state": crop_interaction}, code=load_javascript(__file__, "end_crop.js")
    )
    original.js_on_event(PanStart, start_crop)
    original.js_on_event(Pan, update_crop_box)
    original.js_on_event(PanEnd, end_crop)

    processed = figure(
        height=470,
        sizing_mode="stretch_width",
        x_range=Range1d(start=0, end=1),
        y_range=Range1d(start=0, end=1),
        tools="",
        toolbar_location=None,
        x_axis_location=None,
        y_axis_location=None,
        name="hubble-processed-plot",
    )
    processed.image_rgba(image="image", x=0, y=0, dw=1, dh=1, source=processed_source)
    processed.grid.visible = False
    style_figure(processed)

    configuring = {"operation": False}
    pending_crop_update = {"callback": None}

    def calculate() -> None:
        x_low, x_high = crop["x"]
        y_low, y_high = crop["y"]
        selection = cube.sel(x=slice(x_low, x_high), y=slice(y_low, y_high)).isel(
            x=slice(None, None, 2), y=slice(None, None, 2)
        )
        image = np.ascontiguousarray(selection.values)
        image_filter = FILTERS[operation.value]
        started = perf_counter()
        result = image_filter.processor(image, strength.value)
        elapsed = 1000 * (perf_counter() - started)
        height, width, _ = image.shape
        processed_source.data = {"image": [rgba_view(result)]}
        processed_title.text = image_heading("02", "Processed view", operation.value, CORAL)
        report.text = (
            f"<p><strong>{operation.value}</strong> applied &nbsp; <strong>{width} x {height}</strong> pixels &nbsp; "
            f"<strong>{elapsed:.1f} ms</strong> Numba kernel</p>"
            f"<p>Xarray selection: <code>x={x_low}:{x_high}</code>, <code>y={y_low}:{y_high}</code>, dimensions {selection.dims}.</p>"
        )

    def apply_crop() -> None:
        pending_crop_update["callback"] = None
        bounds = (crop_box.left, crop_box.right, crop_box.bottom, crop_box.top)
        left_value, right_value, bottom_value, top_value = bounds
        if not (
            isinstance(left_value, (int, float))
            and isinstance(right_value, (int, float))
            and isinstance(bottom_value, (int, float))
            and isinstance(top_value, (int, float))
        ):
            return
        left, right = sorted((float(left_value), float(right_value)))
        bottom, top = sorted((float(bottom_value), float(top_value)))
        x_low = int(np.clip(left * raw.shape[1], 0, raw.shape[1] - 1))
        x_high = int(np.clip(right * raw.shape[1], x_low + 1, raw.shape[1]))
        y_low = int(np.clip((1 - top) * raw.shape[0], 0, raw.shape[0] - 1))
        y_high = int(np.clip((1 - bottom) * raw.shape[0], y_low + 1, raw.shape[0]))
        crop["x"] = (x_low, x_high)
        crop["y"] = (y_low, y_high)
        calculate()

    def update_crop(_attr: str, _old: object, _new: object) -> None:
        callback = pending_crop_update["callback"]
        if callback is not None:
            document.remove_timeout_callback(callback)
        if document.session_context is None:
            apply_crop()
        else:
            pending_crop_update["callback"] = document.add_timeout_callback(apply_crop, 80)

    def restore_crop() -> None:
        crop["x"] = (260, 740)
        crop["y"] = (196, 676)
        crop_box.update(**initial_crop_box)
        crop_handles.data = dict(initial_crop_handles)

    def configure_filter(_attr: str, _old: object, _new: object) -> None:
        image_filter = FILTERS[operation.value]
        slider = image_filter.slider
        configuring["operation"] = True
        if slider is not None:
            strength.start = slider.start
            strength.end = slider.end
            strength.step = slider.step
            strength.value = slider.value
            strength.title = slider.title
        strength.disabled = slider is None
        strength.visible = slider is not None
        configuring["operation"] = False
        operation_note.text = f"<p>{image_filter.description}</p>"
        calculate()

    def update_strength(_attr: str, _old: object, _new: object) -> None:
        if not configuring["operation"]:
            calculate()

    operation.on_change("value", configure_filter)
    strength.on_change("value", update_strength)
    reset_crop.on_click(restore_crop)
    for property_name in ("left", "right", "bottom", "top"):
        crop_box.on_change(property_name, update_crop)
    configure_filter("value", None, operation.value)

    intro = Div(
        text=(
            "<h2>Process a Hubble image</h2>"
            "<p>Move or resize the crop box in the source image. Xarray turns that region into a coordinate-aware selection, then a Numba-compiled filter processes its pixels.</p>"
        )
    )
    controls = column(
        wrap_row(operation, strength, reset_crop, sizing_mode="stretch_width"), operation_note
    )
    crop_guide = Div(
        text=(
            "<p><strong>Move:</strong> drag anywhere inside the shaded crop. "
            "<strong>Resize:</strong> drag any gold corner. "
            "The processed image updates after each adjustment.</p>"
        ),
        styles={
            "padding": "10px 14px",
            "background": "#f3efe8",
            "border-left": f"4px solid {GOLD}",
        },
    )
    document.add_root(
        column(
            intro,
            controls,
            report,
            crop_guide,
            responsive_row(
                column(source_title, original, sizing_mode="stretch_width"),
                column(processed_title, processed, sizing_mode="stretch_width"),
                sizing_mode="stretch_width",
            ),
            Div(
                text=(
                    "<p><strong>Data:</strong> NASA Hubble Deep Field image distributed with scikit-image. "
                    "The image is public domain. Processing runs locally in the Bokeh server session.</p>"
                )
            ),
            sizing_mode="stretch_width",
            spacing=18,
        )
    )
    prepare_document(document, "/image-processing")
