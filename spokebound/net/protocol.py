"""Wire format for a network match.

Every action either side takes — locking in a fleet, deploying a
piece, making a move, spending an upgrade — becomes one small JSON
object, newline-delimited over the connection (see
:mod:`spokebound.net.session`). Encoding and decoding both live here
so neither side of the connection has to know the other's internal
types (:class:`~spokebound.model.pieces.Piece`, a board ``Square``
tuple) — just plain dicts, lists and ints.
"""

from dataclasses import asdict
from typing import Any

from spokebound.model.board import Square
from spokebound.model.pieces import Piece, Player

Message = dict[str, Any]

# Bumped whenever a message's shape changes, so two mismatched builds
# fail the handshake cleanly instead of silently desyncing mid-game.
PROTOCOL_VERSION = 1

HELLO = "hello"
FLEET = "fleet"
PLACE = "place"
MOVE = "move"
UPGRADE_ADJUST = "upgrade_adjust"
UPGRADE_FINISH = "upgrade_finish"


def hello() -> Message:
    """The first message either side sends, so a version mismatch is
    caught immediately rather than as a confusing decode failure
    later."""
    return {"type": HELLO, "version": PROTOCOL_VERSION}


def fleet(pieces: list[Piece]) -> Message:
    """A locked-in fleet, ready to send to the other side once both
    players are done building."""
    return {"type": FLEET, "pieces": [_piece_to_dict(p) for p in pieces]}


def fleet_from(message: Message) -> list[Piece]:
    return [_piece_from_dict(p) for p in message["pieces"]]


def place(square: Square) -> Message:
    """Deploying the sender's next piece to ``square``."""
    return {"type": PLACE, "square": list(square)}


def place_from(message: Message) -> Square:
    row, col = message["square"]
    return (row, col)


def move(src: Square, dst: Square) -> Message:
    """Moving the piece on ``src`` to ``dst``."""
    return {"type": MOVE, "src": list(src), "dst": list(dst)}


def move_from(message: Message) -> tuple[Square, Square]:
    src_row, src_col = message["src"]
    dst_row, dst_col = message["dst"]
    return (src_row, src_col), (dst_row, dst_col)


def upgrade_adjust(spoke: int, step: int) -> Message:
    """Raising or lowering one spoke of the piece currently being
    upgraded, after a bounty capture or promotion."""
    return {"type": UPGRADE_ADJUST, "spoke": spoke, "step": step}


def upgrade_adjust_from(message: Message) -> tuple[int, int]:
    return message["spoke"], message["step"]


def upgrade_finish() -> Message:
    """Done spending bonus points; ends the sender's turn."""
    return {"type": UPGRADE_FINISH}


def _piece_to_dict(piece: Piece) -> dict:
    data = asdict(piece)
    data["owner"] = int(piece.owner)
    return data


def _piece_from_dict(data: dict) -> Piece:
    data = dict(data)
    data["owner"] = Player(data["owner"])
    return Piece(**data)
