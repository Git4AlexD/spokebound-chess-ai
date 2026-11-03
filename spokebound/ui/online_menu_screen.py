"""Sub-menu shown after choosing "Online Match" from the main menu:
invite a friend directly, or (once it exists) play a matched,
competitive game."""

import tkinter as tk
from collections.abc import Callable

from spokebound.ui import starfield, theme
from spokebound.ui.layout import watch_resize, window_scale
from spokebound.ui.mode_card import ModeCard
from spokebound.ui.settings_gear import add_gear

CARD_WIDTH = 280
CARD_HEIGHT = 160
# How far these cards may grow past their base size to fill a big
# window — see layout.window_scale.
MAX_SCALE = 2.2

# (title, blurb, key) — same shape as welcome_screen.MODES, and the
# same rule: only a key present in the callbacks dict is clickable.
MODES = [
    ("Invite a Friend", "Host a game on this device, or join one a "
                        "friend is hosting.", "invite"),
    ("Competitive", "Get matched with another player online.",
     "competitive"),
]


class OnlineMenuScreen(tk.Frame):
    """Two choices, side by side — same card language as the main menu,
    just without its responsive grid: two cards never need one."""

    def __init__(self, parent: tk.Misc,
                 callbacks: dict[str, Callable[[], None]],
                 on_main_menu: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._callbacks = callbacks
        self._on_main_menu = on_main_menu
        self._rebuild()
        # Keeps the cards' scale matched to the window as it's resized
        # (see the same note on AIMenuScreen).
        watch_resize(self, self._rebuild)

    def _rebuild(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        starfield.add_starfield(self)
        scale = window_scale(self, max_scale=MAX_SCALE)
        theme.make_button(self, "Main Menu", self._on_main_menu,
                          secondary=True).pack(anchor=tk.NW, padx=16,
                                               pady=16)
        centre = tk.Frame(self, bg=theme.BACKGROUND)
        centre.place(relx=0.5, rely=0.5, anchor="center")
        theme.make_label(centre, "Online Match",
                         theme.scaled_font(theme.FONT_TITLE, scale),
                         fg=theme.ACCENT).pack(pady=(0, round(24 * scale)))

        row = tk.Frame(centre, bg=theme.BACKGROUND)
        row.pack()
        for title, blurb, key in MODES:
            card = ModeCard(row, title, blurb, self._callbacks.get(key),
                            round(CARD_WIDTH * scale),
                            round(CARD_HEIGHT * scale))
            card.pack(side=tk.LEFT, padx=round(10 * scale))
        add_gear(self)
