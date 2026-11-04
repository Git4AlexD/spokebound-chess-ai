"""Static exchange evaluation, and the pruning tests built on it.

A capture is judged by the whole exchange on its square: each side keeps
recapturing with its cheapest piece for as long as doing so pays, so a
capture that loses material once the recaptures are counted is not worth
searching.
"""

from spokebound.ai.config import Weights
from spokebound.config import UNLIMITED
from spokebound.model.board import Board, Square
from spokebound.model.pieces import SPOKE_COUNT, Player, board_delta

Move = tuple[Square, Square]

# Points of slack for delta pruning: a capture is only dropped when even
# winning the captured piece outright (plus this margin) cannot lift the
# score past the bound it has to beat.
DELTA_MARGIN = 1.0


def attacker_costs(board: Board, square: Square, owner: Player, ignore: Square) -> list[int]:
    """Return the costs of ``owner``'s pieces that can reach ``square``,
    cheapest first, leaving out the piece standing on ``ignore``."""
    costs = []
    for spoke in range(SPOKE_COUNT):
        d_row, d_col = board_delta(spoke, owner)
        row, col = square
        distance = 0
        while True:
            row -= d_row
            col -= d_col
            distance += 1
            if not board.in_bounds((row, col)):
                break
            occupant = board.get((row, col))
            if occupant is None:
                continue
            if (
                occupant.owner is owner
                and (row, col) != ignore
                and (occupant.spokes[spoke] >= UNLIMITED or distance <= occupant.spokes[spoke])
            ):
                costs.append(occupant.cost)
            break
    return sorted(costs)


def see(board: Board, move: Move) -> int:
    """Return the material the move nets once both sides keep recapturing
    on its destination with their cheapest pieces, stopping whenever going
    on would lose material. Pieces that open up behind a capturing piece
    are ignored, so this is an estimate rather than an exact count.
    """
    src, dst = move
    mover = board.get(src)
    victim = board.get(dst)
    gains = [victim.cost if victim is not None else 0]
    on_square = mover.cost
    sides = [mover.owner.opponent, mover.owner]
    costs = {side: attacker_costs(board, dst, side, src) for side in sides}
    turn = 0
    while costs[sides[turn % 2]]:
        recapture = costs[sides[turn % 2]].pop(0)
        gains.append(on_square - gains[-1])
        on_square = recapture
        turn += 1
    for index in range(len(gains) - 1, 0, -1):
        gains[index - 1] = -max(-gains[index - 1], gains[index])
    return gains[0]


def prune_quiescence(
    board: Board, forcing: list[Move], stand_pat: float, bound: float, weights: Weights, maximizing: bool
) -> list[Move]:
    """Drop the captures in ``forcing`` that cannot change the outcome:
    exchanges that lose material (see :func:`see`), and captures too small
    to lift the score past ``bound`` even if they win the piece outright.
    Checks are never dropped, since a check can always matter.
    """
    kept = []
    for move in forcing:
        victim = board.get(move[1])
        if victim is None:
            kept.append(move)
            continue
        if see(board, move) < 0:
            continue
        gain = weights.material * (victim.cost + DELTA_MARGIN)
        if maximizing and stand_pat + gain < bound:
            continue
        if not maximizing and stand_pat - gain > bound:
            continue
        kept.append(move)
    return kept
