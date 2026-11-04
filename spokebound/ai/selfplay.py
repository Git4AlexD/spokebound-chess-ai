"""Shared machinery for playing whole AI-vs-AI games in bulk — the part
spokebound.ai.tournament (level vs. level), spokebound.ai.evolve (Weights
vs. Weights, bred across generations) and spokebound.ai.evolve_fleet
(FleetRules vs. FleetRules) would otherwise each reimplement on their
own: deploy two fleets, play out a full game with a safety-net turn
ceiling, and spread many such games across every CPU core.
"""

import multiprocessing
import time
from collections.abc import Callable
from typing import NamedTuple

from spokebound.ai.config import DEFAULT_WEIGHTS, Weights
from spokebound.ai.deploy import choose_deploy_square
from spokebound.ai.levels import Level
from spokebound.ai.search import play_ply
from spokebound.config import TURN_LIMIT
from spokebound.model.deployment import Deployment
from spokebound.model.game import Game
from spokebound.model.pieces import Piece, Player

Move = tuple
MoveChooser = Callable[[Game], Move]

# How often (in completed games) to print a progress line during a
# batch of games, so a long one doesn't sit silent.
PROGRESS_EVERY = 20


def format_duration(seconds: float) -> str:
    """A short, human "Xh Ym" / "Xm Ys" / "Xs" rendering of a duration —
    used everywhere a long run reports elapsed time or an ETA, so every
    one of those reads the same way."""
    seconds = max(0, round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# The search profile every self-play game (spokebound.ai.evolve,
# evolve_fleet, and benchmarks.py's own fallback) plays at — not one of
# the 10 player-facing levels in spokebound.ai.levels (0 is never a key
# there), since those are tuned for how a human experiences the ladder,
# not for how fast bulk self-play can run. Still the real engine
# (alpha-beta, quiescence, move ordering, a transposition table), just
# a shallow, fast profile of its own — fast enough to play thousands of
# games in a reasonable time, deep enough that two different Weights or
# FleetRules still actually play differently against each other.
SELF_PLAY_LEVEL = Level(
    number=0,
    name="Self-Play",
    min_depth=2,
    max_depth=3,
    time_limit=0.4,
    critical_time_limit=0.6,
    use_quiescence=True,
    use_move_ordering=True,
    use_transposition_table=True,
    # Unused in practice: build_fleet_spec only ever consults a level's
    # pregame_skill by looking it up in the real LEVELS dict by number,
    # and 0 is never a key there — every self-play/tuning caller either
    # passes its own FleetRules explicitly or gets DEFAULT_FLEET_RULES
    # outright (see build._rules_for_level). Set to 1.0 anyway, so this
    # profile would still mean "full strength" if that ever changed.
    pregame_skill=1.0,
)


class GameResult(NamedTuple):
    """One finished game's outcome plus each side's own final score
    (see Game.score — the cost of everything it still has on the
    board), so a caller that cares how *decisively* a game went (not
    just who won — see spokebound.ai.evolve's own margin-of-victory
    fitness) doesn't have to replay the game itself to find out."""

    winner: Player | None
    orange_score: int
    white_score: int


def play_full_game(
    orange_fleet: list[Piece],
    white_fleet: list[Piece],
    choose_for: Callable[[Player], MoveChooser],
    weights_for: Callable[[Player], Weights] | None = None,
    skill_for: Callable[[Player], float] | None = None,
) -> GameResult:
    """Deploy both fleets and play one full game to completion.

    ``choose_for(player)`` returns the move-chooser to call whenever it's
    ``player``'s turn — a closure over whatever "contestant" (a level
    number, a Weights, a fixed bot) that side is playing, so this
    function itself never needs to know what a contestant even is.
    ``weights_for(player)``, if given, returns which Weights that side's
    own bounty/promotion spending should be scored against (see
    spokebound.ai.upgrade.spend_upgrade) — so a self-play game between
    two different candidate Weights has each side upgrading by its own
    lights, not always DEFAULT_WEIGHTS regardless of who earned the
    upgrade; callers with no per-side Weights concept (a plain level
    number, say) can just omit it. ``skill_for(player)``, if given,
    returns how much that side's deployment trusts its own evaluation
    (see spokebound.ai.deploy.choose_deploy_square) — spokebound.ai.
    tournament uses this so a level-vs-level game degrades deployment
    the same way it already degrades search depth and fleet-building;
    tuning callers that want every game played at full strength
    regardless of level (spokebound.ai.evolve/evolve_fleet) just omit
    it. Returns a GameResult (``winner`` is ``None`` for a draw). A real
    game always ends on its own (checkmate, stalemate or the turn
    limit); the ``ceiling`` below is only a safety net against a bug
    looping forever during an unattended run.
    """
    deployment = Deployment(orange_fleet, white_fleet)
    while not deployment.is_done:
        player = deployment.current
        weights = weights_for(player) if weights_for is not None else DEFAULT_WEIGHTS
        skill = skill_for(player) if skill_for is not None else 1.0
        square = choose_deploy_square(deployment, player, weights, skill)
        deployment.place(square)

    game = Game(deployment.board)
    ceiling = TURN_LIMIT * 2 + 20
    plies = 0
    while not game.is_over and plies < ceiling:
        ply = choose_for(game.current)(game)
        weights = weights_for(game.current) if weights_for is not None else DEFAULT_WEIGHTS
        play_ply(game, ply, weights)
        plies += 1
    winner = game.outcome.winner if game.outcome is not None else None
    return GameResult(winner, game.score(Player.ORANGE), game.score(Player.WHITE))


def _play_one(task: tuple) -> str:
    """Play one game and report it from ``a``'s side — run in a worker
    process, so ``play_game_fn`` and everything it closes over has to be
    picklable (a module-level function is; so is a frozen dataclass like
    Weights).

    ``task`` is ``(play_game_fn, a_is_orange, a, b)``: ``play_game_fn(a,
    b)`` plays one game with ``a`` as Orange, ``b`` as White, and returns
    the winner. Kept as a single tuple (rather than separate
    pool.starmap arguments) so every caller's task list looks the same
    shape, regardless of what ``a`` and ``b`` actually are.
    """
    play_game_fn, a_is_orange, a, b = task
    winner = play_game_fn(a, b) if a_is_orange else play_game_fn(b, a)
    if winner is None:
        return "draw"
    a_won = (a_is_orange and winner is Player.ORANGE) or (not a_is_orange and winner is Player.WHITE)
    return "a" if a_won else "b"


def play_round(
    pool: multiprocessing.Pool,
    play_game_fn: Callable,
    a=None,
    b=None,
    games: int = 0,
    label: str = "round",
    a_name: str = "a",
    b_name: str = "b",
    progress_every: int = PROGRESS_EVERY,
    prepare: Callable[[], tuple] | None = None,
) -> tuple[int, int, int]:
    """Play ``games`` games between ``a`` and ``b`` with ``play_game_fn``,
    each side playing both colours equally, spread across every CPU core
    in ``pool``. Prints a progress line every ``progress_every`` completed
    games (the games finish in whatever order each worker gets to them,
    not the order they were submitted, so this reports "how many so
    far," not "which one"). Returns ``(a_wins, b_wins, draws)``.

    ``prepare``, if given, is called once per *pair* of games (one per
    colour) to produce a fresh ``(a, b)`` for that pair, in place of the
    static ``a``/``b`` arguments (which are then ignored entirely) — see
    spokebound.ai.evolve._prepare_matchup, which builds a fresh shared
    fleet spec this way so a matchup's games sample a genuine variety of
    fleets instead of replaying the same one, colour-swapped, for every
    game (a matchup with no ``prepare`` has no other source of per-game
    variation once deployment and search are both deterministic, so
    every colour-pair ends up an exact replay of the other pairs — the
    same 2 real outcomes repeated, not ``games`` independent samples).
    """
    task_args = []
    current: tuple = (a, b)
    for i in range(games):
        if prepare is not None and i % 2 == 0:
            current = prepare()
        task_args.append(current)
    tasks = [(play_game_fn, i % 2 == 0, task_args[i][0], task_args[i][1]) for i in range(games)]
    results = []
    started = time.monotonic()
    for completed, result in enumerate(pool.imap_unordered(_play_one, tasks), start=1):
        results.append(result)
        if completed % progress_every == 0 or completed == games:
            elapsed = time.monotonic() - started
            remaining = games - completed
            eta = (elapsed / completed) * remaining if completed else 0.0
            eta_text = (
                f", ~{format_duration(eta)} left" if remaining else f", took {format_duration(elapsed)}"
            )
            print(
                f"  [{label}] {completed}/{games} games played "
                f"({a_name} {results.count('a')}, "
                f"{b_name} {results.count('b')}, "
                f"draws {results.count('draw')}){eta_text}",
                flush=True,
            )
    return (results.count("a"), results.count("b"), results.count("draw"))
