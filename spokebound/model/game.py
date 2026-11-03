"""Turn flow and win conditions for a Spokebound match."""

import copy
from dataclasses import dataclass

from spokebound.config import (
    BOARD_ROWS, BOUNTIES, GOAL_SQUARES, PROMOTION_BONUS, TURN_LIMIT,
)
from spokebound.model.board import Board, Square
from spokebound.model.pieces import Piece, Player
from spokebound.model.spending import PendingUpgrade

HOME_ROWS = {Player.ORANGE: BOARD_ROWS - 1, Player.WHITE: 0}


def assign_bounties(fleet: list[Piece]) -> None:
    """Give the bounties to the most expensive pieces in ``fleet``.

    Ties go to the piece further left from the owner's point of view.
    """
    ranked = sorted(fleet, key=lambda piece: piece.cost, reverse=True)
    for piece, bounty in zip(ranked, BOUNTIES):
        piece.bounty = bounty


@dataclass(frozen=True)
class Outcome:
    """How a finished game ended. ``winner`` is ``None`` for a draw.

    ``reached_centre`` is True only for the "marched the Captain onto
    the centre" win — the UI's own cue for whether to play its victory
    spiral (see DeployScreen._refresh_status), rather than matching on
    ``reason``'s own text, which is meant for the log/status line, not
    as a machine-readable signal.
    """

    winner: Player | None
    reason: str
    reached_centre: bool = False


class Game:
    """A match in progress, driven by :meth:`move` and :meth:`finish_turn`.

    Rules follow chess for the Captain: a move that would leave your own
    Captain attacked is illegal (which also means you must answer a
    check), and a player with no legal move at all — in check or not —
    loses immediately. A move that earns bonus points leaves the turn
    open with :attr:`upgrade` set; the turn ends when :meth:`finish_turn`
    is called.
    """

    def __init__(self, board: Board) -> None:
        self.board = board
        self.current = Player.ORANGE
        self.moves_made = {Player.ORANGE: 0, Player.WHITE: 0}
        self.upgrade: PendingUpgrade | None = None
        self.outcome: Outcome | None = None
        self.log: list[str] = ["Orange moves first."]

    @property
    def is_over(self) -> bool:
        """Return True once the game has a result."""
        return self.outcome is not None

    def copy(self) -> "Game":
        """Return a deep, independent copy of this game.

        Search (see :mod:`spokebound.ai`) plays speculative moves out on
        a copy and discards it, rather than risk leaving the real game in
        some half-simulated state or needing a matching "undo" for every
        rule (promotion, bounties, the win checks) move() can trigger.
        """
        return copy.deepcopy(self)

    def all_legal_moves(self, player: Player) -> list[tuple[Square, Square]]:
        """Return every ``(src, dst)`` legal move for ``player``.

        Empty if it isn't ``player``'s turn, the game is over, or an
        upgrade is pending — the same cases :meth:`legal_moves` already
        refuses, just enumerated across every one of their pieces instead
        of one square at a time.
        """
        if player is not self.current:
            return []
        return [(src, dst) for src, _ in self.board.pieces(player)
               for dst in self.legal_moves(src)]

    def score(self, player: Player) -> int:
        """Return the total points ``player`` has left on the board."""
        return sum(piece.cost for _, piece in self.board.pieces(player))

    def in_check(self, player: Player) -> bool:
        """Return True if ``player``'s Captain is currently attacked."""
        square = self._captain_square(player)
        return (square is not None
               and self._is_attacked(square, player.opponent))

    def legal_moves(self, src: Square) -> list[Square]:
        """Return legal destinations for the current player's piece.

        A candidate move is dropped if playing it would leave the
        mover's own Captain attacked.
        """
        piece = self.board.get(src)
        if not self._can_move_from(src, piece):
            return []
        return [dst for dst in self.board.legal_moves(src)
               if not self._leaves_captain_attacked(src, dst, piece.owner)]

    def is_legal(self, src: Square, dst: Square) -> bool:
        """Return True if ``src`` -> ``dst`` is one of :meth:`legal_moves`,
        checking just that one destination instead of every candidate."""
        piece = self.board.get(src)
        if not self._can_move_from(src, piece):
            return False
        return (dst in self.board.legal_moves(src)
                and not self._leaves_captain_attacked(src, dst, piece.owner))

    def _can_move_from(self, src: Square, piece: Piece | None) -> bool:
        return not (self.is_over or self.upgrade or piece is None
                    or piece.owner is not self.current)

    def move(self, src: Square, dst: Square) -> None:
        """Play a move for the current player."""
        if not self.is_legal(src, dst):
            raise ValueError(f"Illegal move {src} -> {dst}")
        piece = self.board.get(src)
        captured = self.board.move(src, dst)
        points = (self._capture_points(piece, captured)
                 + self._promotion_points(piece, dst))
        if piece.is_captain and dst in GOAL_SQUARES:
            self._end(piece.owner, "marched the Captain onto the centre",
                      reached_centre=True)
            return
        if points and not piece.is_captain:
            self.upgrade = PendingUpgrade(piece, points)
        else:
            self.finish_turn()

    def finish_turn(self) -> None:
        """Close the current turn and start the next player's."""
        self.upgrade = None
        self.moves_made[self.current] += 1
        self.current = self.current.opponent
        self._start_turn()

    def _start_turn(self) -> None:
        """Check the turn limit, then checkmate and stalemate."""
        if all(n >= TURN_LIMIT for n in self.moves_made.values()):
            self._end_on_points()
        elif not self._has_any_legal_move(self.current):
            reason = ("checkmated" if self.in_check(self.current)
                      else "stalemated, with no legal move")
            self._end(self.current.opponent,
                     f"{self.current.label} was {reason}")

    def _has_any_legal_move(self, player: Player) -> bool:
        """Return True if any of ``player``'s pieces has a legal move."""
        return any(self.legal_moves(sq)
                  for sq, _ in self.board.pieces(player))

    def _captain_square(self, player: Player) -> Square | None:
        """Return the square ``player``'s Captain stands on, if it's alive."""
        for square, piece in self.board.pieces(player):
            if piece.is_captain:
                return square
        return None

    def _is_attacked(self, square: Square, by_player: Player) -> bool:
        """Return True if any of ``by_player``'s pieces can reach it."""
        return self.board.is_attacked(square, by_player)

    def _leaves_captain_attacked(self, src: Square, dst: Square,
                                 owner: Player) -> bool:
        """Simulate src -> dst and report whether ``owner``'s Captain is
        then attacked, undoing the simulation before returning."""
        captured = self.board.move(src, dst)
        square = self._captain_square(owner)
        attacked = (square is not None
                   and self._is_attacked(square, owner.opponent))
        self.board.move(dst, src)
        if captured is not None:
            self.board.place(dst, captured)
        return attacked

    def _capture_points(self, piece: Piece, captured: Piece | None) -> int:
        """Log a capture and return the bounty points it earned."""
        if captured is None:
            return 0
        bounty = (f" and claimed its {captured.bounty} bounty"
                  if captured.bounty else "")
        self.log.append(f"{piece.owner.label} captured a {captured.cost}-"
                        f"point piece{bounty}.")
        return captured.bounty

    def _promotion_points(self, piece: Piece, dst: Square) -> int:
        """Promote ``piece`` on its first visit to the far row.

        Returns the bonus points earned, or 0 if there was no promotion.
        The Captain is fixed and never promotes.
        """
        if piece.is_captain or piece.promoted:
            return 0
        far_row = HOME_ROWS[piece.owner.opponent]
        reached = (dst[0] <= far_row if piece.owner is Player.ORANGE
                  else dst[0] >= far_row)
        if not reached:
            return 0
        piece.promoted = True
        self.log.append(f"{piece.owner.label} promoted a piece "
                        f"(+{PROMOTION_BONUS}).")
        return PROMOTION_BONUS

    def _end_on_points(self) -> None:
        """Decide the game on points left once the turn limit is reached."""
        orange, white = self.score(Player.ORANGE), self.score(Player.WHITE)
        winner = None
        if orange != white:
            winner = Player.ORANGE if orange > white else Player.WHITE
        self._end(winner, f"turn limit reached ({orange}-{white} points)")

    def _end(self, winner: Player | None, reason: str,
             reached_centre: bool = False) -> None:
        """Record the result and close any open upgrade."""
        self.outcome = Outcome(winner, reason, reached_centre)
        self.upgrade = None
        who = f"{winner.label} wins" if winner is not None else "Draw"
        self.log.append(f"{who}: {reason}.")
