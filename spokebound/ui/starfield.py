"""A small reusable starfield: a fixed scatter of background stars,
used both inside board_view.BoardView's own canvas and, via
:func:`add_starfield`, behind every plain menu screen's real content.
"""

import random
import tkinter as tk

from spokebound.ui import theme

# Stars per square pixel of canvas, for the fixed scatter below —
# sparse enough to read as depth, not noise.
_STAR_DENSITY = 1 / 2200

Star = tuple[float, float, float, str, bool]


def make_stars(width: int, height: int) -> list[Star]:
    """Return a fixed, deterministic scatter of background stars across
    a ``width`` x ``height`` area (x, y, radius, colour, sparkle).

    A fixed seed means a given size always gets the same scatter rather
    than jittering every time it's regenerated for a new size (a board
    rebuilt on resize, a menu screen's own background catching up to
    its window).
    """
    rng = random.Random("spokebound-starfield")
    count = max(16, int(width * height * _STAR_DENSITY))
    stars: list[Star] = []
    for _ in range(count):
        x, y = rng.uniform(0, width), rng.uniform(0, height)
        roll = rng.random()
        if roll > 0.95:
            stars.append((x, y, rng.uniform(1.5, 2.3), theme.STAR_BRIGHT, True))
        elif roll > 0.78:
            stars.append((x, y, rng.uniform(1.0, 1.5), theme.STAR_MID, False))
        else:
            stars.append((x, y, rng.uniform(0.5, 0.9), theme.STAR_DIM, False))
    return stars


def draw_stars(canvas: tk.Canvas, stars: list[Star]) -> None:
    """Draw ``stars`` (see :func:`make_stars`) onto ``canvas`` — the
    brightest tier also gets a small plus-shaped sparkle, not just a
    bigger dot."""
    for x, y, r, colour, sparkle in stars:
        canvas.create_oval(x - r, y - r, x + r, y + r, fill=colour,
                           outline="")
        if sparkle:
            span = r * 2.6
            canvas.create_line(x - span, y, x + span, y, fill=colour,
                               width=1)
            canvas.create_line(x, y - span, x, y + span, fill=colour,
                               width=1)


class _StarfieldCanvas(tk.Canvas):
    """A borderless canvas that tracks its parent's size and keeps a
    starfield (see module docstring) drawn to fill it, regenerating
    only when its size actually changes rather than on every
    <Configure> event a resize fires in a burst."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=theme.BACKGROUND, highlightthickness=0,
                         bd=0)
        self._last_size: tuple[int, int] | None = None
        self.bind("<Configure>", self._on_configure)
        # Stars only ever actually get drawn in response to a real
        # <Configure> event — this widget has no size yet at
        # construction time (it's usually still an orphan, not yet
        # packed anywhere), so without this it sits as a plain dark
        # rectangle, with no stars at all, until Tk gets around to
        # laying it out and firing that event. On a screen that
        # otherwise looks almost identical to the one it's replacing
        # (see app.SpokeboundApp._show), that gap reads as a visible
        # flash rather than a seamless continuation. The toplevel is
        # already sized by this point (this app only ever shows full
        # screens filling an already-maximized window), so drawing
        # against its current size immediately is a safe guess — the
        # real <Configure> event, whenever it lands, corrects this if
        # it turns out to differ at all.
        root = parent.winfo_toplevel()
        width, height = root.winfo_width(), root.winfo_height()
        if width > 1 and height > 1:
            self._last_size = (width, height)
            draw_stars(self, make_stars(width, height))

    def _on_configure(self, event: tk.Event) -> None:
        size = (event.width, event.height)
        if size == self._last_size or size[0] <= 1 or size[1] <= 1:
            return
        self._last_size = size
        self.delete("all")
        draw_stars(self, make_stars(*size))


def add_starfield(parent: tk.Misc) -> tk.Canvas:
    """Add a starfield filling ``parent`` entirely and sitting behind
    everything else already in it (or added after) — call this first,
    before adding any other child, in a plain menu screen's own
    ``__init__``. Safe alongside children ``parent`` manages with
    ``pack`` or ``grid`` elsewhere, since this one manages itself with
    ``place`` instead and never contends with them for space.
    """
    background = _StarfieldCanvas(parent)
    background.place(x=0, y=0, relwidth=1, relheight=1)
    # Plain `background.lower()` would call Canvas's own `lower`, which
    # it overrides to mean "lower this canvas ITEM among its siblings"
    # (an alias for tag_lower) and requires a tagOrId — not what's
    # wanted here, which is to lower this WIDGET in its parent's own
    # stacking order. Calling Misc's version explicitly bypasses that
    # override.
    tk.Misc.lower(background)
    return background
