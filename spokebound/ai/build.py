"""AI fleet building — the pregame-setup "brain" (see
spokebound.ai.config.FleetRules for its tunable knobs, and
spokebound.ai.evolve_fleet for how they're tuned; entirely separate from
Weights, the actual-game "brain" spokebound.ai.evolve tunes).

Every fleet is generated straight from ``rules``: each point of the
build budget is spent on a direction (steered by that direction's own
bias, blended with a little pure randomness — see
FleetRules.variety/_weighted_direction) and a piece (steered by
FleetRules.concentration/_weighted_piece_index) — no hand-authored
"styles" to pick among any more (see AI_STYLES's removal), and no
building several candidates and keeping the best either. A level that
isn't given ``rules`` explicitly gets exactly one fleet, built from a
single, level-appropriate blend of NEUTRAL_FLEET_RULES and
DEFAULT_FLEET_RULES (see _rules_for_level and
spokebound.ai.levels.Level.pregame_skill) — a genuinely weaker fleet at
a low level, not a noisier sample of the strongest one.

There is no way for the AI to look at the opponent's own built fleet
before choosing its own any more — the counter-picking that used to let
the top few levels do that is gone.
"""

import random

from spokebound.ai.config import (
    DEFAULT_FLEET_RULES,
    NEUTRAL_FLEET_RULES,
    FleetRules,
)
from spokebound.ai.levels import LEVELS
from spokebound.config import FLEET_SIZE
from spokebound.model.pieces import SPOKE_COUNT, Piece, Player
from spokebound.model.spending import FleetBuilder

# How many times _allocate_points retries a single point's spend (a
# different random direction/piece each time) before giving up on it —
# spending bumps into an already-unlimited spoke or an already-capped
# piece often enough, especially as a fleet fills up, that trying just
# once would leave a chunk of the budget unspent for no real reason.
_SPEND_ATTEMPTS = 5

# Field name for each spoke index, in spoke order — see
# spokebound.model.pieces.DIRECTION_NAMES, which this mirrors exactly.
_DIRECTION_BIAS_FIELDS = (
    "bias_n", "bias_ne", "bias_e", "bias_se",
    "bias_s", "bias_sw", "bias_w", "bias_nw",
)

Spec = list[list[int]]  # one fleet's raw spoke levels, not yet owned by anyone


def build_fleet_spec(difficulty: int, rules: FleetRules | None = None) -> Spec:
    """Return a finished fleet's raw spoke-level spec — everything
    build_fleet does except deciding whose it is (see materialize_fleet),
    so the very same design can be materialized for either side, e.g. to
    give two self-play contestants an identical fleet (see
    spokebound.ai.evolve) rather than two independently-random ones.

    ``difficulty`` is a level number — one of the 10 in
    spokebound.ai.levels.LEVELS, or a custom profile's own number (see
    e.g. spokebound.ai.selfplay.SELF_PLAY_LEVEL). Pass ``rules``
    explicitly to build from it exactly as given, with no regard for
    ``difficulty`` at all (this is how spokebound.ai.evolve_fleet tests
    a candidate FleetRules at full strength); leave it out to build from
    whatever that level's own pregame_skill blends to instead — see
    _rules_for_level.
    """
    if rules is None:
        rules = _rules_for_level(difficulty)
    return _build_one_spec(rules)


def _rules_for_level(difficulty: int) -> FleetRules:
    """The FleetRules a bare level number builds from when no explicit
    ``rules`` is given: NEUTRAL_FLEET_RULES blended toward
    DEFAULT_FLEET_RULES by that level's own pregame_skill (0.0 = pure
    chance, 1.0 = the real, fully-evolved rules) — see
    FleetRules.blended. A number that isn't one of the 10 real levels
    (a custom profile like spokebound.ai.selfplay.SELF_PLAY_LEVEL) gets
    DEFAULT_FLEET_RULES outright, at full strength."""
    level = LEVELS.get(difficulty)
    if level is None:
        return DEFAULT_FLEET_RULES
    return NEUTRAL_FLEET_RULES.blended(DEFAULT_FLEET_RULES, level.pregame_skill)


def materialize_fleet(spec: Spec, owner: Player) -> list[Piece]:
    """Return ``spec`` built as an actual, owned fleet for ``owner``."""
    builder = FleetBuilder(owner)
    builder.load_preset(spec)
    return builder.pieces


def build_fleet(difficulty: int, owner: Player,
               rules: FleetRules | None = None) -> list[Piece]:
    """Return a finished fleet for ``owner``, playing at ``difficulty``
    (a level number — see spokebound.ai.levels.LEVELS and
    build_fleet_spec for what ``rules`` overrides)."""
    return materialize_fleet(build_fleet_spec(difficulty, rules), owner)


def _build_one_spec(rules: FleetRules) -> Spec:
    """Build one fleet from scratch, driven entirely by ``rules``' own
    per-direction bias and piece concentration."""
    builder = FleetBuilder(Player.ORANGE)  # owner is discarded below
    # Every piece needs at least one level-1 spoke to have a legal move
    # at all — reserved up front, before the rest of the budget is
    # spent freely, so it can't run dry before every piece gets its
    # share (the same reasoning the AI_STYLES generator this replaced
    # used to follow).
    for index in range(FLEET_SIZE):
        builder.adjust(index, _weighted_direction(rules), 1)
    _allocate_points(builder, builder.remaining, rules)
    return [list(piece.spokes) for piece in builder.pieces]


def _allocate_points(builder: FleetBuilder, points: int,
                     rules: FleetRules) -> None:
    """Spend ``points`` one at a time: each point picks a direction
    (biased by ``rules``' own per-direction weights, blended with some
    uniform randomness — see _weighted_direction) and a piece (weighted
    by ``rules``.concentration — see _weighted_piece_index), then raises
    that piece's spoke in that direction one level. A spend that can't
    land (already unlimited, already at the piece's cost cap) is
    retried a few times against a fresh random pick rather than simply
    lost, so the budget doesn't end up under-spent just because an
    early pick happened to be unlucky."""
    for _ in range(points):
        for _attempt in range(_SPEND_ATTEMPTS):
            spoke = _weighted_direction(rules)
            index = _weighted_piece_index(builder, rules.concentration)
            if builder.adjust(index, spoke, 1):
                break


def _weighted_direction(rules: FleetRules) -> int:
    """Pick a spoke direction, biased by ``rules``' own per-direction
    weights, blended with a little uniform randomness (rules.variety)
    so a run of the very same rules doesn't always build the identical
    fleet."""
    biases = [max(0.01, getattr(rules, field))
             for field in _DIRECTION_BIAS_FIELDS]
    variety = min(1.0, max(0.0, rules.variety))
    weights = [(1 - variety) * bias + variety for bias in biases]
    return random.choices(range(SPOKE_COUNT), weights=weights, k=1)[0]


def _weighted_piece_index(builder: FleetBuilder, concentration: float) -> int:
    """Pick a piece index to spend on, weighted by its current cost
    raised to ``concentration - 1`` — neutral (every piece equally
    likely) at 1.0 (cost ** 0 == 1 regardless of cost), favouring
    whichever piece(s) already hold the most points above that,
    spreading more evenly below it."""
    costs = [piece.cost + 1 for piece in builder.pieces]  # +1: a 0-cost piece can still be picked
    weights = [cost ** (concentration - 1) for cost in costs]
    return random.choices(range(len(builder.pieces)), weights=weights, k=1)[0]
