"""A sci-fi computer-terminal shell: an '80s console casing — a
stepped bezel shading darker toward the glass so the screen reads as
recessed into it, a column of chunky non-functional buttons and a
speaker grille running the full height down the screen's left side,
and an orange-and-grey keyboard beneath it (the console look this
project's reference art uses) — wrapped around another panel's
existing content rather than restyling it. See build_shell."""

import math
import tkinter as tk

from spokebound.ui import theme

BEZEL_PADDING = 10

# The casing itself: nested frames, each inset by CASING_STEP px,
# stepping from a lit outer shell colour (the ``bezel`` frame itself)
# down to theme.TERMINAL_BEZEL right at the glass — the opposite
# direction from window_frame.py's viewport bevel (which brightens
# toward the glass, like a glowing rim): this one darkens toward it
# instead, so the screen reads as sunk into the console rather than
# lit from within. Chunky steps (not a thin sliver) plus a bright seam
# right at the glass's own edge are what actually sell "moulded plastic
# casing" rather than "a rectangle with a border."
CASING_BANDS = 4
CASING_STEP = 7
CASING_INSET = (CASING_BANDS - 1) * 2 * CASING_STEP
CASING_SEAM = theme.mix_hex(theme.TERMINAL_CASE_OUTER, "#FFFFFF", 0.35)

# The left-hand sidebar: BUTTON_SET_COUNT tight clusters of
# BUTTONS_PER_SET keys each (a fixed small gap within a cluster),
# spread out via equal expand slots so the sets together — not any one
# key — fill the whole height beside the screen, with a round speaker
# grille pinned at the very bottom, right before the keyboard begins.
# Looks-only: nothing behind any of it responds to a click.
SIDEBAR_WIDTH = 30
SIDEBAR_GAP = BEZEL_PADDING
BUTTON_SET_COUNT = 4
BUTTONS_PER_SET = 3
BUTTON_HEIGHT = 14
BUTTON_GAP = 4
SPEAKER_RADIUS = 13
SPEAKER_HOLE_RADIUS = 1.4
SPEAKER_HOLE_RINGS = (0, 6, 10.5)
SPEAKER_HOLES_PER_RING = (1, 6, 10)

# The decorative keyboard beneath the screen: KEYBOARD_ROWS of small
# keys, each KEYBOARD_KEY_SIZE square with a KEYBOARD_KEY_GAP gap,
# however many columns actually fit the width it's given.
KEYBOARD_ROWS = 4
KEYBOARD_KEY_SIZE = 16
KEYBOARD_KEY_GAP = 3
KEYBOARD_MARGIN = 8


def build_shell(parent: tk.Misc, width: int) -> tuple[tk.Frame, tk.Frame]:
    """Return (bezel, screen): the full console casing — recessed
    screen (with its own side buttons/speaker) above a decorative
    keyboard, sized to ``width``. Pack whatever the caller would
    otherwise have packed straight into ``parent`` into ``screen``
    instead, and pack ``bezel`` (not ``screen``) into ``parent``.
    ``screen`` carries the same colour as the innermost casing band,
    just so any sliver of it still showing around the content packed
    inside blends into the housing rather than clashing with it —
    that content's own background is what actually reads as the
    screen.
    """
    bezel = tk.Frame(parent, bg=theme.TERMINAL_CASE_OUTER,
                     highlightthickness=2,
                     highlightbackground=theme.TERMINAL_BEZEL_EDGE)
    # Packed before the casing bands below (which claim the rest of
    # this frame with expand=True), so the keyboard keeps its own
    # natural height instead of being squeezed by whatever's above it.
    _build_keyboard(bezel, width).pack(side=tk.BOTTOM, fill=tk.X,
                                       padx=CASING_STEP,
                                       pady=(0, CASING_STEP))

    band = bezel
    for i in range(1, CASING_BANDS):
        t = i / (CASING_BANDS - 1)
        colour = theme.mix_hex(theme.TERMINAL_CASE_OUTER,
                               theme.TERMINAL_BEZEL, t)
        next_band = tk.Frame(band, bg=colour)
        next_band.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                       padx=CASING_STEP, pady=CASING_STEP)
        band = next_band
    # ``band`` is now the innermost casing layer, right at the glass —
    # everything below sits on that, not on the outer shell colour. A
    # bright seam right here, at the actual edge of the glass, is what
    # reads as a crisp machined edge rather than just a colour fade.
    inner_bg = band.cget("bg")
    band.configure(padx=BEZEL_PADDING, pady=BEZEL_PADDING,
                   highlightthickness=1, highlightbackground=CASING_SEAM)

    row = tk.Frame(band, bg=inner_bg)
    row.pack(fill=tk.BOTH, expand=True)
    _build_sidebar(row, inner_bg).pack(side=tk.LEFT, fill=tk.Y,
                                       padx=(0, SIDEBAR_GAP))

    screen = tk.Frame(row, bg=theme.TERMINAL_BEZEL)
    screen.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    return bezel, screen


def _build_sidebar(parent: tk.Misc, bg: str) -> tk.Frame:
    """Return a column holding BUTTON_SET_COUNT tight clusters of
    BUTTONS_PER_SET keys, spread apart to fill the whole height beside
    the screen, with a round speaker grille pinned at the very bottom
    — right before the keyboard starts, not part of the spread-out
    sets above it. Purely decorative: nothing behind any of it
    responds to a click."""
    sidebar = tk.Frame(parent, bg=bg, width=SIDEBAR_WIDTH)
    # Packed first, with side=tk.BOTTOM, so it claims its own space at
    # the sidebar's foot — the button sets below, packed next with
    # side=tk.TOP, only ever divide up whatever's left above it.
    speaker = tk.Canvas(sidebar, width=SIDEBAR_WIDTH,
                        height=SPEAKER_RADIUS * 2 + 4,
                        bg=bg, highlightthickness=0)
    speaker.pack(side=tk.BOTTOM, pady=(0, BEZEL_PADDING))
    _draw_speaker(speaker, SIDEBAR_WIDTH / 2, SPEAKER_RADIUS + 2)

    for _ in range(BUTTON_SET_COUNT):
        # expand=True on this group frame, not on the keys inside it —
        # that's what keeps each set a tight, fixed-gap cluster while
        # the sets collectively still divide up the full height evenly.
        group = tk.Frame(sidebar, bg=bg)
        group.pack(side=tk.TOP, expand=True)
        for i in range(BUTTONS_PER_SET):
            key = tk.Canvas(group, width=SIDEBAR_WIDTH, height=BUTTON_HEIGHT,
                            bg=bg, highlightthickness=0)
            key.pack(side=tk.TOP, pady=(0 if i == 0 else BUTTON_GAP, 0))
            key.create_rectangle(1, 1, SIDEBAR_WIDTH - 1, BUTTON_HEIGHT - 1,
                                 fill=theme.TERMINAL_BUTTON,
                                 outline=theme.TERMINAL_BUTTON_EDGE)
            key.create_line(2, 2, SIDEBAR_WIDTH - 2, 2,
                            fill=theme.TERMINAL_BUTTON_HIGHLIGHT)
    return sidebar


def _draw_speaker(canvas: tk.Canvas, cx: float, cy: float) -> None:
    """Draw a small perforated-metal speaker grille centred at
    (cx, cy): a flat disc with a few concentric rings of drilled
    holes, darker than the disc itself."""
    canvas.create_oval(cx - SPEAKER_RADIUS, cy - SPEAKER_RADIUS,
                       cx + SPEAKER_RADIUS, cy + SPEAKER_RADIUS,
                       fill=theme.TERMINAL_CASE_OUTER,
                       outline=theme.TERMINAL_BEZEL_EDGE)
    for ring_radius, hole_count in zip(SPEAKER_HOLE_RINGS,
                                       SPEAKER_HOLES_PER_RING):
        for h in range(hole_count):
            angle = 2 * math.pi * h / max(1, hole_count)
            hx = cx + ring_radius * math.cos(angle)
            hy = cy + ring_radius * math.sin(angle)
            canvas.create_oval(hx - SPEAKER_HOLE_RADIUS,
                               hy - SPEAKER_HOLE_RADIUS,
                               hx + SPEAKER_HOLE_RADIUS,
                               hy + SPEAKER_HOLE_RADIUS,
                               fill=theme.TERMINAL_BEZEL, outline="")


def _build_keyboard(parent: tk.Misc, width: int) -> tk.Canvas:
    """Return a canvas drawing KEYBOARD_ROWS rows of small keys across
    ``width`` — orange and grey, looks-only, nothing behind any key
    responds to a click. However many columns actually fit ``width``
    are drawn, so this always spans the casing cleanly rather than
    overflowing or leaving a ragged gap at one edge."""
    step = KEYBOARD_KEY_SIZE + KEYBOARD_KEY_GAP
    cols = max(1, (width - 2 * KEYBOARD_MARGIN + KEYBOARD_KEY_GAP) // step)
    used_width = cols * step - KEYBOARD_KEY_GAP
    left0 = (width - used_width) / 2
    height = KEYBOARD_ROWS * step - KEYBOARD_KEY_GAP + 2 * KEYBOARD_MARGIN
    canvas = tk.Canvas(parent, width=width, height=height,
                       bg=theme.TERMINAL_CASE_OUTER, highlightthickness=0)
    for row in range(KEYBOARD_ROWS):
        top = KEYBOARD_MARGIN + row * step
        for col in range(cols):
            left = left0 + col * step
            # A scattered minority of orange keys among the grey ones —
            # the same two-tone texture the reference keyboard uses —
            # rather than an exact key-by-key copy of its layout.
            orange = (col == 0 or col == cols - 1
                     or (row == 0 and col % 3 == 0))
            fill, edge = ((theme.TERMINAL_BUTTON, theme.TERMINAL_BUTTON_EDGE)
                         if orange else
                         (theme.KEYBOARD_KEY, theme.KEYBOARD_KEY_EDGE))
            canvas.create_rectangle(left, top, left + KEYBOARD_KEY_SIZE,
                                    top + KEYBOARD_KEY_SIZE,
                                    fill=fill, outline=edge)
            canvas.create_line(left + 1, top + 1,
                               left + KEYBOARD_KEY_SIZE - 1, top + 1,
                               fill=theme.TERMINAL_BUTTON_HIGHLIGHT
                               if orange else theme.KEYBOARD_KEY_HIGHLIGHT)
    return canvas
