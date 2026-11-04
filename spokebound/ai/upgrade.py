"""AI upgrade spending: greedily extend whichever direction leaves the
whole position scoring best, until the points run out.
"""

from spokebound.ai.config import DEFAULT_WEIGHTS, Weights
from spokebound.ai.evaluate import evaluate
from spokebound.config import LEVEL_COSTS, PIECE_CAP, UNLIMITED
from spokebound.model.game import Game
from spokebound.model.pieces import SPOKE_COUNT
from spokebound.model.spending import PendingUpgrade

SPEND_CANDIDATES = 3


def spend_candidates(game: Game, upgrade: PendingUpgrade,
                     weights: Weights,
                     width: int = SPEND_CANDIDATES) -> list[tuple[int, ...]]:
    """Return up to ``width`` ways of spending ``upgrade``'s points, best first.

    A beam search over the spend: each step raises one spoke by one level,
    and only the ``width`` most promising partial spends (by the position's
    evaluation) carry on. Full enumeration is far too large once a bounty
    is more than a point or two, so the candidates are a ranked selection
    rather than every possibility.
    """
    piece = upgrade.piece
    owner = piece.owner
    original = tuple(piece.spokes)
    beam = [(original, upgrade.points, piece.cost)]
    finished: set[tuple[int, ...]] = set()
    while beam:
        successors: dict[tuple, None] = {}
        for spokes, points, cost in beam:
            extended = False
            for spoke, level in enumerate(spokes):
                if level >= UNLIMITED:
                    continue
                delta = LEVEL_COSTS[level + 1] - LEVEL_COSTS[level]
                if delta > points or cost + delta > PIECE_CAP:
                    continue
                extended = True
                raised = (*spokes[:spoke], level + 1, *spokes[spoke + 1:])
                successors[(raised, points - delta, cost + delta)] = None
            if not extended:
                finished.add(spokes)
        ranked = []
        for spokes, points, cost in successors:
            piece.spokes = list(spokes)
            ranked.append((evaluate(game, owner, weights), (spokes, points, cost)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        beam = [state for _, state in ranked[:width]]
    scored = []
    for spokes in finished:
        piece.spokes = list(spokes)
        scored.append((evaluate(game, owner, weights), spokes))
    piece.spokes = list(original)
    scored.sort(key=lambda item: item[0], reverse=True)
    return [spokes for _, spokes in scored[:width]] or [original]


def spend_upgrade(game: Game, weights: Weights = DEFAULT_WEIGHTS) -> None:
    """Spend every point of ``game.upgrade`` on its piece.

    Each step tries every one-level extension still available (any
    spoke not yet unlimited), scores the position that step would
    produce with :func:`spokebound.ai.evaluate.evaluate` and keeps
    whichever scores best for the piece's owner, before repeating for
    the next point.

    Deliberately not "whichever direction opens the most new squares"
    (the old rule): that rewards raw mobility regardless of whether it
    actually matters right now — a spoke that closes a hole in the
    Captain's own defence, covers a piece worth protecting, or presses
    the goal can lose to one that just adds empty squares nobody's
    contesting, which is exactly the kind of tactically-blind spending a
    stronger opponent could rely on. Scoring the whole position after
    each candidate step catches all of that the same way search already
    does everywhere else in this package, at the cost of one evaluate()
    call per still-available spoke per point — cheap next to a single
    node of the main search, and this only ever runs once a bounty or
    promotion has actually happened, not on every move.
    """
    upgrade = game.upgrade
    if upgrade is None:
        return
    piece = upgrade.piece
    owner = piece.owner
    while upgrade.points > 0:
        best_spoke, best_score = None, float("-inf")
        for spoke in range(SPOKE_COUNT):
            if piece.spokes[spoke] >= UNLIMITED:
                continue
            if not upgrade.adjust(spoke, 1):
                continue
            score = evaluate(game, owner, weights)
            upgrade.adjust(spoke, -1)
            if score > best_score:
                best_score, best_spoke = score, spoke
        if best_spoke is None or not upgrade.adjust(best_spoke, 1):
            break
