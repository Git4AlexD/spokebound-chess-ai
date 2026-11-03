"""The 10 playable difficulty levels — every lever for every level in
one place, one level at a time, so tweaking a single number doesn't
require hunting through search.py or evaluate.py.

There is exactly one AI here, not a separate weak one and a separate
strong one: every level runs spokebound.ai.search's shared engine
(iterative-deepening alpha-beta, quiescence, move ordering, a
transposition table) for its moves, and the very same fleet-building/
deployment logic (spokebound.ai.build/spokebound.ai.deploy) for its
pregame setup — a level is that engine and that setup handed a
shallower depth, a smaller time budget and a less confident pregame
policy, never a different, simpler algorithm standing in for "easy."
Level 10, Impossible, is simply that same engine and setup with no
limitations relaxed — the strongest configuration that still finishes a
move in a reasonable wait.

Each Level is a full profile for the engine and the pregame setup —
these are the levers:

    min_depth / max_depth     Iterative deepening starts at min_depth
                               and tries one ply deeper at a time, up to
                               max_depth, as long as time remains.
    time_limit                Normal per-move time budget, in seconds.
    critical_time_limit       Used instead of time_limit when
                               spokebound.ai.evaluate.is_critical flags
                               the position (a Captain in check, an
                               undefended close Captain race, or a piece
                               worth CRITICAL_PIECE_VALUE+ hanging) —
                               worth spending longer to get right.
    use_quiescence             Keep following captures and checks past
                               the depth limit until the position is
                               quiet, so a trade (or a check) that looks
                               good right at the limit isn't scored
                               before seeing the reply.
    use_move_ordering          Try the transposition table's remembered
                               move, then captures, then checks, first —
                               so alpha-beta prunes more, faster.
    use_transposition_table    Cache each position's result for this
                               move's search, so a transposed or
                               revisited position isn't re-searched.
    pregame_skill              How much of the fully-evolved pregame
                               brain (spokebound.ai.config.
                               DEFAULT_FLEET_RULES, plus deployment
                               scored by spokebound.ai.evaluate.evaluate)
                               this level actually gets, from 0.0 (a
                               fleet built by pure chance and pieces
                               placed with no regard for how good the
                               square actually is) to 1.0 (the real,
                               fully-evolved fleet-building rules and
                               exact-best deployment, no noise at all)
                               — see spokebound.ai.build._rules_for_level
                               and spokebound.ai.deploy.choose_deploy_square.
                               No level, at any difficulty, ever looks at
                               the opponent's own built fleet — this only
                               ever weakens (or doesn't) a side's own
                               setup, never lets it see the other side's.

To add or tweak a level: edit (or copy) one of the _add(...) calls
below — every field is a keyword, so it's always clear which lever
you're changing. LEVELS is rebuilt from these on import; nothing else
in the codebase hard-codes a level's numbers.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    """One rung of the ladder — see the module docstring for what each
    field controls."""

    number: int
    name: str
    min_depth: int
    max_depth: int
    time_limit: float
    critical_time_limit: float
    use_quiescence: bool
    use_move_ordering: bool
    use_transposition_table: bool
    pregame_skill: float
    use_pvs: bool = True
    use_reductions: bool = True
    use_aspiration: bool = True
    use_iid: bool = True
    use_see: bool = True
    check_extensions: int = 4
    use_quiescence_pruning: bool = True
    use_futility: bool = True
    use_history_pruning: bool = True


LEVELS: dict[int, Level] = {}


def _add(*, number: int, name: str, min_depth: int, max_depth: int,
        time_limit: float, critical_time_limit: float,
        use_quiescence: bool, use_move_ordering: bool,
        use_transposition_table: bool, pregame_skill: float) -> None:
    LEVELS[number] = Level(
        number=number, name=name,
        min_depth=min_depth, max_depth=max_depth, time_limit=time_limit,
        critical_time_limit=critical_time_limit,
        use_quiescence=use_quiescence, use_move_ordering=use_move_ordering,
        use_transposition_table=use_transposition_table,
        pregame_skill=pregame_skill)


_add(
    number=1, name="Beginner",
    min_depth=1, max_depth=1,
    time_limit=0.20, critical_time_limit=0.30,
    use_quiescence=False, use_move_ordering=False,
    use_transposition_table=False,
    pregame_skill=0.00,
)

_add(
    number=2, name="Novice",
    min_depth=1, max_depth=2,
    time_limit=0.30, critical_time_limit=0.45,
    use_quiescence=False, use_move_ordering=False,
    use_transposition_table=False,
    pregame_skill=0.12,
)

_add(
    number=3, name="Casual",
    min_depth=1, max_depth=2,
    time_limit=0.45, critical_time_limit=0.65,
    use_quiescence=False, use_move_ordering=True,
    use_transposition_table=False,
    pregame_skill=0.25,
)

_add(
    number=4, name="Club Player",
    min_depth=2, max_depth=3,
    time_limit=0.65, critical_time_limit=0.90,
    use_quiescence=False, use_move_ordering=True,
    use_transposition_table=False,
    pregame_skill=0.40,
)

_add(
    number=5, name="Solid",
    min_depth=2, max_depth=3,
    time_limit=0.90, critical_time_limit=1.30,
    use_quiescence=True, use_move_ordering=True,
    use_transposition_table=False,
    pregame_skill=0.55,
)

_add(
    number=6, name="Sharp",
    min_depth=2, max_depth=3,
    time_limit=1.30, critical_time_limit=1.90,
    use_quiescence=True, use_move_ordering=True,
    use_transposition_table=True,
    pregame_skill=0.68,
)

_add(
    number=7, name="Strong",
    min_depth=2, max_depth=4,
    time_limit=1.80, critical_time_limit=2.70,
    use_quiescence=True, use_move_ordering=True,
    use_transposition_table=True,
    pregame_skill=0.80,
)

_add(
    number=8, name="Expert",
    min_depth=2, max_depth=4,
    time_limit=2.50, critical_time_limit=4.00,
    use_quiescence=True, use_move_ordering=True,
    use_transposition_table=True,
    pregame_skill=0.90,
)

_add(
    number=9, name="Master",
    min_depth=2, max_depth=4,
    time_limit=4.00, critical_time_limit=6.50,
    use_quiescence=True, use_move_ordering=True,
    use_transposition_table=True,
    pregame_skill=0.96,
)

# The top rung: as deep and as long-thinking as the engine gets, with
# every search feature on (killer moves, history heuristic and check
# extensions included — see search.py) and pregame_skill=1.0, the real,
# fully-evolved fleet-building and deployment, still built entirely
# blind to the opponent's own fleet. Not a guarantee no one could ever
# beat it, but this is the ceiling — nothing plays stronger, at a wait
# still reasonable for one move.
_add(
    number=10, name="Impossible",
    min_depth=2, max_depth=5,
    time_limit=8.00, critical_time_limit=12.00,
    use_quiescence=True, use_move_ordering=True,
    use_transposition_table=True,
    pregame_skill=1.00,
)
