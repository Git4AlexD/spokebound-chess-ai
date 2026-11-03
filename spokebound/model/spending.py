"""Spending points on pieces: the build phase and in-game upgrades."""

from spokebound.config import (
    FLEET_SIZE, BUILD_BUDGET, LEVEL_COSTS, MIN_PIECE_COST, PIECE_CAP,
)
from spokebound.model.pieces import Piece, Player


class FleetBuilder:
    """Holds one player's fleet while they spend their build budget."""

    def __init__(self, owner: Player) -> None:
        self.owner = owner
        self.pieces = [Piece(owner) for _ in range(FLEET_SIZE)]

    @property
    def remaining(self) -> int:
        """Return the unspent part of the build budget."""
        return BUILD_BUDGET - sum(piece.cost for piece in self.pieces)

    def adjust(self, index: int, spoke: int, step: int) -> bool:
        """Change one spoke of piece ``index``; return True if accepted."""
        piece = self.pieces[index]
        return piece.try_adjust(spoke, step, self.remaining) is not None

    def load_preset(self, fleet: list[list[int]]) -> None:
        """Replace every piece's spokes with a preset fleet's, wholesale.

        The player can still freely tweak every piece afterwards.
        """
        if len(fleet) != len(self.pieces):
            raise ValueError("Preset has the wrong number of pieces")
        for piece in fleet:
            cost = sum(LEVEL_COSTS[level] for level in piece)
            if not 0 <= cost <= PIECE_CAP:
                raise ValueError(f"Preset piece costs {cost}, over the cap")
        if sum(sum(LEVEL_COSTS[level] for level in piece)
              for piece in fleet) > BUILD_BUDGET:
            raise ValueError("Preset costs more than the build budget")
        for piece, levels in zip(self.pieces, fleet):
            piece.spokes = list(levels)

    def problems(self) -> list[str]:
        """Return reasons the fleet can't be locked in yet (empty if valid)."""
        weak = [str(i + 1) for i, piece in enumerate(self.pieces)
                if piece.cost < MIN_PIECE_COST]
        if not weak:
            return []
        return [f"Piece {', '.join(weak)} needs at least "
                f"{MIN_PIECE_COST} point to move."]


class PendingUpgrade:
    """Bonus points being spent on one piece after a bounty or promotion.

    Spokes can be raised while points remain, and lowered back to (but not
    below) their level when the upgrade began. Unspent points are lost.
    """

    def __init__(self, piece: Piece, points: int) -> None:
        self.piece = piece
        self.points = points
        self._floors = list(piece.spokes)

    def adjust(self, spoke: int, step: int) -> bool:
        """Change one spoke of the upgrading piece; return True if accepted."""
        spent = self.piece.try_adjust(
            spoke, step, self.points, floor=self._floors[spoke])
        if spent is None:
            return False
        self.points -= spent
        return True
