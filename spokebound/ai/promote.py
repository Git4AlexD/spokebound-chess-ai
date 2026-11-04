"""Promote a tuning or evolution result into whatever the game actually
plays with. spokebound.ai.evolve and spokebound.ai.evolve_fleet both call
``apply`` automatically now, at the end of their own deep-validation
round (see either module's own module docstring) — there's no gate to
clear and nothing left unpromoted; every full run's champion becomes the
new spokebound.ai.config.DEFAULT_WEIGHTS / DEFAULT_FLEET_RULES, the
literal every other part of the AI reads from, unconditionally. This
module's own CLI below is for the rarer manual case: promoting an
already-saved champion snapshot (evolved_champion.json /
evolved_fleet_rules.json) by hand — e.g. resurrecting an older run's
result, or re-applying one after editing config.py by hand in between.
This rewrites one of DEFAULT_WEIGHTS/DEFAULT_FLEET_RULES's two lines,
never both from the same file (a Weights result and a FleetRules result
are never the same shape).

    python -m spokebound.ai.promote spokebound/ai/evolved_champion.json
    python -m spokebound.ai.promote spokebound/ai/evolved_champion.json --apply
    python -m spokebound.ai.promote spokebound/ai/evolved_fleet_rules.json --kind fleet-rules --apply

The first form only prints a preview (the new values, and how each one
differs from the current default) — nothing is written. Add --apply
once you've actually looked at that preview and decided the result is
worth adopting. ``--kind`` picks which of the two it is; default is
weights.
"""

import argparse
import json
import re
from pathlib import Path

from spokebound.ai.config import DEFAULT_FLEET_RULES, DEFAULT_WEIGHTS, FleetRules, Weights

CONFIG_PATH = Path(__file__).with_name("config.py")

# Which config.py assignment, and which baseline to diff against, each
# kind of genome promotes into.
_TARGETS = {
    Weights: ("DEFAULT_WEIGHTS", DEFAULT_WEIGHTS),
    FleetRules: ("DEFAULT_FLEET_RULES", DEFAULT_FLEET_RULES),
}


def load(path: Path, cls: type = Weights):
    """Read a champion file into ``cls`` (Weights or FleetRules),
    ignoring any extra keys (e.g. evolve.py's "name") it doesn't need."""
    data = json.loads(path.read_text(encoding="utf-8"))
    _, baseline = _TARGETS[cls]
    fields = {name: data[name] for name in baseline.field_names()}
    return cls(**fields)


def format_literal(genome) -> str:
    """Return the ``NAME = Cls(...)`` literal --apply writes into
    config.py, one field per line — also printed on its own so it can
    be pasted in by hand instead, if you'd rather not trust this
    script's own text surgery on a source file."""
    assignment, _ = _TARGETS[type(genome)]
    fields = ",\n".join(f"    {field}={getattr(genome, field)!r}" for field in genome.field_names())
    return f"{assignment} = {type(genome).__name__}(\n{fields},\n)"


def apply(genome) -> None:
    """Rewrite config.py's matching assignment (DEFAULT_WEIGHTS or
    DEFAULT_FLEET_RULES, going by ``genome``'s own type) in place."""
    assignment, _ = _TARGETS[type(genome)]
    pattern = re.compile(rf"^{assignment} = {type(genome).__name__}\([^)]*\)$", re.MULTILINE)
    text = CONFIG_PATH.read_text(encoding="utf-8")
    match = pattern.search(text)
    if match is None:
        raise SystemExit(
            f"Couldn't find a '{assignment} = {type(genome).__name__}(...)' "
            f"assignment to replace in {CONFIG_PATH} — promote by hand "
            "instead, using the literal printed above."
        )
    new_text = text[: match.start()] + format_literal(genome) + text[match.end() :]
    CONFIG_PATH.write_text(new_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("champion_file", type=Path, help="A champion JSON file to promote")
    parser.add_argument(
        "--kind",
        choices=("weights", "fleet-rules"),
        default="weights",
        help="Which default this file promotes into (default: weights)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rewrite config.py (default: only preview what would change)",
    )
    args = parser.parse_args()
    cls = Weights if args.kind == "weights" else FleetRules
    _, baseline = _TARGETS[cls]

    genome = load(args.champion_file, cls)
    print(f"Promoting {args.champion_file}:\n")
    print(genome.describe_diff(baseline))
    print()
    print(format_literal(genome))
    if args.apply:
        apply(genome)
        print(
            f"\nWritten to {CONFIG_PATH}. Run the test suite before "
            "trusting this in a real game — several of test_ai.py's "
            "evaluate() tests check that one position scores better "
            "than another under the current defaults, and a "
            "sufficiently extreme promoted value could in principle "
            "flip one of those orderings."
        )
    else:
        print("\n(preview only — nothing written; pass --apply to actually rewrite config.py)")


if __name__ == "__main__":
    main()
