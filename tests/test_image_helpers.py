"""Test lightweight helpers used by the image-processing view."""

from __future__ import annotations

import numpy as np

from apps.image_lab import image_heading, rgba_view


def test_image_heading_escapes_content_and_applies_accent() -> None:
    html = image_heading("<1>", "Raw & source", "Stars <script>", "#123456")

    assert "&lt;1&gt;" in html
    assert "Raw &amp; source" in html
    assert "Stars &lt;script&gt;" in html
    assert "#123456" in html
    assert "<script>" not in html


def test_rgba_view_adds_opaque_alpha_and_flips_vertical_axis() -> None:
    image = np.array([[[1, 2, 3], [4, 5, 6]], [[7, 8, 9], [10, 11, 12]]], dtype=np.uint8)
    rgba = rgba_view(image)
    channels = rgba.view(np.uint8).reshape(2, 2, 4)

    assert rgba.dtype == np.uint32
    assert channels[..., :3].tolist() == image[::-1].tolist()
    assert np.all(channels[..., 3] == 255)
