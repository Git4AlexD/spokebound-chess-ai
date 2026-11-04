"""Shrinking text to fit a fixed box, instead of the box changing shape
to fit the text."""

import tkinter as tk
import tkinter.font as tkfont


def fit_font_size(
    widget: tk.Misc,
    text: str,
    family: str,
    base_size: int,
    max_width: int,
    min_size: int = 7,
    *,
    weight: str = "normal",
) -> int:
    """Return the largest font size from ``base_size`` down to
    ``min_size`` at which ``text`` renders no wider than ``max_width``
    pixels, in ``family`` at ``weight``. Falls back to ``min_size`` if
    even that doesn't fit — still the smallest this will ever go, never
    wider."""
    size = abs(base_size)
    while size > min_size:
        measured = tkfont.Font(root=widget, family=family, size=size, weight=weight).measure(text)
        if measured <= max_width:
            return size
        size -= 1
    return min_size
