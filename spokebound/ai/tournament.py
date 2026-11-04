"""Round-robin tournament between the 10 difficulty levels (see
spokebound.ai.levels.LEVELS), to check the difficulty ramp actually
holds up — a higher level should beat a lower one more often than not.

Not run automatically — a standalone session you start on purpose:

    python -m spokebound.ai.tournament

Every pair of levels plays GAMES_PER_MATCHUP games (two by default, one
per colour). Games run one at a time, so each one gets the same CPU as a
real game would. Levels above ~5 use a
real multi-second time budget per move (see LEVELS), so this can take a
long time — it prints progress as matchups finish, and results are
still meaningful if interrupted partway (finished matchups are shown;
GAMES_PER_MATCHUP can be lowered for a quicker, noisier run).
"""

import itertools
import time

from spokebound.ai.build import build_fleet
from spokebound.ai.levels import LEVELS
from spokebound.ai.search import choose_turn
from spokebound.ai.selfplay import play_full_game, play_round
from spokebound.model.pieces import Player

# How many games each pair of levels plays (split evenly between
# colours) — set this before starting a run.
GAMES_PER_MATCHUP = 2

# Which levels to include — defaults to the whole ladder (1-10), but
# this can be narrowed (e.g. range(1, 6)) for a much faster, still-
# useful run.
LEVELS_TO_TEST = range(1, 11)


def play_game(orange_level: int, white_level: int) -> Player | None:
    """Play one full game between two levels and return the winner, or
    ``None`` for a draw. See spokebound.ai.selfplay for the shared
    deploy-then-play-to-completion machinery this builds on. Each side's
    fleet-building (build_fleet), deployment (skill_for) and move search
    (choose_for) all use that side's own level, so a level's whole
    pregame setup is on trial here, not just its search depth."""
    orange_fleet = build_fleet(orange_level, Player.ORANGE)
    white_fleet = build_fleet(white_level, Player.WHITE)
    by_player = {Player.ORANGE: orange_level, Player.WHITE: white_level}

    def choose_for(player: Player):
        return lambda game: choose_turn(game, by_player[player])

    def skill_for(player: Player) -> float:
        return LEVELS[by_player[player]].pregame_skill

    return play_full_game(orange_fleet, white_fleet, choose_for,
                          skill_for=skill_for).winner


class _SerialPool:
    """Runs play_round's games in this process, one after another, so the
    tournament uses exactly the code and CPU a real game does."""

    def imap_unordered(self, func, tasks):
        return map(func, tasks)


def play_matchup(pool: _SerialPool, a: int, b: int,
                 games: int = GAMES_PER_MATCHUP) -> tuple[int, int, int]:
    """Play ``games`` games between levels ``a`` and ``b``, split evenly
    between colours. Returns ``(a_wins, b_wins, draws)``."""
    return play_round(pool, play_game, a, b, games,
                      label=f"{a} vs {b}", a_name=str(a), b_name=str(b))


def run(levels=LEVELS_TO_TEST, games_per_matchup: int = GAMES_PER_MATCHUP,
       adjacent_only: bool = False
       ) -> dict[tuple[int, int], tuple[int, int, int]]:
    """Play every pair of ``levels`` against each other, printing progress
    as each matchup finishes. Each pair plays ``games_per_matchup`` games
    (two by default), split evenly between the two colours. With
    ``adjacent_only``, only consecutive levels play each other. Returns
    ``{(a, b): (a_wins, b_wins, draws)}`` for every pair, ``a < b``.
    """
    ordered = sorted(levels)
    pairs = (list(itertools.pairwise(ordered)) if adjacent_only
             else list(itertools.combinations(ordered, 2)))
    print(f"Tournament: {len(pairs)} matchups x {games_per_matchup} games "
         f"= {len(pairs) * games_per_matchup} games total, one at a time",
         flush=True)
    results: dict[tuple[int, int], tuple[int, int, int]] = {}
    pool = _SerialPool()
    for index, (a, b) in enumerate(pairs, start=1):
        started = time.monotonic()
        a_wins, b_wins, draws = play_matchup(pool, a, b, games_per_matchup)
        elapsed = time.monotonic() - started
        results[(a, b)] = (a_wins, b_wins, draws)
        print(f"[{index}/{len(pairs)}] Level {a} ({LEVELS[a].name}) "
             f"vs Level {b} ({LEVELS[b].name}): "
             f"{a_wins}-{b_wins}-{draws} ({elapsed:.0f}s)", flush=True)
    return results


def summarize(results: dict[tuple[int, int], tuple[int, int, int]],
             levels=LEVELS_TO_TEST) -> None:
    """Print total wins/losses/draws and a win rate per level, across
    every matchup it played."""
    totals = {level: [0, 0, 0] for level in levels}  # wins, losses, draws
    head_to_head: dict[tuple[int, int], str] = {}
    for (a, b), (a_wins, b_wins, draws) in results.items():
        totals[a][0] += a_wins
        totals[a][1] += b_wins
        totals[a][2] += draws
        totals[b][0] += b_wins
        totals[b][1] += a_wins
        totals[b][2] += draws
        head_to_head[(a, b)] = f"{a_wins}-{b_wins}" + (f"-{draws}" if draws else "")
        head_to_head[(b, a)] = f"{b_wins}-{a_wins}" + (f"-{draws}" if draws else "")
    ordered = sorted(levels)
    print("\nHead-to-head (row's wins-losses against column):", flush=True)
    print("      " + "".join(f"{level:>8}" for level in ordered), flush=True)
    for row in ordered:
        cells = [f"{'-' if row == col else head_to_head.get((row, col), ''):>8}"
                 for col in ordered]
        print(f"{row:>5} " + "".join(cells), flush=True)
    print("\nStandings (by win rate):", flush=True)
    ranked = sorted(totals.items(),
                    key=lambda item: item[1][0] / max(1, sum(item[1])),
                    reverse=True)
    for level, (wins, losses, draws) in ranked:
        games = wins + losses + draws
        rate = wins / games if games else 0.0
        print(f"  Level {level:>2} {LEVELS[level].name:<12} "
             f"{wins:>3}-{losses:>3}-{draws:>3}  ({rate:.0%})", flush=True)




if __name__ == "__main__":
    summarize(run())
