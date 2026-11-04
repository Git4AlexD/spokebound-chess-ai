"""Fleet-building tuning for the pregame-setup "brain" (see
spokebound.ai.config.FleetRules; spokebound.ai.evolve is this same
approach's twin for Weights, the actual-game brain) — the same CMA-ES-
at-Impossible-depth approach as spokebound.ai.evolve (see its own
module docstring for the full reasoning), applied to FleetRules
instead: every game, every generation, played at DEEP_LEVEL —
LEVELS[10], Impossible — against every fixed benchmark bot in
spokebound.ai.benchmarks, the current incumbent (CMA-ES's own search-
distribution mean), *and* every entry in the hall of fame (a small,
capped pool of past incumbents — see HALL_OF_FAME_EVERY/
HALL_OF_FAME_SIZE), scored by margin of victory as well as outcome (see
_score) — see spokebound.ai.evolve's own module docstring for the full
reasoning behind each of those four pieces. No shallow proxy, no rungs.

Weights (the actual-game brain) is held fixed for every game here, on
both sides — the only thing under test is which FleetRules builds the
stronger fleet, so each side gets to build its *own* fleet from its
*own* rules (unlike spokebound.ai.evolve, which holds fleet-building
fixed and gives both sides the same fleet instead, to isolate Weights
the other way). Fixed at spokebound.ai.evolve's own most recent
champion (evolved_champion.json), not DEFAULT_WEIGHTS — fleet-building
should be judged against the best gameplay currently known — falling
back to DEFAULT_WEIGHTS only if evolve.py has never been run at all in
this checkout. See GAMEPLAY_WEIGHTS.

Not run as part of the app or the test suite — a standalone session you
start on purpose:

    python -m spokebound.ai.evolve_fleet
    python -m spokebound.ai.evolve_fleet --fresh

Crash-resilient by default, the same way as spokebound.ai.evolve: the
whole search distribution is saved to STATE_PATH after every single
generation, so re-running the plain command above picks up from the
last completed generation instead of losing everything. Pass ``--fresh``
to discard any saved progress and start over instead — either way, an
actual fresh start first cleans out every file the previous run
touched, so nothing from it can linger into the new one.

Always promotes the final incumbent straight into
spokebound.ai.config.DEFAULT_FLEET_RULES via spokebound.ai.promote once
it's done — DEFAULT_FLEET_RULES is a seed used only to start CMA-ES's
very first search distribution (see MEAN0), never a fallback a run can
leave untouched.

See spokebound.ai.evolve's own module docstring for the same speed/
noise trade in POPULATION_SIZE/GENERATIONS/GAMES_PER_BENCHMARK.
"""

import json
import multiprocessing
import time
from pathlib import Path

from spokebound.ai.benchmarks import BENCHMARK_WEIGHTS, BENCHMARKS, RULES_FOR_BOT
from spokebound.ai.build import build_fleet_spec, materialize_fleet
from spokebound.ai.cma_es import run_cma_es
from spokebound.ai.config import (
    DEFAULT_FLEET_RULES,
    DEFAULT_WEIGHTS,
    FleetRules,
    Weights,
)
from spokebound.ai.evolve import BEST_WEIGHTS_PATH as _EVOLVED_WEIGHTS_PATH
from spokebound.ai.levels import LEVELS
from spokebound.ai.promote import apply as promote
from spokebound.ai.promote import load as _load_champion
from spokebound.ai.search import choose_turn_at
from spokebound.ai.selfplay import format_duration, play_full_game, play_round
from spokebound.config import BUILD_BUDGET
from spokebound.model.pieces import Player

POPULATION_SIZE = 6
GENERATIONS = 20
GAMES_PER_BENCHMARK = 2
SIGMA0 = 0.5
CHECKPOINT_EVERY = 5
CHECKPOINT_GAMES = 6
DEEP_LEVEL = LEVELS[10]
# See spokebound.ai.evolve's own HALL_OF_FAME_EVERY/HALL_OF_FAME_SIZE.
HALL_OF_FAME_EVERY = 5
HALL_OF_FAME_SIZE = 3

RESULTS_PATH = Path(__file__).with_name("evolution_fleet_results.txt")
LOG_PATH = Path(__file__).with_name("evolution_fleet_log.jsonl")
BEST_RULES_PATH = Path(__file__).with_name("evolved_fleet_rules.json")
STATE_PATH = Path(__file__).with_name("cma_es_fleet_state.json")
HALL_OF_FAME_PATH = Path(__file__).with_name("hall_of_fame_fleet.json")


def _gameplay_weights() -> Weights:
    """The Weights held fixed on both sides while tuning FleetRules:
    spokebound.ai.evolve's own most recent champion, if it's been run
    at least once in this checkout, falling back to DEFAULT_WEIGHTS if
    evolve.py has never been run here. Read once, at import time: each
    worker process re-imports this module fresh anyway, so every game
    in a run sees the same value.
    """
    if _EVOLVED_WEIGHTS_PATH.exists():
        return _load_champion(_EVOLVED_WEIGHTS_PATH, Weights)
    return DEFAULT_WEIGHTS


GAMEPLAY_WEIGHTS = _gameplay_weights()


def _fleet_for(contestant, player: Player) -> list:
    rules = contestant if isinstance(contestant, FleetRules) else RULES_FOR_BOT[contestant]
    return materialize_fleet(build_fleet_spec(DEEP_LEVEL.number, rules=rules), player)


def _chooser(contestant):
    if isinstance(contestant, FleetRules):
        return lambda game: choose_turn_at(game, DEEP_LEVEL, GAMEPLAY_WEIGHTS)
    return contestant  # a bare bot callable


def _weights_for(contestant) -> Weights:
    return GAMEPLAY_WEIGHTS if isinstance(contestant, FleetRules) else BENCHMARK_WEIGHTS


def _play_game(a, b) -> Player | None:
    """Play one game at DEEP_LEVEL between two contestants, each either
    a FleetRules (builds its own fleet from its own rules, searches and
    spends bounty under GAMEPLAY_WEIGHTS) or a fixed benchmark bot
    (builds the fleet matching its own strategy, see RULES_FOR_BOT, and
    searches under its own frozen BENCHMARK_WEIGHTS)."""
    by_player = {Player.ORANGE: a, Player.WHITE: b}

    def choose_for(player: Player):
        return _chooser(by_player[player])

    def weights_for(player: Player) -> Weights:
        return _weights_for(by_player[player])

    return play_full_game(
        _fleet_for(a, Player.ORANGE), _fleet_for(b, Player.WHITE), choose_for, weights_for
    ).winner


def _play_one(task: tuple) -> tuple[int, str, int]:
    """Run in a worker process — see _evaluate_population. ``task`` is
    ``(genome_index, a_is_orange, genome, opponent)`` — ``opponent``
    either a fixed benchmark bot or the current incumbent/hall-of-fame
    FleetRules, the two things _chooser/_fleet_for already handle
    generically; returns ``(genome_index, "win"/"loss"/"draw", margin)``
    from ``genome``'s own side, where ``margin`` is its own final score
    minus its opponent's (see spokebound.ai.selfplay.GameResult) — a
    finer-grained signal than win/loss/draw alone, see _score."""
    genome_index, a_is_orange, genome, opponent = task
    a, b = (genome, opponent) if a_is_orange else (opponent, genome)
    by_player = {Player.ORANGE: a, Player.WHITE: b}

    def choose_for(player: Player):
        return _chooser(by_player[player])

    def weights_for(player: Player) -> Weights:
        return _weights_for(by_player[player])

    result = play_full_game(
        _fleet_for(a, Player.ORANGE), _fleet_for(b, Player.WHITE), choose_for, weights_for
    )
    genome_score = result.orange_score if a_is_orange else result.white_score
    opponent_score = result.white_score if a_is_orange else result.orange_score
    margin = genome_score - opponent_score
    if result.winner is None:
        return (genome_index, "draw", margin)
    genome_won = (a_is_orange and result.winner is Player.ORANGE) or (
        not a_is_orange and result.winner is Player.WHITE
    )
    return (genome_index, "win" if genome_won else "loss", margin)


def _score(outcome: str, margin: int) -> float:
    """See spokebound.ai.evolve's own _score — the identical margin-of-
    victory refinement, applied here to FleetRules' own games."""
    base = {"win": 2.0, "draw": 1.0, "loss": 0.0}[outcome]
    bonus = max(-0.49, min(0.49, margin / (2 * BUILD_BUDGET)))
    return base + bonus


def _evaluate_population(
    genomes: list[FleetRules],
    incumbent: FleetRules,
    hall_of_fame: list[FleetRules],
    games_per_benchmark: int = GAMES_PER_BENCHMARK,
) -> list[float]:
    """Play every one of ``genomes`` against every benchmark bot, the
    current ``incumbent``, and every ``hall_of_fame`` entry,
    ``games_per_benchmark`` games each, all at DEEP_LEVEL, spread across
    every CPU core in one shared pool for the whole generation. Returns
    each genome's total fitness (see _score), same order as ``genomes``
    — this *is* the fitness CMA-ES searches on."""
    opponents = [*BENCHMARKS.values(), incumbent, *hall_of_fame]
    tasks = []
    for genome_index, genome in enumerate(genomes):
        for opponent in opponents:
            for i in range(games_per_benchmark):
                tasks.append((genome_index, i % 2 == 0, genome, opponent))

    points = [0.0] * len(genomes)
    started = time.monotonic()
    with multiprocessing.Pool() as pool:
        for completed, (genome_index, outcome, margin) in enumerate(
            pool.imap_unordered(_play_one, tasks), start=1
        ):
            points[genome_index] += _score(outcome, margin)
            if completed % 10 == 0 or completed == len(tasks):
                elapsed = time.monotonic() - started
                remaining = len(tasks) - completed
                eta = (elapsed / completed) * remaining if completed else 0.0
                print(
                    f"    {completed}/{len(tasks)} games played "
                    f"({format_duration(elapsed)} elapsed, "
                    f"~{format_duration(eta)} left)",
                    flush=True,
                )
    return points


def checkpoint(
    rules: FleetRules,
    games: int = CHECKPOINT_GAMES,
) -> dict[str, tuple[int, int, int]]:
    """Play ``rules`` against every benchmark bot, ``games`` games each,
    at DEEP_LEVEL, and return each bot's own
    ``(wins, losses, draws)`` from ``rules``' side."""
    results = {}
    with multiprocessing.Pool() as pool:
        for bot_name, bot in BENCHMARKS.items():
            wins, losses, draws = play_round(
                pool,
                _play_game,
                rules,
                bot,
                games,
                label=f"checkpoint vs {bot_name}",
                a_name="incumbent",
                b_name=bot_name,
            )
            results[bot_name] = (wins, losses, draws)
    return results


def _print_checkpoint(rules: FleetRules, games: int = CHECKPOINT_GAMES) -> None:
    header = f"\nCheckpoint — incumbent vs every benchmark ({games} games each):"
    print(header, flush=True)
    results = checkpoint(rules, games)
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
    append to piecemeal — see spokebound.ai.evolve's own _clean_files,
    the same idea for FleetRules' own output files."""
    for path in (RESULTS_PATH, LOG_PATH, BEST_RULES_PATH, STATE_PATH, HALL_OF_FAME_PATH):
        path.unlink(missing_ok=True)


def _load_hall_of_fame() -> list[FleetRules]:
    if not HALL_OF_FAME_PATH.exists():
        return []
    with HALL_OF_FAME_PATH.open(encoding="utf-8") as f:
        return [FleetRules(**fields) for fields in json.load(f)]


def _save_hall_of_fame(hall_of_fame: list[FleetRules]) -> None:
    with HALL_OF_FAME_PATH.open("w", encoding="utf-8") as f:
        json.dump([vars(genome) for genome in hall_of_fame], f)


def _add_to_hall_of_fame(hall_of_fame: list[FleetRules], incumbent: FleetRules) -> None:
    """See spokebound.ai.evolve's own _add_to_hall_of_fame — the
    identical FIFO-capped append, applied here to FleetRules."""
    hall_of_fame.append(incumbent)
    del hall_of_fame[:-HALL_OF_FAME_SIZE]


def run(
    population_size: int = POPULATION_SIZE,
    generations: int = GENERATIONS,
    games_per_benchmark: int = GAMES_PER_BENCHMARK,
    sigma0: float = SIGMA0,
    checkpoint_every: int = CHECKPOINT_EVERY,
    resume: bool = True,
    seed: int | None = None,
) -> FleetRules:
    """Run CMA-ES for ``generations`` generations, checkpointing the
    incumbent's own per-benchmark record every ``checkpoint_every``
    generations, and always promote the final incumbent into
    DEFAULT_FLEET_RULES — no gate, see the module docstring. Returns the
    final incumbent.

    ``resume`` (default True): see spokebound.ai.evolve.run's own
    ``resume`` argument — the same crash-resilience, via STATE_PATH.
    """
    if not resume or not STATE_PATH.exists():
        _clean_files()

    generation_count = 0
    hall_of_fame = _load_hall_of_fame()

    def evaluate_population(genomes: list[FleetRules], incumbent: FleetRules) -> list[float]:
        nonlocal generation_count
        generation_count += 1
        fitnesses = _evaluate_population(genomes, incumbent, hall_of_fame, games_per_benchmark)
        if checkpoint_every and generation_count % checkpoint_every == 0:
            _print_checkpoint(incumbent)
        if HALL_OF_FAME_EVERY and generation_count % HALL_OF_FAME_EVERY == 0:
            _add_to_hall_of_fame(hall_of_fame, incumbent)
            _save_hall_of_fame(hall_of_fame)
            print(
                f"  (added this generation's incumbent to the hall of "
                f"fame — now {len(hall_of_fame)} entr"
                f"{'y' if len(hall_of_fame) == 1 else 'ies'})",
                flush=True,
            )
        return fitnesses

    incumbent = run_cma_es(
        label="FLEET-BUILDING RULES",
        seed_genome=DEFAULT_FLEET_RULES,
        sigma0=sigma0,
        evaluate_population=evaluate_population,
        generations=generations,
        population_size=population_size,
        results_path=RESULTS_PATH,
        log_path=LOG_PATH,
        state_path=STATE_PATH,
        resume=resume,
        seed=seed,
    )

    with BEST_RULES_PATH.open("w", encoding="utf-8") as f:
        json.dump(vars(incumbent), f, indent=2)

    print("\nFinal incumbent:", flush=True)
    print(incumbent.describe_diff(DEFAULT_FLEET_RULES), flush=True)
    _print_checkpoint(incumbent)

    promote(incumbent)
    message = "\nIncumbent promoted into DEFAULT_FLEET_RULES."
    print(message, flush=True)
    with RESULTS_PATH.open("a", encoding="utf-8") as f:
        f.write(message + "\n")
    STATE_PATH.unlink(missing_ok=True)
    HALL_OF_FAME_PATH.unlink(missing_ok=True)
    return incumbent


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fresh", action="store_true", help="Ignore any saved in-progress run and start over from scratch"
    )
    args = parser.parse_args()
    run(resume=not args.fresh)
