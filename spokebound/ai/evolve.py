"""Weight tuning for the actual-game "brain" (see
spokebound.ai.config.Weights; spokebound.ai.evolve_fleet is this same
approach's twin for FleetRules, the pregame-setup brain) — CMA-ES (see
spokebound.ai.cma_es) searching Weights space, with every single game,
every generation, played at DEEP_LEVEL: LEVELS[10], Impossible, the
exact profile the hardest difficulty actually ships with. No shallow
proxy depth, no cheap early tier, no successive-halving rungs — the
only thing this ever measures is how a candidate performs at the real,
deployed depth, because that's the only number that answers "is this
actually the best AI."

Each generation, every candidate plays GAMES_PER_BENCHMARK games (split
evenly by colour, a fresh fleet every game) against *every* fixed
benchmark bot in spokebound.ai.benchmarks — rusher (races the goal),
grabber (dives for any undefended piece), turtle (never advances its
Captain), hoarder (never trades), opportunist (a hybrid of rusher and
grabber) — *plus* the same number of games against the current
incumbent (CMA-ES's own search-distribution mean from just before this
generation's update — see spokebound.ai.cma_es.run_cma_es) *plus* every
entry currently in the hall of fame (a small, capped pool of *past*
incumbents — see HALL_OF_FAME_EVERY/HALL_OF_FAME_SIZE). A candidate's
fitness is the sum of _score(outcome, margin) across every one of those
games — not flat win/loss/draw points, but each game's actual final
material margin too (see _score), so two wins don't score identically
just because they're both wins.

Three things are stacked here, each fixing a different way the fitness
signal alone would otherwise go stale:

  - The fixed benchmarks catch a shared blind spot self-play alone
    can't (this isn't the same mistake a genetic-tournament predecessor
    of this file made by relying on self-play *alone* — that's exactly
    how it once crowned a champion that lost outright to a bot that
    simply grabbed material) — but once the population beats all five
    convincingly and consistently, they stop being a real test.
  - The current incumbent keeps the bar rising automatically as the
    population actually improves, instead of plateauing the moment the
    fixed benchmarks do.
  - The hall of fame keeps it from quietly *regressing* against a
    strategy it already beat: pure self-play against only the single
    most-recent incumbent can still let the population drift away from
    beating an older approach, simply because nothing's testing against
    it any more once it's no longer "current" (the same strategy-
    cycling failure mode leagues like AlphaStar's are built to avoid).
  - Margin-of-victory scoring keeps a real, continuous signal to climb
    even once every opponent above is already losing outright — outcome
    (win/draw/loss) still always dominates the score, margin only
    refines *within* one outcome, but without it every win (a
    nail-biter or a rout alike) would score identically the moment the
    population gets good enough, and CMA-ES would lose its resolution
    to tell "good" from "better" even though nothing's actually optimal
    yet.

Not run as part of the app or the test suite — a standalone session you
start on purpose:

    python -m spokebound.ai.evolve
    python -m spokebound.ai.evolve --fresh

Crash-resilient by default: the whole search distribution is saved to
STATE_PATH after every single generation, so if this gets killed,
crashes, or the machine restarts, just running
``python -m spokebound.ai.evolve`` again picks up from the last
completed generation rather than losing everything. Pass ``--fresh`` to
deliberately discard any saved progress and start over from the seed
instead — either way, an actual fresh start first cleans out every file
the previous run touched (results, log, saved champion, saved state),
so nothing from it can accidentally linger into the new one.

Prints progress every generation (the population's own best score this
generation, CMA-ES's own sigma — how wide a region it's still
searching, shrinking as it converges — and a running ETA), plus a fuller
per-benchmark win/loss/draw checkpoint of the current incumbent (the
search distribution's own mean, not any single generation's best
individual) every CHECKPOINT_EVERY generations and once more at the
end — this is the number that actually answers "how good is the AI
right now," read it there rather than the raw per-generation fitness.
Always promotes the final incumbent straight into
spokebound.ai.config.DEFAULT_WEIGHTS via spokebound.ai.promote once
it's done — there's no gate and no separate "default" any more:
DEFAULT_WEIGHTS is a seed used only to start CMA-ES's very first search
distribution before any tuning has run at all (see MEAN0); once a run
finishes, whatever it found *becomes* DEFAULT_WEIGHTS, unconditionally.

Every game here plays at Impossible's own depth (up to several seconds
a move, sometimes longer under critical_time_limit), so this is slow —
expect a single generation to take tens of minutes, not seconds.
POPULATION_SIZE, GENERATIONS and GAMES_PER_BENCHMARK (see run()'s own
arguments) can all be lowered for a quicker, noisier run, the same
real trade spokebound.ai.cma_es's own module docstring describes for
any noisy optimization: fewer games per candidate means a noisier
fitness estimate, which CMA-ES tolerates reasonably well by design
(unlike a genetic tournament, no single unlucky game can eliminate a
candidate outright — it just nudges the search distribution a little
less confidently that generation) but doesn't eliminate.
"""

import json
import multiprocessing
import time
from pathlib import Path

from spokebound.ai.benchmarks import BENCHMARK_WEIGHTS, BENCHMARKS
from spokebound.ai.build import build_fleet_spec, materialize_fleet
from spokebound.ai.cma_es import run_cma_es
from spokebound.ai.config import DEFAULT_WEIGHTS, Weights
from spokebound.ai.levels import LEVELS
from spokebound.ai.promote import apply as promote
from spokebound.ai.search import choose_turn_at
from spokebound.ai.selfplay import format_duration, play_full_game, play_round
from spokebound.config import BUILD_BUDGET
from spokebound.model.pieces import Player

POPULATION_SIZE = 6
GENERATIONS = 20
# Per candidate, per benchmark bot, split evenly by colour — see the
# module docstring's noise/speed trade-off note.
GAMES_PER_BENCHMARK = 2
# CMA-ES's own initial step size, in the same units as a Weights field
# itself (most fields sit somewhere around 0.3-3.0) — wide enough to
# explore real extremes from the very first generation, not a gentle
# nudge around the seed.
SIGMA0 = 0.5
# How often (in generations) to separately evaluate the current
# incumbent's own per-benchmark record — the clear, directly-readable
# "how good is the AI right now" report, distinct from the noisier
# per-generation search signal (see CHECKPOINT_GAMES).
CHECKPOINT_EVERY = 5
CHECKPOINT_GAMES = 6
# The only depth anything plays at — Impossible, exactly what level 10
# ships with. See spokebound.ai.levels.LEVELS.
DEEP_LEVEL = LEVELS[10]
# How often (in generations) a snapshot of the current incumbent joins
# the hall of fame — a small, capped pool of *past* incumbents that
# stays in the opponent mix alongside the *current* one (see the module
# docstring), so the population can't quietly regress against a
# strategy it beat a while ago just because nothing's tested that any
# more. Kept well below CHECKPOINT_EVERY's own games so a full hall of
# fame doesn't dominate the per-generation game count.
HALL_OF_FAME_EVERY = 5
HALL_OF_FAME_SIZE = 3

RESULTS_PATH = Path(__file__).with_name("evolution_results.txt")
LOG_PATH = Path(__file__).with_name("evolution_log.jsonl")
BEST_WEIGHTS_PATH = Path(__file__).with_name("evolved_champion.json")
# Where run_cma_es saves the whole search distribution after every
# generation, and where run() looks to resume an interrupted run — see
# run()'s own ``resume`` argument.
STATE_PATH = Path(__file__).with_name("cma_es_state.json")
# The hall of fame's own saved state — a plain JSON list of genomes,
# alongside but independent of STATE_PATH (run_cma_es knows nothing
# about this concept, it's purely evolve.py's own), so a resumed run
# picks the hall of fame back up too, not just CMA-ES's own state.
HALL_OF_FAME_PATH = Path(__file__).with_name("hall_of_fame.json")


def _chooser(contestant):
    """Return the move-chooser for one side of a game: a search at
    DEEP_LEVEL for a Weights, or whatever a fixed benchmark bot (a
    plain callable — see spokebound.ai.benchmarks) decides on its own."""
    if isinstance(contestant, Weights):
        return lambda game: choose_turn_at(game, DEEP_LEVEL, contestant)
    return contestant


def _weights_for(contestant) -> Weights:
    return contestant if isinstance(contestant, Weights) else BENCHMARK_WEIGHTS


def _play_game(a, b) -> Player | None:
    """Play one game at DEEP_LEVEL between two contestants, each either
    a Weights or a fixed benchmark bot — both sides share one freshly
    built fleet spec (built fresh on every call, so repeated games
    naturally sample different fleets — see spokebound.ai.build), so
    this is never testing fleet luck, only how ``a`` and ``b`` actually
    play."""
    spec = build_fleet_spec(DEEP_LEVEL.number)
    orange_fleet = materialize_fleet(spec, Player.ORANGE)
    white_fleet = materialize_fleet(spec, Player.WHITE)
    by_player = {Player.ORANGE: a, Player.WHITE: b}

    def choose_for(player: Player):
        return _chooser(by_player[player])

    def weights_for(player: Player) -> Weights:
        return _weights_for(by_player[player])

    return play_full_game(orange_fleet, white_fleet, choose_for, weights_for).winner


def _play_one(task: tuple) -> tuple[int, str, int]:
    """Run in a worker process — see _evaluate_population. ``task`` is
    ``(genome_index, a_is_orange, genome, opponent, spec)`` — ``opponent``
    either a fixed benchmark bot or the current incumbent/hall-of-fame
    Weights, the two things _chooser/_weights_for already handle
    generically; returns ``(genome_index, "win"/"loss"/"draw", margin)``
    from ``genome``'s own side, where ``margin`` is its own final score
    minus its opponent's (see spokebound.ai.selfplay.GameResult) — a
    finer-grained signal than win/loss/draw alone, see _score."""
    genome_index, a_is_orange, genome, opponent, spec = task
    orange_fleet = materialize_fleet(spec, Player.ORANGE)
    white_fleet = materialize_fleet(spec, Player.WHITE)
    a, b = (genome, opponent) if a_is_orange else (opponent, genome)
    by_player = {Player.ORANGE: a, Player.WHITE: b}

    def choose_for(player: Player):
        return _chooser(by_player[player])

    def weights_for(player: Player) -> Weights:
        return _weights_for(by_player[player])

    result = play_full_game(orange_fleet, white_fleet, choose_for, weights_for)
    genome_score = result.orange_score if a_is_orange else result.white_score
    opponent_score = result.white_score if a_is_orange else result.orange_score
    margin = genome_score - opponent_score
    if result.winner is None:
        return (genome_index, "draw", margin)
    genome_won = ((a_is_orange and result.winner is Player.ORANGE)
                 or (not a_is_orange and result.winner is Player.WHITE))
    return (genome_index, "win" if genome_won else "loss", margin)


def _score(outcome: str, margin: int) -> float:
    """Turn one game's outcome and final material margin (the genome's
    own final score minus its opponent's, from _play_one) into a
    fitness contribution. Outcome always dominates — a win always
    outscores a draw, which always outscores a loss, regardless of
    margin — margin only refines *within* the same outcome, capped well
    short of a whole point either way. Without this, once a candidate
    is already winning every game outright, every convincing win and
    every nail-biter score identically and CMA-ES loses its resolution
    to tell "good" from "better" — see the module docstring."""
    base = {"win": 2.0, "draw": 1.0, "loss": 0.0}[outcome]
    bonus = max(-0.49, min(0.49, margin / (2 * BUILD_BUDGET)))
    return base + bonus


def _evaluate_population(genomes: list[Weights], incumbent: Weights,
                         hall_of_fame: list[Weights],
                         games_per_benchmark: int = GAMES_PER_BENCHMARK,
                         ) -> list[float]:
    """Play every one of ``genomes`` against every benchmark bot, the
    current ``incumbent``, and every ``hall_of_fame`` entry (see the
    module docstring on why each is in the mix), ``games_per_benchmark``
    games each, all at DEEP_LEVEL, spread across every CPU core in one
    shared pool for the whole generation. Returns each genome's total
    fitness (see _score — outcome plus a margin-of-victory refinement,
    not flat win/loss/draw points), same order as ``genomes`` — this
    *is* the fitness CMA-ES searches on."""
    opponents = list(BENCHMARKS.values()) + [incumbent] + hall_of_fame
    tasks = []
    for genome_index, genome in enumerate(genomes):
        for opponent in opponents:
            for i in range(games_per_benchmark):
                spec = build_fleet_spec(DEEP_LEVEL.number)
                tasks.append((genome_index, i % 2 == 0, genome, opponent, spec))

    points = [0.0] * len(genomes)
    started = time.monotonic()
    with multiprocessing.Pool() as pool:
        for completed, (genome_index, outcome, margin) in enumerate(
                pool.imap_unordered(_play_one, tasks), start=1):
            points[genome_index] += _score(outcome, margin)
            if completed % 10 == 0 or completed == len(tasks):
                elapsed = time.monotonic() - started
                remaining = len(tasks) - completed
                eta = (elapsed / completed) * remaining if completed else 0.0
                print(f"    {completed}/{len(tasks)} games played "
                     f"({format_duration(elapsed)} elapsed, "
                     f"~{format_duration(eta)} left)", flush=True)
    return points


def checkpoint(weights: Weights, games: int = CHECKPOINT_GAMES,
              ) -> dict[str, tuple[int, int, int]]:
    """Play ``weights`` against every benchmark bot, ``games`` games
    each, at DEEP_LEVEL, and return each bot's own
    ``(wins, losses, draws)`` from ``weights``' side — the clear,
    directly-readable "how good is this actually" report the module
    docstring points to, distinct from CMA-ES's own noisier internal
    fitness signal."""
    results = {}
    with multiprocessing.Pool() as pool:
        for bot_name, bot in BENCHMARKS.items():
            wins, losses, draws = play_round(
                pool, _play_game, weights, bot, games,
                label=f"checkpoint vs {bot_name}",
                a_name="incumbent", b_name=bot_name)
            results[bot_name] = (wins, losses, draws)
    return results


def _print_checkpoint(weights: Weights, games: int = CHECKPOINT_GAMES) -> None:
    header = f"\nCheckpoint — incumbent vs every benchmark ({games} games each):"
    print(header, flush=True)
    results = checkpoint(weights, games)
    lines = [header]
    for bot_name, (wins, losses, draws) in results.items():
        rate = wins / games if games else 0.0
        line = f"  vs {bot_name:<12} {wins:>2}W-{losses:>2}L-{draws:>2}D  ({rate:.0%})"
        print(line, flush=True)
        lines.append(line)
    with RESULTS_PATH.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _clean_files() -> None:
    """Remove every file a fresh run would otherwise overwrite or
    append to piecemeal (RESULTS_PATH gets truncated at the start of a
    fresh run_cma_es call regardless, but LOG_PATH/BEST_WEIGHTS_PATH/
    STATE_PATH don't) — so nothing left over from an earlier, unrelated
    run can ever get spliced into this one's history."""
    for path in (RESULTS_PATH, LOG_PATH, BEST_WEIGHTS_PATH, STATE_PATH,
                HALL_OF_FAME_PATH):
        path.unlink(missing_ok=True)


def _load_hall_of_fame() -> list[Weights]:
    if not HALL_OF_FAME_PATH.exists():
        return []
    with HALL_OF_FAME_PATH.open(encoding="utf-8") as f:
        return [Weights(**fields) for fields in json.load(f)]


def _save_hall_of_fame(hall_of_fame: list[Weights]) -> None:
    with HALL_OF_FAME_PATH.open("w", encoding="utf-8") as f:
        json.dump([vars(genome) for genome in hall_of_fame], f)


def _add_to_hall_of_fame(hall_of_fame: list[Weights],
                         incumbent: Weights) -> None:
    """Append ``incumbent`` to ``hall_of_fame`` in place, trimming to
    HALL_OF_FAME_SIZE by dropping the *oldest* entries first (FIFO) —
    the newest snapshots stay, since they're the closest to what the
    population might otherwise start forgetting how to beat."""
    hall_of_fame.append(incumbent)
    del hall_of_fame[:-HALL_OF_FAME_SIZE]


def run(population_size: int = POPULATION_SIZE, generations: int = GENERATIONS,
       games_per_benchmark: int = GAMES_PER_BENCHMARK, sigma0: float = SIGMA0,
       checkpoint_every: int = CHECKPOINT_EVERY, resume: bool = True,
       seed: int | None = None) -> Weights:
    """Run CMA-ES for ``generations`` generations, checkpointing the
    incumbent's own per-benchmark record every ``checkpoint_every``
    generations, and always promote the final incumbent into
    DEFAULT_WEIGHTS — no gate, see the module docstring. Returns the
    final incumbent.

    ``resume`` (default True): if STATE_PATH already holds a saved,
    in-progress run (see spokebound.ai.cma_es.run_cma_es's own
    ``state_path``, saved fresh after every single generation), this
    continues it from its last completed generation instead of
    starting over — a crash or interruption then loses at most the
    generation in progress. Pass ``resume=False`` (the --fresh
    command-line flag below) to ignore any saved progress and start
    completely over instead; either way, a genuinely fresh start (no
    saved state to resume, or resume explicitly declined) first cleans
    out every file the old run touched, so nothing from it can linger
    and confuse the new one (see _clean_files).
    """
    if not resume or not STATE_PATH.exists():
        _clean_files()

    generation_count = 0
    hall_of_fame = _load_hall_of_fame()

    def evaluate_population(genomes: list[Weights],
                            incumbent: Weights) -> list[float]:
        nonlocal generation_count
        generation_count += 1
        fitnesses = _evaluate_population(genomes, incumbent, hall_of_fame,
                                        games_per_benchmark)
        if (checkpoint_every and generation_count % checkpoint_every == 0):
            _print_checkpoint(incumbent)
        if (HALL_OF_FAME_EVERY and generation_count % HALL_OF_FAME_EVERY == 0):
            _add_to_hall_of_fame(hall_of_fame, incumbent)
            _save_hall_of_fame(hall_of_fame)
            print(f"  (added this generation's incumbent to the hall of "
                 f"fame — now {len(hall_of_fame)} entr"
                 f"{'y' if len(hall_of_fame) == 1 else 'ies'})", flush=True)
        return fitnesses

    incumbent = run_cma_es(
        label="WEIGHT", seed_genome=DEFAULT_WEIGHTS, sigma0=sigma0,
        evaluate_population=evaluate_population, generations=generations,
        population_size=population_size, results_path=RESULTS_PATH,
        log_path=LOG_PATH, state_path=STATE_PATH, resume=resume, seed=seed)

    with BEST_WEIGHTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(vars(incumbent), f, indent=2)

    print("\nFinal incumbent:", flush=True)
    print(incumbent.describe_diff(DEFAULT_WEIGHTS), flush=True)
    _print_checkpoint(incumbent)

    promote(incumbent)
    message = "\nIncumbent promoted into DEFAULT_WEIGHTS."
    print(message, flush=True)
    with RESULTS_PATH.open("a", encoding="utf-8") as f:
        f.write(message + "\n")
    HALL_OF_FAME_PATH.unlink(missing_ok=True)
    # The run finished cleanly — nothing left to resume, and leaving
    # this here would make the *next* run think there was.
    STATE_PATH.unlink(missing_ok=True)
    return incumbent


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fresh", action="store_true",
        help="Ignore any saved in-progress run and start over from scratch")
    args = parser.parse_args()
    run(resume=not args.fresh)
