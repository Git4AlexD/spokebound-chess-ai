"""Turn-by-turn placement of each side's built fleet onto the board."""

from spokebound.config import BOARD_ROWS, CAPTAIN_COLUMN
from spokebound.model.board import Board, Square, sanctuary_squares
from spokebound.model.game import assign_bounties
from spokebound.model.pieces import Piece, Player, make_captain


def _bounty_first(fleet: list[Piece]) -> list[Piece]:
    """Return ``fleet`` reordered so its bounty pieces (highest first)
    deploy before the rest — the same convention for both sides, so
    which pieces go down first is decided by their value, not by
    whatever order they happened to be built or listed in. A stable
    sort, so the non-bounty pieces keep their original relative order
    behind them."""
    return sorted(fleet, key=lambda piece: -piece.bounty)


class Deployment:
    """Alternates letting each side place a built piece in their sanctuary.

    Both Captains are placed automatically, fixed to the centre column
    behind their side's sanctuary, before either player places anything.
    Orange then places first, matching who moves first once play begins,
    so the second mover (White) places last.
    """

    def __init__(self, orange_fleet: list[Piece],
                 white_fleet: list[Piece]) -> None:
        self.board = Board()
        self.current = Player.ORANGE
        for fleet in (orange_fleet, white_fleet):
            assign_bounties(fleet)
        self._fleets = {Player.ORANGE: _bounty_first(orange_fleet),
                        Player.WHITE: _bounty_first(white_fleet)}
        self._placed = {Player.ORANGE: 0, Player.WHITE: 0}
        self.captains = {
            Player.ORANGE: make_captain(Player.ORANGE),
            Player.WHITE: make_captain(Player.WHITE),
        }
        for player, captain in self.captains.items():
            square = self._captain_square(player)
            self.board.add_extra_square(player, square)
            self.board.place(square, captain)

    @staticmethod
    def _captain_square(player: Player) -> Square:
        """Return the fixed, centre-column square behind ``player``'s
        sanctuary that their Captain starts on."""
        row = -1 if player is Player.WHITE else BOARD_ROWS
        return (row, CAPTAIN_COLUMN)

    def roster(self, player: Player) -> list[Piece]:
        """Return ``player``'s full fleet, built pieces then the Captain."""
        return [*self._fleets[player], self.captains[player]]

    @property
    def is_done(self) -> bool:
        """Return True once both built fleets are placed."""
        return all(self._placed[p] >= len(self._fleets[p]) for p in Player)

    def next_piece(self, player: Player) -> Piece | None:
        """Return the next unplaced piece for ``player``, if any."""
        fleet = self._fleets[player]
        index = self._placed[player]
        return fleet[index] if index < len(fleet) else None

    def placed_count(self, player: Player) -> int:
        """Return how many of ``player``'s pieces have been placed."""
        return self._placed[player]

    def fleet_size(self, player: Player) -> int:
        """Return the number of built pieces ``player`` is deploying."""
        return len(self._fleets[player])

    def legal_squares(self) -> list[Square]:
        """Return the empty squares in the current player's sanctuary."""
        if self.is_done:
            return []
        return [sq for sq in sanctuary_squares(self.current)
               if self.board.get(sq) is None]

    def place(self, square: Square) -> None:
        """Deploy the current player's next piece to ``square``."""
        if square not in self.legal_squares():
            raise ValueError(f"Can't deploy to {square}")
        self.board.place(square, self.next_piece(self.current))
        self._placed[self.current] += 1
        if not self.is_done:
            self.current = self.current.opponent
