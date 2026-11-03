"""The first screen: pick a game mode.

Only 2-Player Local, Play vs AI, Instructions and Custom Fleets are wired
up so far. The other two are laid out and styled already so hooking them
up later is just adding a callback.

The card grid is rebuilt (not just uniformly scaled) whenever the window
is resized: how many columns it uses and how big each card is are both
recomputed from the window's actual size, so the grid genuinely fills
the width left to right at any size rather than sitting as a fixed-size
block in the middle of a mostly-empty window.
"""

import tkinter as tk
from collections.abc import Callable

from spokebound.model.pieces import Player, make_captain
from spokebound.ui import drawing, starfield, theme
from spokebound.ui.fit_text import fit_font_size
from spokebound.ui.mode_card import ModeCard
from spokebound.ui.settings_gear import add_gear

BASE_CARD_WIDTH = 260
BASE_CARD_HEIGHT = 150
CARD_ASPECT = BASE_CARD_WIDTH / BASE_CARD_HEIGHT

# A wide window (width at least this much taller-than-square) gets a
# 3-column grid instead of 2, so the extra width goes into more columns
# rather than just wider cards.
WIDE_ASPECT_THRESHOLD = 1.15
MIN_CARD_WIDTH = 200
MAX_CARD_WIDTH = 420
WIDTH_MARGIN_FRACTION = 0.08
HEIGHT_FRACTION = 0.88
GAP_FRACTION = 0.02

# Resize events fire in a burst while a window is being dragged; wait
# for them to stop for this long before actually rebuilding the grid.
REBUILD_DEBOUNCE_MS = 80

GAME_TITLE = "Spokebound"
CAPTAIN_ICON_SIZE = 92
TITLE_ICON_GAP = 14

# (title, description, key). Only a key present in the callbacks dict
# passed to WelcomeScreen is clickable; the rest show as coming soon.
MODES = [
    ("2-Player Local", "Build, deploy and play against a friend on this "
                       "device.", "local"),
    ("Instructions", "Learn the rules.",
     "tutorial"),
    ("Online Match", "Challenge another player over the network.",
     "online"),
    ("Play vs AI", "Play against an AI opponent.", "ai"),
    ("Custom Fleets", "Build and save your own fleets to use later.",
     "custom_fleets"),
    ("Story Mode", "A guided campaign against a series of opponents.",
     "story"),
]


def _layout_for(width: int, height: int) -> dict:
    """Work out the column count and per-card size that fills ``width``
    x ``height`` — a wide window gets more columns, and card size scales
    with the window's own width (clamped to a sane range) rather than
    against some fixed baseline, so the grid actually fills the space
    left to right instead of just centring a fixed-size block."""
    columns = 3 if width >= height * WIDE_ASPECT_THRESHOLD else 2
    usable_width = width * (1 - 2 * WIDTH_MARGIN_FRACTION)
    gap = max(8, round(usable_width * GAP_FRACTION))
    card_width = (usable_width - (columns - 1) * gap) / columns
    card_width = max(MIN_CARD_WIDTH, min(MAX_CARD_WIDTH, card_width))
    card_height = card_width / CARD_ASPECT
    return {
        "columns": columns,
        "card_width": round(card_width),
        "card_height": round(card_height),
        "gap": round(gap),
    }


class WelcomeScreen(tk.Frame):
    """A grid of game-mode cards, proportioned to fill the window at
    whatever size it currently is; unimplemented modes show disabled."""

    def __init__(self, parent: tk.Misc,
                 callbacks: dict[str, Callable[[], None]]) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        starfield.add_starfield(self)
        self._callbacks = callbacks
        self._centre: tk.Frame | None = None
        self._last_size: tuple[int, int] | None = None
        self._rebuild_job: str | None = None

        self._gear = add_gear(self)

        self.bind("<Configure>", self._on_configure)
        self.bind("<Destroy>", self._on_destroy)
        # Not mapped yet at construction time (parent packs this after
        # __init__ returns), so this first call just finds a 1x1 frame
        # and reschedules itself — the real build happens once the
        # resulting <Configure> reports the actual packed size.
        self._rebuild()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._rebuild_job is not None:
            self.after_cancel(self._rebuild_job)
            self._rebuild_job = None

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._rebuild_job is not None:
            self.after_cancel(self._rebuild_job)
        self._rebuild_job = self.after(REBUILD_DEBOUNCE_MS, self._rebuild)

    def _rebuild(self) -> None:
        self._rebuild_job = None
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1:
            self._rebuild_job = self.after(REBUILD_DEBOUNCE_MS,
                                           self._rebuild)
            return
        if (width, height) == self._last_size:
            return
        self._last_size = (width, height)

        layout = _layout_for(width, height)

        # Build off-screen first to measure the real rendered height —
        # an estimate here previously undershot the true height and let
        # a third row clip off the bottom of short windows. This has to
        # use .place() (never .pack()) since the gear button and the
        # real content below both use .place() on this same frame, and
        # mixing geometry managers on one parent corrupts its geometry
        # bookkeeping even after the offending child is gone.
        probe = self._fill_centre(layout)
        probe.place(x=-10000, y=-10000)
        self.update_idletasks()
        needed = probe.winfo_reqheight()
        probe.destroy()

        available = height * HEIGHT_FRACTION
        if needed > available > 0:
            shrink = available / needed
            layout = dict(layout)
            layout["card_width"] = max(
                MIN_CARD_WIDTH, round(layout["card_width"] * shrink))
            layout["card_height"] = round(layout["card_width"] / CARD_ASPECT)
            layout["gap"] = max(4, round(layout["gap"] * shrink))

        if self._centre is not None:
            self._centre.destroy()
        self._centre = self._fill_centre(layout)
        self._centre.place(relx=0.5, rely=0.5, anchor="center")
        # Each rebuild creates a brand new centre frame, which Tk stacks
        # above the gear button (created once, back in __init__) by
        # default — re-assert the gear button on top every time so a
        # wide card grid never covers the corner it sits in.
        self._gear.lift()

    def _fill_centre(self, layout: dict) -> tk.Frame:
        centre = tk.Frame(self, bg=theme.BACKGROUND)
        title_row = tk.Frame(centre, bg=theme.BACKGROUND)
        title_row.pack(pady=(0, 2))
        # The full name between both icons is wider than the smallest
        # window this app allows, so the text shrinks to the room that's
        # actually there rather than running off both sides.
        family, size, weight = theme.FONT_HERO
        room = round(self.winfo_width() * (1 - 2 * WIDTH_MARGIN_FRACTION)
                     - 2 * (CAPTAIN_ICON_SIZE + TITLE_ICON_GAP))
        title_font = (family, fit_font_size(self, GAME_TITLE, family, size,
                                            room, weight=weight), weight)
        self._draw_captain_icon(title_row, Player.ORANGE, rotated=False).pack(
            side=tk.LEFT, padx=(0, TITLE_ICON_GAP))
        theme.make_label(title_row, GAME_TITLE, title_font,
                         fg=theme.ACCENT).pack(side=tk.LEFT)
        self._draw_captain_icon(title_row, Player.WHITE, rotated=True).pack(
            side=tk.LEFT, padx=(TITLE_ICON_GAP, 0))
        theme.make_label(
            centre, "Build Your Fleet, Push Your Captain To The Core",
            theme.FONT_BODY, fg=theme.MUTED_TEXT).pack(pady=(0, 24))

        grid = tk.Frame(centre, bg=theme.BACKGROUND)
        grid.pack()
        columns = layout["columns"]
        pad = max(4, layout["gap"] // 2)
        for index, (title, blurb, key) in enumerate(MODES):
            card = ModeCard(grid, title, blurb, self._callbacks.get(key),
                            layout["card_width"], layout["card_height"])
            card.grid(row=index // columns, column=index % columns,
                      padx=pad, pady=pad)
        return centre

    def _draw_captain_icon(self, parent: tk.Misc, owner: Player,
                           rotated: bool) -> tk.Canvas:
        """Return a small canvas drawing ``owner``'s Captain — purely
        decorative, flanking the title with the two sides' own pieces
        rather than a generic logo."""
        size = CAPTAIN_ICON_SIZE
        canvas = tk.Canvas(parent, width=size, height=size,
                           bg=theme.BACKGROUND, highlightthickness=0)
        drawing.draw_star(canvas, (size / 2, size / 2), size * 0.42,
                          make_captain(owner), rotated=rotated)
        return canvas
