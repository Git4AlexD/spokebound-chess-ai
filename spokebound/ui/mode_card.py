"""A clickable-or-disabled card offering one named choice among several
— the main menu's game modes, and any other screen built the same way
(see :mod:`spokebound.ui.online_menu_screen`)."""

import tkinter as tk
from collections.abc import Callable

from spokebound.ui import sound, theme


class ModeCard(tk.Frame):
    """One clickable (or not) card in a menu of named choices.

    ``command`` being ``None`` is what marks a choice as not
    implemented yet: the card renders muted rather than accented, shows
    "Coming soon." under its own blurb, and stays inert to clicks.
    """

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        blurb: str,
        command: Callable[[], None] | None,
        width: int,
        height: int,
    ) -> None:
        enabled = command is not None
        bg = theme.ACCENT if enabled else theme.PANEL
        fg = theme.ON_ACCENT if enabled else theme.TEXT
        sub_fg = theme.ON_ACCENT if enabled else theme.MUTED_TEXT
        super().__init__(
            parent,
            bg=bg,
            width=width,
            height=height,
            highlightthickness=1,
            highlightbackground=(theme.ACCENT_DARK if enabled else theme.DISABLED),
        )
        self.pack_propagate(False)
        self._bg = bg
        self._hover_bg = theme.ACCENT_DARK if enabled else bg

        title_label = theme.make_label(
            self, title, theme.FONT_HEADING, fg=fg, bg=bg, wraplength=width - 32, justify=tk.LEFT
        )
        title_label.pack(anchor=tk.W, padx=18, pady=(18, 6))
        blurb_text = blurb if enabled else f"{blurb}\nComing soon."
        blurb_label = theme.make_label(
            self, blurb_text, theme.FONT_SMALL, fg=sub_fg, bg=bg, wraplength=width - 32, justify=tk.LEFT
        )
        blurb_label.pack(anchor=tk.W, padx=18)

        widgets = (self, title_label, blurb_label)
        if enabled:

            def on_click(_event: tk.Event) -> None:
                sound.play_button_click()
                command()

            for widget in widgets:
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>", on_click)
                widget.bind("<Enter>", self._on_enter)
                widget.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event: tk.Event) -> None:
        self._recolour(self._hover_bg)

    def _on_leave(self, _event: tk.Event) -> None:
        self._recolour(self._bg)

    def _recolour(self, bg: str) -> None:
        self.configure(bg=bg)
        for child in self.winfo_children():
            child.configure(bg=bg)
