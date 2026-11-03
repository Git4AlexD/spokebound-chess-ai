"""A fixed-width vertical list of preset-fleet buttons, shared between
the real build screen (built-in presets on the left, saved custom ones
on the right) and the custom-fleet builder on the main menu."""

import tkinter as tk
from collections.abc import Callable

from spokebound.ui import theme


def build_preset_column(parent: tk.Misc, heading: str,
                        entries: list[tuple[str, Callable[[], None]]],
                        width: int, height: int, gap: int,
                        empty_text: str | None = None,
                        on_delete: Callable[[str], None] | None = None
                        ) -> tk.Frame:
    """One vertical list of fixed-size preset buttons, each pinned to
    ``width`` x ``height`` regardless of its own name's length — a long
    preset name shrinks its own label rather than widening the button
    or the column around it. ``empty_text`` shows instead when
    ``entries`` is empty. ``on_delete``, if given, adds a small delete
    button beside each entry, called with that entry's name.
    """
    column = tk.Frame(parent, bg=theme.BACKGROUND)
    theme.make_label(column, heading, theme.FONT_SMALL,
                     fg=theme.MUTED_TEXT, wraplength=width).pack(
        anchor=tk.W, pady=(0, gap))
    if not entries and empty_text:
        theme.make_label(column, empty_text, theme.FONT_SMALL,
                         fg=theme.MUTED_TEXT, wraplength=width,
                         justify=tk.LEFT).pack(anchor=tk.W)
    for name, callback in entries:
        if on_delete is None:
            theme.make_fixed_button(column, name, callback, width,
                                    height).pack(pady=(0, gap))
            continue
        row = tk.Frame(column, bg=theme.BACKGROUND)
        row.pack(pady=(0, gap))
        theme.make_fixed_button(row, name, callback, width - height - gap,
                                height).pack(side=tk.LEFT)
        theme.make_fixed_button(
            row, "×", lambda name=name: on_delete(name), height,
            height, min_font_size=9).pack(side=tk.LEFT, padx=(gap, 0))
    return column
