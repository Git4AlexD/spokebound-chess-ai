"""Side panel listing both full fleets; a lost-piece tracker once battle
starts, since a captured piece just fades and gets crossed out in place."""

import math
import tkinter as tk

from spokebound.model.board import Board
from spokebound.model.pieces import Piece, Player
from spokebound.ui import drawing, theme

THUMB_SIZE = 90
THUMB_GAP = 10
ROW_GAP = 10
NUMBER_HEIGHT = 16
LABEL_PADY = (8, 3)
# A raised card surface, one step lighter than theme.PANEL, instead of
# the plain white this used to be — a stray white rectangle would break
# the dark chrome everywhere else on screen.
CARD_FILL = "#1D3E5C"
CARD_OUTLINE = theme.DISABLED


class FleetPanel(tk.Frame):
    """Shows each side's full fleet, in build order, Captain last — a
    small number under each piece marks that order, so it's clear which
    one is placed first, second, and so on. Wrapped over two rows (not
    one long one) so each piece can be drawn at a readable size.

    ``track_losses`` is on by default: a piece no longer found on the
    board (captured) fades and gets crossed out. During deployment
    that's not yet meaningful — an unplaced piece isn't a lost one — so
    :class:`~spokebound.ui.deploy_screen.DeployScreen` turns it off and
    instead sets ``next_index`` to ring whichever piece is up next; the
    same panel instance just flips both back once play begins, rather
    than being rebuilt.

    ``thumb_size`` defaults to a comfortable size but can be scaled down
    by a screen that's fitting its whole layout to a smaller window.
    """

    def __init__(
        self,
        parent: tk.Misc,
        rosters: dict[Player, list[Piece]],
        board: Board,
        track_losses: bool = True,
        thumb_size: int = THUMB_SIZE,
        next_index: dict[Player, int] | None = None,
    ) -> None:
        super().__init__(parent, bg=theme.PANEL)
        self._rosters = rosters
        self._board = board
        # Both public: a screen whose phase changes over time (deploy
        # -> play) flips track_losses and clears next_index directly,
        # on the same panel instance, rather than rebuilding it; one
        # whose "next to place" piece changes (deployment itself)
        # updates next_index the same way — either way, just set the
        # attribute and call redraw().
        self.track_losses = track_losses
        self.next_index = next_index
        self._thumb_size = thumb_size
        self._rows: dict[Player, tk.Canvas] = {}
        self._labels: dict[Player, tk.Label] = {}
        for player in Player:
            label = theme.make_label(
                self, f"{player.label} Fleet", theme.FONT_BODY, fg=theme.PLAYER_TEXT[player], bg=theme.PANEL
            )
            label.pack(anchor=tk.W, pady=LABEL_PADY)
            self._labels[player] = label
            count = len(rosters[player])
            columns = self._columns(count)
            row_count = math.ceil(count / columns) if columns else 1
            cell_height = thumb_size + 4 + NUMBER_HEIGHT
            width = columns * (thumb_size + THUMB_GAP) - THUMB_GAP
            height = row_count * cell_height + (row_count - 1) * ROW_GAP
            canvas = tk.Canvas(self, width=width, height=height, bg=theme.PANEL, highlightthickness=0)
            canvas.pack(anchor=tk.W)
            self._rows[player] = canvas
        # Not drawn here: every real call site (DeployScreen's own
        # _refresh, right after _rebuild) already redraws this
        # immediately afterwards regardless, and each canvas's own size
        # above is fixed independently of what's actually drawn inside
        # it — so an eager draw here would only ever be thrown away
        # unseen on fit_height's own throwaway probe builds (which
        # measure this panel's size, then discard it), wasting real
        # time on full piece artwork nothing ever shows.

    @staticmethod
    def _columns(count: int) -> int:
        """Return how many pieces wide the grid should be, at most two
        rows deep, so each piece stays a readable size."""
        return max(1, math.ceil(count / 2))

    def row_width(self, player: Player) -> int:
        """Return one row's pixel width for ``player``'s fleet grid, so
        another panel can be sized to visually match it."""
        columns = self._columns(len(self._rosters[player]))
        return columns * (self._thumb_size + THUMB_GAP) - THUMB_GAP

    def height_to_first_row(self, player: Player) -> int:
        """Return the distance, from this panel's own top, down to the
        bottom of ``player``'s first row of thumbnails — so another panel
        can be sized to align with just that row rather than the whole
        (possibly two-row) grid.

        Built from each section's own requested size (``winfo_reqheight``)
        rather than its resolved on-screen position (``winfo_y``): this
        runs while the panel is still being assembled, before it (or its
        ancestors) have been packed anywhere, and a widget's position
        within its master isn't settled until that master itself has been
        arranged by its own master, all the way up — its requested size
        is, since that's computed bottom-up from children alone.
        """
        cell_height = self._thumb_size + 4 + NUMBER_HEIGHT
        total = 0
        for p in Player:
            total += self._labels[p].winfo_reqheight() + sum(LABEL_PADY)
            if p == player:
                return total + cell_height
            total += self._rows[p].winfo_reqheight()
        raise ValueError(f"{player!r} isn't in this panel")

    def redraw(self) -> None:
        """Redraw both rosters: order numbers always, crossing out any
        piece no longer on the board once losses are tracked, and
        ringing whichever piece is next to place while they aren't."""
        size = self._thumb_size
        cell_height = size + 4 + NUMBER_HEIGHT
        for player, canvas in self._rows.items():
            canvas.delete("all")
            roster = self._rosters[player]
            columns = self._columns(len(roster))
            alive = {id(piece) for _, piece in self._board.pieces(player)} if self.track_losses else None
            next_index = self.next_index.get(player) if self.next_index else None
            for index, piece in enumerate(roster):
                col, grid_row = index % columns, index // columns
                left = col * (size + THUMB_GAP)
                top = grid_row * (cell_height + ROW_GAP)
                is_next = index == next_index
                # A plain card behind each piece keeps the shapes reading
                # cleanly against the panel, and gives lost pieces a flat,
                # neutral backdrop instead of the board's own colours.
                outline = theme.ACCENT if is_next else CARD_OUTLINE
                width = 3 if is_next else 1
                canvas.create_rectangle(
                    left, top + 2, left + size, top + size + 2, fill=CARD_FILL, outline=outline, width=width
                )
                centre = (left + size / 2, top + size / 2 + 2)
                lost = alive is not None and id(piece) not in alive
                # Always upright, regardless of owner: this is a list to
                # read (order numbers, which piece is next, what's been
                # lost), not the board itself — rotating White's half
                # the way the actual board does (see BoardView) just
                # makes half the tracker awkward to read for no benefit
                # on a single shared screen.
                drawing.draw_star(canvas, centre, size * 0.42, piece, rotated=False, lost=lost)
                canvas.create_text(
                    left + size / 2,
                    top + size + 4 + NUMBER_HEIGHT / 2,
                    text=str(index + 1),
                    font=theme.FONT_SMALL,
                    fill=(theme.ACCENT_DARK if is_next else theme.MUTED_TEXT),
                )
