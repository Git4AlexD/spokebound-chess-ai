"""Difficulty picker shown after choosing "Play vs AI" from the main
menu, before building a fleet against the computer."""

import tkinter as tk
from collections.abc import Callable

from spokebound.ai.levels import LEVELS
from spokebound.ui import sound, starfield, theme
from spokebound.ui.layout import watch_resize, window_scale
from spokebound.ui.settings_gear import add_gear

# One short line per level (see spokebound.ai.levels.LEVELS for the
# actual search and pregame_skill profile each one runs). There's one AI
# here, not a separate weak one and a separate strong one — every level
# is the same engine and the same fleet-building/deployment logic, just
# handed a shallower depth, a smaller time budget and less confidence in
# its own pregame setup; no level, at any difficulty, ever looks at your
# built fleet before building its own.
_BLURBS = {
    1: "Only looks one move ahead, and builds and deploys its fleet "
      "almost by chance. Easy to out-plan.",
    2: "One or two moves ahead, with only a rough sense of how to build "
      "or place a fleet.",
    3: "Same shallow search, but tries its own best-looking move first; "
      "fleet-building is still mostly guesswork.",
    4: "Plans a few moves ahead, and starts building and placing its "
      "fleet with real, if shaky, judgement.",
    5: "Genuine lookahead, with a fleet and deployment that are starting "
      "to reflect real strategy.",
    6: "Searches deeper still, with a real tactical sense and a fleet "
      "built on solid, if not perfect, judgement.",
    7: "Deeper again, with sharper fleet-building and placement to "
      "go with it.",
    8: "Strong tactical play, with a fleet built on nearly its full, "
      "evolved strategy. It never looks at yours.",
    9: "Very strong: deep search, careful play, and pregame setup very "
      "close to this AI's best-known strategy.",
    10: "As deep and as thorough as this AI gets, with its fully "
       "evolved fleet-building and placement. The strongest setting "
       "there is: no human should expect to beat this one.",
}
_DEFAULT_LEVEL = 5
_MIN_LEVEL = min(LEVELS)
_MAX_LEVEL = max(LEVELS)


class AIMenuScreen(tk.Frame):
    """Pick a difficulty level — 1 (easiest) to the top of the ladder
    (hardest) — before building an fleet against the computer."""

    def __init__(self, parent: tk.Misc, on_choose: Callable[[int], None],
                 on_main_menu: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._on_choose = on_choose
        self._on_main_menu = on_main_menu
        # Set before the first _rebuild below, so landing on the
        # default level doesn't itself count as a change worth a click.
        self._last_level = _DEFAULT_LEVEL
        self._level = _DEFAULT_LEVEL
        self._rebuild()
        # Keeps this screen's scale matched to the window as it's
        # resized — un-maximizing, dragging an edge — not just at the
        # moment it was first shown (see layout.window_scale: this
        # screen is otherwise a fixed size regardless of the window,
        # which leaves it looking small and lost on a big one).
        watch_resize(self, self._rebuild)

    def _rebuild(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        # Rebuilt fresh every time alongside everything else above,
        # since the destroy loop just above wipes out the one from last
        # time too — add_starfield's own .lower() keeps it behind
        # whatever's about to be built here regardless of order.
        starfield.add_starfield(self)
        scale = window_scale(self)
        theme.make_button(self, "Main Menu", self._on_main_menu,
                          secondary=True).pack(anchor=tk.NW, padx=16,
                                               pady=16)
        centre = tk.Frame(self, bg=theme.BACKGROUND)
        centre.place(relx=0.5, rely=0.5, anchor="center")
        theme.make_label(centre, "Choose a Difficulty",
                         theme.scaled_font(theme.FONT_TITLE, scale),
                         fg=theme.ACCENT).pack(pady=(0, round(24 * scale)))

        self._level_label = theme.make_label(
            centre, "", theme.scaled_font(theme.FONT_HEADING, scale),
            fg=theme.TEXT)
        self._level_label.pack(pady=(0, round(4 * scale)))
        self._blurb_label = theme.make_label(
            centre, "", theme.scaled_font(theme.FONT_SMALL, scale),
            fg=theme.MUTED_TEXT, wraplength=round(360 * scale),
            justify=tk.CENTER)
        self._blurb_label.pack(pady=(0, round(16 * scale)))

        self._scale = tk.Scale(
            centre, from_=_MIN_LEVEL, to=_MAX_LEVEL, orient=tk.HORIZONTAL,
            length=round(360 * scale), showvalue=False, bg=theme.BACKGROUND,
            fg=theme.TEXT, troughcolor=theme.PANEL, highlightthickness=0,
            activebackground=theme.ACCENT, command=self._on_slide)
        self._scale.set(self._level)
        self._scale.pack(pady=(0, round(8 * scale)))

        ends = tk.Frame(centre, bg=theme.BACKGROUND)
        ends.pack(fill=tk.X, pady=(0, round(20 * scale)))
        small_font = theme.scaled_font(theme.FONT_SMALL, scale)
        theme.make_label(ends, f"{_MIN_LEVEL} · Easiest", small_font,
                         fg=theme.MUTED_TEXT).pack(side=tk.LEFT)
        theme.make_label(ends, f"{_MAX_LEVEL} · Hardest", small_font,
                         fg=theme.MUTED_TEXT).pack(side=tk.RIGHT)

        self._on_slide(self._level)
        theme.make_button(
            centre, "Start", lambda: self._on_choose(self._scale.get())
        ).pack()
        add_gear(self)

    def _on_slide(self, value: str | int) -> None:
        self._level = int(float(value))
        level = LEVELS[int(float(value))]
        if level.number != self._last_level:
            sound.play_button_click()
            self._last_level = level.number
        self._level_label.config(text=f"Level {level.number}: {level.name}")
        self._blurb_label.config(text=_BLURBS[level.number])
