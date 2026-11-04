"""Board storage and move generation."""

from collections.abc import Iterator

from spokebound.config import BOARD_COLS, BOARD_ROWS, SANCTUARY_DEPTH
from spokebound.model.pieces import SPOKE_COUNT, Piece, Player, board_delta

Square = tuple[int, int]

# Row 0 is White's edge and row BOARD_ROWS - 1 is Orange's, so each
# player's sanctuary is the band of rows nearest their own edge, where
# the built fleet (not the Captain) is deployed.
SANCTUARY_ROWS = {
    Player.WHITE: range(SANCTUARY_DEPTH),
    Player.ORANGE: range(BOARD_ROWS - SANCTUARY_DEPTH, BOARD_ROWS),
}


def in_sanctuary(square: Square, owner: Player) -> bool:
    """Return True if ``square`` lies inside ``owner``'s own sanctuary."""
    return square[0] in SANCTUARY_ROWS[owner]


def sanctuary_squares(owner: Player) -> Iterator[Square]:
    """Yield every square in ``owner``'s sanctuary."""
    for row in SANCTUARY_ROWS[owner]:
        for col in range(BOARD_COLS):
            yield row, col


class Board:
    """A grid of pieces keyed by ``(row, col)``.

    Each player may also have one extra square, one row beyond their own
    edge, added by :meth:`add_extra_square` for their Captain to start on.
    """

    def __init__(self) -> None:
        self._grid: dict[Square, Piece] = {}
        self.extra_squares: dict[Player, Square] = {}

    def add_extra_square(self, owner: Player, square: Square) -> None:
        """Register ``square`` as ``owner``'s extra, Captain-only square."""
        self.extra_squares[owner] = square

    def in_bounds(self, square: Square) -> bool:
        """Return True if ``square`` lies on the board."""
        row, col = square
        if 0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS:
            return True
        return square in self.extra_squares.values()

    def get(self, square: Square) -> Piece | None:
        """Return the piece on ``square``, if any."""
        return self._grid.get(square)

    def place(self, square: Square, piece: Piece) -> None:
        """Put ``piece`` on an empty ``square``."""
        if square in self._grid:
            raise ValueError(f"Square {square} is already occupied")
        self._grid[square] = piece

    def remove(self, square: Square) -> Piece | None:
        """Take the piece off ``square``, if any, and return it — the
        undo half of :meth:`place`, e.g. for trying a placement and
        putting it back (see spokebound.ai.deploy)."""
        return self._grid.pop(square, None)

    def move(self, src: Square, dst: Square) -> Piece | None:
        """Move the piece on ``src`` to ``dst`` and return any capture."""
        piece = self._grid.pop(src)
        captured = self._grid.pop(dst, None)
        self._grid[dst] = piece
        return captured

    def pieces(self, player: Player) -> Iterator[tuple[Square, Piece]]:
        """Yield ``(square, piece)`` for every piece ``player`` owns."""
        for square, piece in list(self._grid.items()):
            if piece.owner is player:
                yield square, piece

    def legal_moves(self, src: Square) -> list[Square]:
        """Return every square the piece on ``src`` can move to.

        This ignores whether the move would leave the mover's own
        Captain attacked; :class:`~spokebound.model.game.Game` filters
        that in separately, since it also needs these unfiltered
        (pseudo-legal) moves to work out which squares are attacked.
        """
        piece = self._grid.get(src)
        if piece is None:
            return []
        moves: list[Square] = []
        for spoke in range(SPOKE_COUNT):
            moves.extend(self._ray(src, piece, spoke))
        return moves

    def is_attacked(self, target: Square, by_player: Player) -> bool:
        """Return True if any of ``by_player``'s pieces can reach ``target``.

        Same answer as ``target in`` every piece's :meth:`legal_moves`.
        """
        occupant = self._grid.get(target)
        if occupant is not None and occupant.owner is by_player:
            return False
        for spoke in range(SPOKE_COUNT):
            d_row, d_col = board_delta(spoke, by_player)
            row, col = target
            distance = 0
            while True:
                row -= d_row
                col -= d_col
                distance += 1
                square = (row, col)
                if not self.in_bounds(square):
                    break
                occupant = self._grid.get(square)
                if occupant is None:
                    continue
                if occupant.owner is by_player:
                    reach = occupant.reach(spoke)
                    if reach is None or distance <= reach:
                        return True
                break
        return False

    def _ray(self, src: Square, piece: Piece, spoke: int) -> Iterator[Square]:
        """Yield squares reachable along one spoke.

        Movement stops at the board edge or the first piece in the way;
        an enemy piece in the way can be captured.
        """
        reach = piece.reach(spoke)
        d_row, d_col = board_delta(spoke, piece.owner)
        square = src
        steps = 0
        while reach is None or steps < reach:
            square = (square[0] + d_row, square[1] + d_col)
            steps += 1
            row, col = square
            if not (0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS) and not self.in_bounds(square):
                return
            occupant = self._grid.get(square)
            if occupant is None:
                yield square
                continue
            if occupant.owner is not piece.owner:
                yield square
            return
