"""Tunable AI parameters, kept apart from the AI logic itself so tuning
only ever produces new data here, never edits the search, evaluation or
build code. Two separate "brains" live here, each with its own
evolutionary tuner:

    Weights      The actual-game brain: evaluation weights driving move
                 search, upgrade spending and deployment (evaluate()'s
                 features) — tuned by :mod:`spokebound.ai.evolve`.
    FleetRules   The pregame-setup brain: which fleet-building style to
                 favour and how aggressively to concentrate spending on
                 fewer pieces — tuned by :mod:`spokebound.ai.evolve_fleet`.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Weights:
    """One full set of evaluation weights — a "brain" self-play tuning
    can nudge and compare against another. Positive weights reward a
    feature that's good for whoever's being scored; the raw features
    themselves (see :mod:`spokebound.ai.evaluate`) are signed so every
    weight here reads as "how much this matters," not which way it cuts.
    """

    material: float = 1.0
    # Scaled so one square of Captain progress is worth about as much as
    # this many points of material — see _captain_distance in
    # evaluate.py. Scored across the whole board, not just near the
    # goal, so advancing (or blocking) always matters, with an added
    # bonus once a Captain is within striking range.
    captain_distance: float = 1.2
    captain_safety: float = 1.5
    # How many of this player's pieces hold or could reach the goal
    # square, minus the opponent's — see _goal_attackers in evaluate.py.
    goal_attackers: float = 1.0
    # The sharp "nothing is stopping them" alarm: fires only once the
    # goal has no defenders at all, on top of (not instead of)
    # captain_distance and goal_attackers — see _goal_urgency in
    # evaluate.py.
    goal_urgency: float = 2.0
    # Control of the ring of 8 squares around the goal (not the goal
    # square itself) — a wider-lens companion to goal_attackers, so the
    # approaches can be cut off before a Captain is close enough for
    # goal_attackers or goal_urgency to see anything yet. Kept smaller
    # than goal_attackers since it's summed over 8 squares, not one.
    goal_area_control: float = 0.7
    bounty_risk: float = 1.3
    # Cost of this player's pieces under attack with nothing able to
    # recapture, minus the opponent's — see _piece_safety in
    # evaluate.py. Already in cost units like material, so this is
    # deliberately not weighted as heavily: it's about pending danger
    # (a piece that could still be saved), not material already lost.
    piece_safety: float = 1.6
    # This player's Captain's safe escape squares, minus the opponent's
    # — see _captain_escape in evaluate.py. A king-mobility-style
    # signal alongside captain_safety's attacker count.
    captain_escape: float = 1.5
    mobility: float = 0.3

    def field_names(self) -> tuple[str, ...]:
        """Return the names of every weight, for tuning to pick among."""
        return tuple(self.__dataclass_fields__)

    def nudged(self, field: str, factor: float) -> "Weights":
        """Return a copy with one weight scaled by ``factor``."""
        return replace(self, **{field: getattr(self, field) * factor})

    def describe_diff(self, baseline: "Weights") -> str:
        """Return a human-readable, one-line-per-field comparison against
        ``baseline`` — every field's value and its percent change, so a
        tuning or evolution result's champion reads as "what actually
        changed" rather than a bare list of floats (see
        spokebound.ai.evolve and spokebound.ai.promote, which both use
        this against DEFAULT_WEIGHTS)."""
        lines = []
        for field in self.field_names():
            value, base = getattr(self, field), getattr(baseline, field)
            change = (value / base - 1) * 100 if base else 0.0
            arrow = "+" if change >= 0 else ""
            lines.append(f"   {field:<18} {value:6.3f}  ({arrow}{change:.0f}% vs. baseline)")
        return "\n".join(lines)


# The hand-picked starting point both play and tuning use until an
# evolutionary session (spokebound.ai.evolve) finds something that beats
# it — see promote.py for turning a winner into a new DEFAULT_WEIGHTS.
DEFAULT_WEIGHTS = Weights(
    material=2.5379759424307444,
    captain_distance=1.281836216324368,
    captain_safety=1.846642819881887,
    goal_attackers=1.6052073964078977,
    goal_urgency=2.636016233000172,
    goal_area_control=0.9627789900252213,
    bounty_risk=0.9901387765364001,
    piece_safety=0.8237648140681219,
    captain_escape=1.8832761113515597,
    mobility=0.01723705794854319,
)


@dataclass(frozen=True)
class FleetRules:
    """Tunable knobs for how a fleet gets built (see
    spokebound.ai.build) — the AI's pregame-setup "brain", entirely
    separate from Weights (its actual-game "brain"): nothing here
    affects a single move once play begins, and nothing in Weights
    affects which pieces get built in the first place.

    Bias is per compass direction — "N" is always forward, toward the
    opponent, whichever side of the board a piece's owner is actually
    on (the same relative convention spoke levels themselves already
    use — see spokebound.model.pieces.DIRECTION_NAMES). Forward and
    backward reach are not symmetric in this game: forward pressure
    threatens the goal and the opponent's Captain directly, backward
    reach mostly just covers your own — so this is a per-direction
    knob, not a single "aggression" dial, and evolution is free to
    discover (for instance) that points are worth far more spent
    forward than spent backward, rather than that being assumed here.
    """

    bias_n: float = 1.0
    bias_ne: float = 1.0
    bias_e: float = 1.0
    bias_se: float = 1.0
    bias_s: float = 1.0
    bias_sw: float = 1.0
    bias_w: float = 1.0
    bias_nw: float = 1.0
    # How strongly spending favours whichever piece(s) already hold the
    # most points, over spreading the budget evenly across the fleet:
    # 1.0 is neutral, above that concentrates further (fewer, bigger
    # pieces), below spreads wider (more, cheaper ones).
    concentration: float = 1.0
    # How much of each spend is pure uniform randomness rather than
    # steered by the biases above (0.0 = always follow bias, 1.0 =
    # bias ignored entirely) — so two fleets built from the very same
    # rules still aren't identical, and a real game against this level
    # doesn't always open the same way. See spokebound.ai.build
    # ._weighted_direction.
    variety: float = 0.15

    def field_names(self) -> tuple[str, ...]:
        """Return the names of every rule, for tuning to pick among."""
        return tuple(self.__dataclass_fields__)

    def nudged(self, field: str, factor: float) -> "FleetRules":
        """Return a copy with one rule scaled by ``factor``."""
        return replace(self, **{field: getattr(self, field) * factor})

    def blended(self, other: "FleetRules", t: float) -> "FleetRules":
        """Return the point ``t`` of the way from ``self`` (t=0) to
        ``other`` (t=1) across every field, linearly. Used to turn one
        evolved FleetRules into a genuinely weaker (or stronger) policy
        for a given difficulty level — see
        spokebound.ai.levels.Level.pregame_skill and
        spokebound.ai.build._rules_for_level — rather than sampling the
        same fully-evolved rules more or less carefully."""
        return replace(
            self,
            **{
                name: getattr(self, name) + t * (getattr(other, name) - getattr(self, name))
                for name in self.field_names()
            },
        )

    def describe_diff(self, baseline: "FleetRules") -> str:
        """Same as Weights.describe_diff, for FleetRules."""
        lines = []
        for field in self.field_names():
            value, base = getattr(self, field), getattr(baseline, field)
            change = (value / base - 1) * 100 if base else 0.0
            arrow = "+" if change >= 0 else ""
            lines.append(f"   {field:<18} {value:6.3f}  ({arrow}{change:.0f}% vs. baseline)")
        return "\n".join(lines)


# The hand-picked starting point for fleet-building — see
# spokebound.ai.evolve_fleet for how this gets tuned, and promote.py for
# turning a winner into a new DEFAULT_FLEET_RULES.
DEFAULT_FLEET_RULES = FleetRules(
    bias_n=1.1953864652711332,
    bias_ne=1.0434,
    bias_e=0.05,
    bias_se=0.364,
    bias_s=0.01,
    bias_sw=0.364,
    bias_w=0.05,
    bias_nw=1.0434,
    concentration=-0.4642686805204102,
    variety=0.15,
)

# The "knows nothing" end of FleetRules.blended: every direction equally
# likely, no concentration on already-rich pieces, and variety=1.0 so
# bias is ignored entirely — pure chance, not a weaker echo of whatever
# DEFAULT_FLEET_RULES currently is. Every difficulty level blends
# between this and DEFAULT_FLEET_RULES (see Level.pregame_skill), so a
# future, stronger DEFAULT_FLEET_RULES automatically raises every
# level's ceiling without this floor moving at all.
NEUTRAL_FLEET_RULES = FleetRules(variety=1.0)

# Quiescence: once the main search bottoms out, keep following captures
# and checks (see search.py) until the position is quiet before scoring
# it, so a piece that looks safely won at the depth limit doesn't get
# credited when it's actually about to be recaptured. This caps how far
# a single such chain can extend, as a safety net against a
# pathological, very long forced sequence — the same cap for every
# level (see spokebound.ai.levels) that turns quiescence on at all.
QUIESCENCE_MAX_PLIES = 6

# A piece on a square the opponent could capture right now counts as
# "hanging"; hanging at or above this many points marks the position
# critical (see is_critical in evaluate.py) — worth spending a level's
# critical_time_limit on instead of its usual time_limit.
CRITICAL_PIECE_VALUE = 8

# The 10 player-facing difficulty levels (Level, LEVELS) live in their
# own file, spokebound.ai.levels — every lever for every level in one
# place, laid out so any one of them is easy to find and tweak without
# touching this file. All 10 run the very same search engine (see
# search.py) and the very same fleet-building/deployment logic (see
# build.py/deploy.py) — a level is nothing but that engine and that
# pregame logic handed a shallower depth, a smaller time budget and a
# less confident (see Level.pregame_skill) pregame setup, never a
# separate, simpler algorithm.
