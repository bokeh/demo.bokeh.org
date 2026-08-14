"""Assemble the structured spectrum-monitor example.

Unlike the smaller single-file demos, this app separates numerical simulation,
Bokeh model construction, and per-session behavior so each concern remains readable.
"""

from __future__ import annotations

from bokeh.document import Document

from apps._common import prepare_document
from apps.spectrum.receiver import Receiver
from apps.spectrum.view import build_view


def modify_document(document: Document) -> None:
    # Keep the document assembly visible while the larger pieces live in focused modules.
    view = build_view()
    Receiver(view).connect(document)
    document.add_root(view.root)
    prepare_document(document, "/spectrum-monitor")
