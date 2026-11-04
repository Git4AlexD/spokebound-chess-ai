"""Canvas that draws the board and reports clicked squares."""

import tkinter as tk
from collections.abc import Callable, Iterable

from spokebound.config import BOARD_COLS, BOARD_ROWS, GOAL_SQUARES
from spokebound.model.board import Board, Square, in_sanctuary
from spokebound.model.pieces import Player
from spokebound.ui import drawing, starfield, theme

# The single square every piece's own cockpit shading is lit toward
# (see BoardView.redraw) and where draw_sun is centred — GOAL_SQUARES
# is a one-element frozenset (config.py), so there's exactly one.
_SUN_SQUARE = next(iter(GOAL_SQUARES))

# Square size in pixels, scaled to fill the space it's given between these
# bounds (see BoardView._fit_square_size), so the board reads clearly in a
# small space without going tiny, and actually fills a big one on a large
# monitor instead of sitting small in a corner.
MIN_SQUARE_SIZE = 42
# High enough that a maximized window on a large or high-res monitor
# still has the board grow to fill it, rather than hitting a ceiling and
# leaving the rest of the window as unused background — by_width/
# by_height in _fit_square_size already bound this to whatever's
# actually available, so raising it only matters on a screen big enough
# to want it.
MAX_SQUARE_SIZE = 200

# The board shows one extra display row above row 0 and below the last
# row, for each side's single Captain square.
ROW_OFFSET = 1
DISPLAY_ROWS = BOARD_ROWS + 2 * ROW_OFFSET

# The board's own outer padx/pady plus the side panel's, on top of
# whatever exact width the panel itself reports. Trimmed to what the
# packing actually uses (see DeployScreen's own padx/pady on
# the board) plus a small margin, rather than a much larger flat
# allowance — the board is already fighting a tight pixel budget (nine
# display rows have to fit the window's own height), so every pixel of
# padding this doesn't actually need comes straight off how big the
# piece on each square, and its own outline, can be drawn.
OUTER_PADDING = 36


def available_board_size(widget: tk.Misc, panel_width: int) -> tuple[int, int]:
    """Return the (width, height) box left for the board in this window,
    once ``panel_width`` — the side panel's real, exact width — and the
    usual outer padding are set aside."""
    root = widget.winfo_toplevel()
    root.update_idletasks()
    width = root.winfo_width() - panel_width - OUTER_PADDING
    height = root.winfo_height() - OUTER_PADDING
    return max(1, width), max(1, height)


class BoardView(tk.Canvas):
    """Draws the board from Orange's side, with White at the top —
    unless ``flipped``, which mirrors both axes so the side that should
    be at the bottom of this screen is drawn there. DeployScreen flips
    it online (so each player sees their own side at the bottom) and in
    local two-player play (so the board faces whoever is moving).

    Sized to fill the ``max_width`` x ``max_height`` box it's given —
    scaled down to fit rather than clipped or scrolled, down to a
    legible floor (see MIN_SQUARE_SIZE).
    """

    def __init__(
        self,
        parent: tk.Misc,
        board: Board,
        on_click: Callable[[Square], None],
        max_width: int,
        max_height: int,
        flipped: bool = False,
    ) -> None:
        self.square_size = self._fit_square_size(max_width, max_height)
        width = self.square_size * BOARD_COLS
        height = self.square_size * DISPLAY_ROWS
        super().__init__(parent, width=width, height=height, bg=theme.BACKGROUND, highlightthickness=0)
        self._board = board
        self._on_click = on_click
        self._flipped = flipped
        self._stars = starfield.make_stars(width, height)
        self.bind("<Button-1>", self._handle_click)

    def set_flipped(self, flipped: bool) -> None:
        """Mirror the board on both axes, or put it back (see the class
        docstring). Takes effect on the next :meth:`redraw`."""
        self._flipped = flipped

    @staticmethod
    def _fit_square_size(max_width: int, max_height: int) -> int:
        """Return a square size that fills a ``max_width`` x ``max_height``
        box with the whole board."""
        by_width = max_width // BOARD_COLS
        by_height = max_height // DISPLAY_ROWS
        size = min(by_width, by_height)
        return max(MIN_SQUARE_SIZE, min(MAX_SQUARE_SIZE, size))

    def _handle_click(self, event: tk.Event) -> None:
        """Translate a click into a board square and report it."""
        display_row = int(event.y // self.square_size)
        display_col = int(event.x // self.square_size)
        if self._flipped:
            display_row = DISPLAY_ROWS - 1 - display_row
            display_col = BOARD_COLS - 1 - display_col
        self._on_click((display_row - ROW_OFFSET, display_col))

    def redraw(self, selected: Square | None = None, targets: Iterable[Square] = ()) -> None:
        """Redraw everything, marking the selection and its legal moves."""
        self.delete("all")
        self._draw_stars()
        targets = list(targets)
        for row in range(-ROW_OFFSET, BOARD_ROWS + ROW_OFFSET):
            for col in range(BOARD_COLS):
                square = (row, col)
                if self._board.in_bounds(square) or square in targets:
                    self._draw_square(square)
        drawing.draw_sun(self, self._centre(_SUN_SQUARE), self.square_size * 0.62)
        if selected is not None:
            # A dark halo under the bright ring — the board now spans
            # dark navy, bright cyan and gold squares, and no single
            # flat colour reads clearly against all three, so this
            # draws both: whichever one the square underneath doesn't
            # swallow is the one that shows.
            bounds = self._bounds(selected, inset=2)
            self.create_rectangle(*bounds, width=6, outline=theme.HIGHLIGHT_SHADOW)
            self.create_rectangle(*bounds, width=2, outline=theme.HIGHLIGHT)
        sun_centre = self._centre(_SUN_SQUARE)
        for player in Player:
            for square, piece in self._board.pieces(player):
                piece_centre = self._centre(square)
                sun_direction = (piece_centre[0] - sun_centre[0], piece_centre[1] - sun_centre[1])
                drawing.draw_star(
                    self,
                    piece_centre,
                    self.square_size * 0.42,
                    piece,
                    rotated=(player is Player.WHITE) != self._flipped,
                    sun_direction=sun_direction,
                )
        for square in targets:
            self._draw_target(square)

    def _draw_stars(self) -> None:
        """Draw the fixed background starfield (see starfield.make_stars)
        before anything else, so squares painted on top of it occlude
        every star except the ones sitting in a dead display cell."""
        starfield.draw_stars(self, self._stars)

    def _draw_square(self, square: Square) -> None:
        """Draw one square, highlighting the goal and sanctuary squares."""
        dark = bool(sum(square) % 2)
        if square in GOAL_SQUARES:
            colour = theme.GOAL_SQUARE
        else:
            owner = self._sanctuary_owner(square)
            if owner is None:
                colour = theme.SQUARE_DARK if dark else theme.SQUARE_LIGHT
            else:
                palette = theme.SANCTUARY_DARK if dark else theme.SANCTUARY_LIGHT
                colour = palette[owner]
        self.create_rectangle(*self._bounds(square), fill=colour, outline="")

    def _sanctuary_owner(self, square: Square) -> Player | None:
        """Return whose zone ``square`` is in, or None if it's open ground."""
        for player in Player:
            if in_sanctuary(square, player) or self._board.extra_squares.get(player) == square:
                return player
        return None

    def _draw_target(self, square: Square) -> None:
        """Mark a legal move: a ring for captures, a dot for empty squares.

        Same dark-halo-plus-bright-colour approach as the selection
        ring, for the same reason: it has to stay visible on any of the
        board's three square colours.
        """
        if self._board.get(square) is not None:
            bounds = self._bounds(square, inset=4)
            self.create_oval(*bounds, width=6, outline=theme.HIGHLIGHT_SHADOW)
            self.create_oval(*bounds, width=3, outline=theme.MOVE_MARK)
            return
        x, y = self._centre(square)
        r = self.square_size * 0.12
        self.create_oval(
            x - r, y - r, x + r, y + r, fill=theme.MOVE_MARK, outline=theme.HIGHLIGHT_SHADOW, width=2
        )

    def _display_position(self, square: Square) -> tuple[int, int]:
        """Return ``square``'s (row, col) in on-screen display terms —
        row 0 at the very top, mirrored on both axes when ``flipped``."""
        row, col = square
        display_row = row + ROW_OFFSET
        display_col = col
        if self._flipped:
            display_row = DISPLAY_ROWS - 1 - display_row
            display_col = BOARD_COLS - 1 - display_col
        return display_row, display_col

    def _bounds(self, square: Square, inset: int = 0) -> tuple[int, int, int, int]:
        """Return the pixel rectangle of ``square``, shrunk by ``inset``."""
        display_row, display_col = self._display_position(square)
        left = display_col * self.square_size
        top = display_row * self.square_size
        return (left + inset, top + inset, left + self.square_size - inset, top + self.square_size - inset)

    def _centre(self, square: Square) -> tuple[float, float]:
        """Return the pixel centre of ``square``."""
        display_row, display_col = self._display_position(square)
        return ((display_col + 0.5) * self.square_size, (display_row + 0.5) * self.square_size)
