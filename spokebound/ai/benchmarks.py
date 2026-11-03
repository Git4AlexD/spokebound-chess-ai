"""Fixed, non-learning opponents used to keep tuning honest.

Two copies of the same weights share every blind spot — neither one ever
punishes the other for missing an obvious tactic, so self-play alone
can't prove a challenger is actually better, only that it's better
against itself. These bots each play one simple, known tactic without
adapting to it, so a challenger has to prove it can handle that tactic
specifically, not just outscore the current champion.

Each bot has three parts, all frozen so tuning never moves the bar:

  - a hard-coded rule that defines its signature behaviour (race, grab,
    turtle, hoard, or the rusher/grabber hybrid),
  - BENCHMARK_WEIGHTS, the brain it uses when its rule doesn't decide
    the move (and for bounty spending),
  - a FleetRules profile, so the army it brings matches its strategy.

Add more of these here as new winning tactics turn up.
"""

from collections.abc import Callable

from spokebound.ai.config import FleetRules, Weights
from spokebound.ai.evaluate import _is_defended
from spokebound.ai.search import _choose_level, choose_move_at
from spokebound.ai.selfplay import SELF_PLAY_LEVEL
from spokebound.config import GOAL_SQUARES
from spokebound.model.board import Square
from spokebound.model.game import Game

Move = tuple[Square, Square]
# A benchmark bot is just a move-chooser, the same shape choose_move has
# minus the difficulty argument — see spokebound.ai.evolve.play_deep and
# spokebound.ai.evolve_fleet.play_vs_benchmark, which each accept either
# this or a genome (Weights/FleetRules) for either side.
Bot = Callable[[Game], Move]

# The brain every bot uses for its fallback search and bounty spending.
# Weights() is the untuned class default and promotion never rewrites it
# (promotion only touches the DEFAULT_WEIGHTS literal in config.py), so
# this stays put no matter how the real AI is tuned.
BENCHMARK_WEIGHTS = Weights()


def rusher_move(game: Game) -> Move:
    """Always race the Captain toward the goal by the most direct legal
    step available; only plays anything else once the Captain has no
    move that actually gets it closer.

    Deliberately simple and single-minded — this is the exact failure
    mode a good AI has to withstand (see the captain_distance/
    goal_attackers/goal_urgency terms in evaluate.py), not a strong
    opponent in its own right.
    """
    player = game.current
    captain_square = next(
        (square for square, piece in game.board.pieces(player)
        if piece.is_captain), None)
    if captain_square is not None:
        here = _distance_to_goal(captain_square)
        closer = [dst for dst in game.legal_moves(captain_square)
                 if _distance_to_goal(dst) < here]
        if closer:
            return (captain_square, min(closer, key=_distance_to_goal))
    return choose_move_at(game, SELF_PLAY_LEVEL, BENCHMARK_WEIGHTS)


def _distance_to_goal(square: Square) -> int:
    goal_row, goal_col = next(iter(GOAL_SQUARES))
    return max(abs(square[0] - goal_row), abs(square[1] - goal_col))


def grabber_move(game: Game) -> Move:
    """Always take the single biggest-value capture on offer right now,
    with no regard for what it costs in return; only plays anything else
    once no capture is available at all.

    Deliberately reckless in the same way rusher_move is deliberately
    single-minded — this is the "dives for any undefended piece"
    failure mode a good AI has to withstand (see the piece_safety/
    bounty_risk terms in evaluate.py), not a strong opponent in its own
    right.
    """
    captures = [(src, dst) for src, dst in game.all_legal_moves(game.current)
               if game.board.get(dst) is not None]
    if captures:
        return max(captures, key=lambda move: game.board.get(move[1]).cost)
    return choose_move_at(game, SELF_PLAY_LEVEL, BENCHMARK_WEIGHTS)


def turtle_move(game: Game) -> Move:
    """Never advances its own Captain while any other legal move
    exists — searches normally, just with the Captain's own moves
    screened out of the candidates, falling back to moving the Captain
    (an ordinary search over every move) only once it's truly the only
    piece left that can move.

    Deliberately one-sided in the opposite direction from rusher_move —
    this is the "build a wall and never advance" failure mode: can the
    AI actually find a plan to break through a Captain that refuses to
    race, rather than only ever having faced one in a hurry?
    """
    player = game.current
    captain_square = next(
        (square for square, piece in game.board.pieces(player)
        if piece.is_captain), None)
    moves = game.all_legal_moves(player)
    screened = [move for move in moves if move[0] != captain_square]
    if not screened:
        return choose_move_at(game, SELF_PLAY_LEVEL, BENCHMARK_WEIGHTS)
    if len(screened) == 1:
        return screened[0]
    return _choose_level(game, screened, BENCHMARK_WEIGHTS, SELF_PLAY_LEVEL)[:2]


def hoarder_move(game: Game) -> Move:
    """Never captures anything while any non-capturing legal move
    exists — searches normally with every capture screened out of the
    candidates, only taking one when every legal move is a capture.

    Tests the opposite of grabber_move: an AI that's only ever learned
    to punish reckless material-grabbing may have no real plan against
    an opponent who simply refuses to trade and quietly improves its
    own position instead.
    """
    player = game.current
    moves = game.all_legal_moves(player)
    screened = [move for move in moves if game.board.get(move[1]) is None]
    if not screened:
        return choose_move_at(game, SELF_PLAY_LEVEL, BENCHMARK_WEIGHTS)
    if len(screened) == 1:
        return screened[0]
    return _choose_level(game, screened, BENCHMARK_WEIGHTS, SELF_PLAY_LEVEL)[:2]


def opportunist_move(game: Game) -> Move:
    """A hybrid of rusher_move and grabber_move: takes a free (genuinely
    undefended) capture first if one is on offer, otherwise races the
    Captain toward the goal exactly like rusher_move, falling back to
    an ordinary search only once neither applies.

    Closer to how an actually competent-but-simple human plays than
    either pure bot alone — tests whether the AI holds up against an
    opponent that's both greedy and goal-focused, not just one or the
    other.
    """
    player = game.current
    free_captures = [
        (src, dst) for src, dst in game.all_legal_moves(player)
        if game.board.get(dst) is not None
        and not _is_defended(game.board, dst)]
    if free_captures:
        return max(free_captures, key=lambda move: game.board.get(move[1]).cost)
    return rusher_move(game)


# Every benchmark bot the tuning pipeline plays a candidate against — not
# a separate pass/fail gate, just fixed, diverse opposition folded
# straight into every fitness evaluation (see spokebound.ai.evolve).
BENCHMARKS: dict[str, Bot] = {
    "rusher": rusher_move,
    "grabber": grabber_move,
    "turtle": turtle_move,
    "hoarder": hoarder_move,
    "opportunist": opportunist_move,
}

# The army each bot brings. In FleetRules, bias_n is forward, toward the
# opponent. Long pieces that reach the far end are the strongest, so
# rusher and opportunist lean forward, and opportunist spreads its reach
# more widely (more omnidirectional) than rusher. The rest are starting
# guesses for each strategy and should be checked in play.
BENCHMARK_FLEET_RULES: dict[str, FleetRules] = {
    "rusher": FleetRules(
        bias_n=6.0, bias_ne=2.0, bias_nw=2.0, bias_e=0.5, bias_w=0.5,
        bias_s=0.3, bias_se=0.3, bias_sw=0.3,
        concentration=1.5, variety=0.1),
    "grabber": FleetRules(
        bias_n=3.0, bias_ne=2.5, bias_nw=2.5, bias_e=2.0, bias_w=2.0,
        bias_s=1.0, bias_se=1.0, bias_sw=1.0,
        concentration=2.0, variety=0.2),
    "turtle": FleetRules(
        bias_n=0.5, bias_ne=0.5, bias_nw=0.5, bias_e=2.0, bias_w=2.0,
        bias_s=3.0, bias_se=2.5, bias_sw=2.5,
        concentration=1.0, variety=0.1),
    "hoarder": FleetRules(
        bias_n=1.0, bias_ne=1.0, bias_nw=1.0, bias_e=1.0, bias_w=1.0,
        bias_s=1.0, bias_se=1.0, bias_sw=1.0,
        concentration=2.5, variety=0.1),
    "opportunist": FleetRules(
        bias_n=5.0, bias_ne=3.0, bias_nw=3.0, bias_e=1.5, bias_w=1.5,
        bias_s=0.5, bias_se=0.8, bias_sw=0.8,
        concentration=1.5, variety=0.15),
}

# The same profiles keyed by the bot callable itself, for code that only
# has the callable in hand (see spokebound.ai.evolve_fleet).
RULES_FOR_BOT: dict[Bot, FleetRules] = {
    BENCHMARKS[name]: rules for name, rules in BENCHMARK_FLEET_RULES.items()
}
