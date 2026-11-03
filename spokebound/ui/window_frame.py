"""A riveted metal window frame around the board, so the board itself
reads as something seen through a ship's own viewport rather than a
flat panel sitting on the page."""

import tkinter as tk
from collections.abc import Callable

from spokebound.model.board import Board, Square
from spokebound.ui import starfield, theme
from spokebound.ui.board_view import BoardView

# How thick the frame is, in pixels, and how many stepped bands it's
# built from — a plain linear gradient Tk can't paint, so this fakes
# one as a handful of flat, progressively lighter rectangles nested
# inside each other (the same banding trick drawing.py's own pieces
# use), reading as a bevel catching the light toward the glass.
BORDER = 28
BANDS = 6
# The bright "seal" line right at the glass's own edge, and the rivets
# at each corner, both fractions of BORDER.
SEAL_INSET_FRACTION = 0.3
RIVET_RADIUS_FRACTION = 0.22


def create_window_board(parent: tk.Misc, board: Board,
                        on_click: Callable[[Square], None],
                        max_width: int, max_height: int,
                        flipped: bool = False,
                        border: int = BORDER) -> tuple[tk.Canvas, BoardView]:
    """Return (frame_canvas, board_view): a BoardView sized to fit
    within ``max_width`` x ``max_height`` once ``border`` is set aside
    on every side for the frame, embedded in a canvas that draws the
    frame itself around it. Pack ``frame_canvas``, not ``board_view``
    directly — board_view is just along for the ride, embedded via
    ``create_window``, so every other BoardView method (set_flipped,
    redraw) still works exactly as before.

    The frame itself always claims the full ``max_width`` x
    ``max_height`` it's given, even though board_view's own size is
    usually capped by ``max_height`` alone (its squares have to stay
    legible, not fill a wide window sideways) and so is often narrower
    than that. board_view sits centred in whatever width that leaves,
    with real starry sky — not just more of the frame's own flat
    background — filling the gap either side of it, read as more of
    space itself showing through the rest of this same window rather
    than a border around a smaller, separate picture.
    """
    inner_w = max(1, max_width - 2 * border)
    inner_h = max(1, max_height - 2 * border)
    frame_canvas = tk.Canvas(parent, bg=theme.BACKGROUND,
                             highlightthickness=0)
    board_view = BoardView(frame_canvas, board, on_click, inner_w, inner_h,
                           flipped=flipped)
    frame_canvas.update_idletasks()
    board_w = board_view.winfo_reqwidth()
    board_h = board_view.winfo_reqheight()
    width = max(max_width, board_w + 2 * border)
    height = max(max_height, board_h + 2 * border)
    frame_canvas.configure(width=width, height=height)
    inner_w, inner_h = width - 2 * border, height - 2 * border
    _draw_frame(frame_canvas, width, height, border)
    # _draw_frame's own bands are solid rectangles, not rings — each
    # one is only ever *read* as a thin step because the next, smaller
    # one sits on top of its middle — so the innermost (lightest) band
    # actually fills this whole inner area, not just a sliver near its
    # own edge. board_view itself (an embedded *window*, always
    # rendered above any plain drawn shape regardless of creation
    # order) used to cover that completely, every time, since it used
    # to fill the whole inner area with no slack to speak of — this
    # repaints the true inner area back to the real starfield
    # background first, erasing that leftover band colour, so the
    # stars below have the right backdrop behind them wherever
    # board_view itself doesn't reach any more.
    frame_canvas.create_rectangle(border, border, border + inner_w,
                                  border + inner_h, fill=theme.BACKGROUND,
                                  outline="")
    if inner_w > board_w or inner_h > board_h:
        _draw_inner_stars(frame_canvas, inner_w, inner_h, border)
    board_x = border + (inner_w - board_w) // 2
    board_y = border + (inner_h - board_h) // 2
    frame_canvas.create_window(board_x, board_y, anchor="nw",
                               window=board_view)
    return frame_canvas, board_view


def _draw_inner_stars(canvas: tk.Canvas, inner_w: int, inner_h: int,
                      border: int) -> None:
    """Fill the whole inner (behind-the-glass) area with a starfield,
    offset by ``border`` so it lines up with that area's own top-left
    corner rather than the canvas's own (which the frame itself still
    occupies) — see :func:`create_window_board`."""
    for x, y, r, colour, sparkle in starfield.make_stars(inner_w, inner_h):
        cx, cy = x + border, y + border
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=colour,
                           outline="")
        if sparkle:
            span = r * 2.6
            canvas.create_line(cx - span, cy, cx + span, cy, fill=colour,
                               width=1)
            canvas.create_line(cx, cy - span, cx, cy + span, fill=colour,
                               width=1)


def _draw_frame(canvas: tk.Canvas, width: int, height: int,
                border: int) -> None:
    """Draw the riveted metal bevel itself."""
    for i in range(BANDS):
        inset = border * i / BANDS
        colour = theme.mix_hex(theme.WINDOW_FRAME_DARK,
                               theme.WINDOW_FRAME_LIGHT, i / (BANDS - 1))
        canvas.create_rectangle(inset, inset, width - inset, height - inset,
                                fill=colour, outline="")
    seal = border * SEAL_INSET_FRACTION
    canvas.create_rectangle(border - seal, border - seal,
                            width - border + seal, height - border + seal,
                            outline=theme.PIECE_RING, width=2)

    rivet_r = max(3, border * RIVET_RADIUS_FRACTION)
    half = border * 0.5
    for x in (half, width - half):
        for y in (half, height - half):
            canvas.create_oval(x - rivet_r, y - rivet_r, x + rivet_r,
                               y + rivet_r, fill=theme.WINDOW_FRAME_RIVET,
                               outline=theme.WINDOW_FRAME_DARK)
            hr = rivet_r * 0.4
            hx, hy = x - rivet_r * 0.3, y - rivet_r * 0.3
            canvas.create_oval(hx - hr, hy - hr, hx + hr, hy + hr,
                               fill=theme.WINDOW_FRAME_RIVET_HIGHLIGHT,
                               outline="")
