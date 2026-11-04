"""Players, spoke directions and pieces."""

from dataclasses import dataclass, field
from enum import IntEnum

from spokebound.config import CAPTAIN_REACH, LEVEL_COSTS, PIECE_CAP, UNLIMITED


class Player(IntEnum):
    """The two sides. Orange starts at the bottom and moves first."""

    ORANGE = 0
    WHITE = 1

    @property
    def opponent(self) -> "Player":
        """Return the other player."""
        return Player(1 - self)

    @property
    def label(self) -> str:
        """Return a display name such as ``'Orange'``.

        WHITE displays as "Blue" — the side's own colour scheme moved
        from white to blue, but the enum member itself stays WHITE
        throughout the model/AI layers rather than a project-wide
        rename, since nothing there depends on the display name.
        """
        return "Blue" if self is Player.WHITE else self.name.capitalize()


# Spokes in clockwise order from the owner's point of view. "N" is always
# forward, towards the opponent.
DIRECTION_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
SPOKE_COUNT = len(DIRECTION_NAMES)

# Board steps as (row delta, col delta) for Orange, who faces up the screen.
_ORANGE_DELTAS = (
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, -1),
)


def board_delta(spoke: int, owner: Player) -> tuple[int, int]:
    """Return the board step for ``spoke`` as seen by ``owner``.

    White sits opposite Orange, so its directions are rotated 180 degrees.
    """
    d_row, d_col = _ORANGE_DELTAS[spoke]
    if owner is Player.WHITE:
        return -d_row, -d_col
    return d_row, d_col


@dataclass
class Piece:
    """A piece whose movement is defined by eight spoke range levels."""

    owner: Player
    spokes: list[int] = field(default_factory=lambda: [0] * SPOKE_COUNT)
    bounty: int = 0
    promoted: bool = False
    is_captain: bool = False

    @property
    def cost(self) -> int:
        """Return the total points spent on this piece's spokes.

        The Captain is free: it never counts against the build budget,
        never carries a bounty, and never contributes to either side's
        score at the turn limit.
        """
        if self.is_captain:
            return 0
        return sum(LEVEL_COSTS[level] for level in self.spokes)

    def reach(self, spoke: int) -> int | None:
        """Return the max squares along ``spoke``, or ``None`` if unlimited."""
        level = self.spokes[spoke]
        return None if level == UNLIMITED else level

    def try_adjust(self, spoke: int, step: int, available: int, floor: int = 0) -> int | None:
        """Change ``spoke`` by ``step`` levels if the rules allow it.

        Args:
            spoke: Index of the spoke to change.
            step: +1 to extend the spoke, -1 to shorten it.
            available: Points the caller can spend on this change.
            floor: Lowest level the spoke may be reduced to.

        Returns:
            The points spent (negative for a refund), or ``None`` if the
            change was refused and nothing happened.
        """
        old = self.spokes[spoke]
        new = old + step
        if not floor <= new <= UNLIMITED:
            return None
        cost = LEVEL_COSTS[new] - LEVEL_COSTS[old]
        if cost > available or self.cost + cost > PIECE_CAP:
            return None
        self.spokes[spoke] = new
        return cost


def make_captain(owner: Player) -> Piece:
    """Return ``owner``'s Captain: moves one square in every direction.

    Free, and fixed for the whole game — its spokes are never upgraded.
    """
    return Piece(owner, spokes=[CAPTAIN_REACH] * SPOKE_COUNT, is_captain=True)
