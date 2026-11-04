"""Move selection: one engine (iterative-deepening alpha-beta, time-
boxed, with quiescence search, move ordering and a transposition table)
for every difficulty there is. A level (see spokebound.ai.levels.LEVELS)
is nothing but that engine handed a shallower depth and a smaller time
budget — never a separate, simpler algorithm standing in for "easy."

:func:`choose_move` is the player-facing entry point, taking a level
number 1-10; :func:`choose_move_at` is the same thing for a caller
(bulk self-play tuning) that wants the engine at a profile of its own
choosing rather than one of the 10 player-facing rungs — see
spokebound.ai.selfplay.SELF_PLAY_LEVEL.
"""

import math
import time
from collections.abc import Iterator

from spokebound.ai.config import DEFAULT_WEIGHTS, QUIESCENCE_MAX_PLIES, Weights
from spokebound.ai.evaluate import DECISIVE_SCORE, evaluate, is_critical
from spokebound.ai.exchange import prune_quiescence, see
from spokebound.ai.levels import LEVELS, Level
from spokebound.ai.upgrade import spend_candidates, spend_upgrade
from spokebound.model.board import Board, Square
from spokebound.model.game import Game
from spokebound.model.pieces import Player

Move = tuple[Square, Square]
# A move plus how any upgrade it opens is spent: the spoke levels to set on
# the upgrading piece, or None when the move opens no upgrade.
Ply = tuple[Square, Square, tuple[int, ...] | None]
# A transposition table entry: the depth it was searched to, its score,
# which bound that score represents (see _EXACT/_LOWER/_UPPER), and the
# best move found there (reused for move ordering even when the depth is
# too shallow to trust the score itself).
_TTEntry = tuple[int, float, int, Move | None]
_EXACT, _LOWER, _UPPER = 0, 1, 2

# Killer moves: for each remaining-depth value, up to this many quiet
# moves that caused an alpha-beta cutoff somewhere at that depth earlier
# in this same search — tried right after captures, since a move that
# refuted one line is a good bet to at least be worth trying in a
# sibling line too. History: a running score per move, bumped whenever
# it causes a cutoff (more, the deeper the cutoff), used to break ties
# among the quiet moves that aren't a killer. Both are fresh per
# choose_move call (see _run_search), never kept between turns, same as
# the transposition table.
_KILLERS_PER_DEPTH = 2
_KillerTable = dict[int, list[Move]]
_HistoryTable = dict[Move, int]

# How many times a line of forcing checks can extend the search by one
# extra ply beyond its normal depth limit (see _alpha_beta) — capped so a
# repeated-check line can't stall the search indefinitely.
_MAX_CHECK_EXTENSIONS = 4
_ASPIRATION_WINDOW = 1.0
_IID_MIN_DEPTH = 4
_IID_REDUCTION = 2
_FUTILITY_MARGIN = 1.5
_LMP_FIRST_MOVE = 6
_LMP_MAX_DEPTH = 3


class _Features:
    """Which of the engine's extras are switched on for this search —
    threaded through the recursion instead of read from module-level
    constants, so the same engine can run any level's profile (or a
    detached-from-the-ladder one — see choose_move_at) without
    duplicating the code."""

    __slots__ = (
        "aspiration",
        "check_extensions",
        "futility",
        "history_pruning",
        "iid",
        "move_ordering",
        "pvs",
        "quiescence",
        "quiescence_max_plies",
        "quiescence_pruning",
        "reductions",
        "see",
    )

    def __init__(
        self,
        quiescence: bool,
        quiescence_max_plies: int,
        move_ordering: bool,
        pvs: bool = True,
        reductions: bool = True,
        aspiration: bool = True,
        iid: bool = True,
        see: bool = True,
        check_extensions: int = _MAX_CHECK_EXTENSIONS,
        quiescence_pruning: bool = True,
        futility: bool = True,
        history_pruning: bool = True,
    ) -> None:
        self.quiescence = quiescence
        self.quiescence_max_plies = quiescence_max_plies
        self.move_ordering = move_ordering
        self.pvs = pvs
        self.reductions = reductions
        self.aspiration = aspiration
        self.iid = iid
        self.see = see
        self.check_extensions = check_extensions
        self.quiescence_pruning = quiescence_pruning
        self.futility = futility
        self.history_pruning = history_pruning


class _TimeUp(Exception):
    """Raised to unwind a search once its time budget has run out."""


def choose_move(game: Game, difficulty: int, weights: Weights = DEFAULT_WEIGHTS) -> Move:
    """Return the ``(src, dst)`` move ``game.current`` should play, at
    ``difficulty`` 1-10 (see spokebound.ai.levels.LEVELS)."""
    return choose_turn(game, difficulty, weights)[:2]


def choose_turn(game: Game, difficulty: int, weights: Weights = DEFAULT_WEIGHTS) -> Ply:
    """Like :func:`choose_move`, but returns the whole turn — the move and
    how any upgrade it opens is spent — ready for :func:`play_ply`."""
    if difficulty not in LEVELS:
        raise ValueError(f"Unknown AI difficulty: {difficulty!r}")
    return choose_turn_at(game, LEVELS[difficulty], weights)


def choose_move_at(game: Game, level: Level, weights: Weights = DEFAULT_WEIGHTS) -> Move:
    """Like :func:`choose_move`, but for a ``Level`` of your own choosing
    rather than one of the 10 player-facing rungs — for internal callers
    that want the real engine at a fast profile detached from the
    ladder (see spokebound.ai.selfplay.SELF_PLAY_LEVEL)."""
    return choose_turn_at(game, level, weights)[:2]


def choose_turn_at(game: Game, level: Level, weights: Weights = DEFAULT_WEIGHTS) -> Ply:
    """The whole-turn version of :func:`choose_move_at`."""
    moves = game.all_legal_moves(game.current)
    if not moves:
        raise ValueError("No legal move for the AI to play")
    if len(moves) == 1:
        # Nothing to actually decide — playing it is the "search," worth
        # skipping the whole time budget for; there's no second option
        # to weigh it against.
        return _default_ply(game, moves[0], weights)
    return _choose_level(game, moves, weights, level)


def apply_move(game: Game, move: Move, weights: Weights = DEFAULT_WEIGHTS) -> Game:
    """Return a copy of ``game`` with ``move`` played and any bonus points
    it earns spent greedily (see :mod:`spokebound.ai.upgrade`), with the
    turn closed. Search itself uses :func:`_children`, which searches the
    spend instead."""
    clone = game.copy()
    clone.move(*move)
    if clone.upgrade is not None:
        spend_upgrade(clone, weights)
        clone.finish_turn()
    return clone


def _children(game: Game, move: Move, weights: Weights) -> list[tuple[Ply, Game]]:
    """Return every ``(ply, position)`` that playing ``move`` can lead to.

    A move that earns a bounty or promotion opens an upgrade, and each
    maximal way of spending it becomes its own child, so the spend is
    chosen by the search rather than greedily. Any other move has exactly
    one child.
    """
    clone = game.copy()
    clone.move(*move)
    if clone.upgrade is None:
        return [((move[0], move[1], None), clone)]
    children = []
    for spokes in spend_candidates(clone, clone.upgrade, weights):
        child = clone.copy()
        child.upgrade.piece.spokes = list(spokes)
        child.finish_turn()
        children.append(((move[0], move[1], spokes), child))
    return children


def _default_ply(game: Game, move: Move, weights: Weights) -> Ply:
    return _children(game, move, weights)[0][0]


def _successor_pairs(game: Game, moves: list[Move], weights: Weights) -> Iterator[tuple[Ply, Game]]:
    for move in moves:
        yield from _children(game, move, weights)


def play_ply(game: Game, ply: Ply | Move, weights: Weights = DEFAULT_WEIGHTS) -> None:
    """Play ``ply`` for the current player, including the upgrade spend it
    carries. A bare move (no spend) has its upgrade spent greedily with
    ``weights`` instead, as the fixed benchmark bots do."""
    game.move(ply[0], ply[1])
    if game.upgrade is None:
        return
    if len(ply) > 2 and ply[2] is not None:
        game.upgrade.piece.spokes = list(ply[2])
        game.upgrade.points = 0
    else:
        spend_upgrade(game, weights)
    game.finish_turn()


def _choose_level(game: Game, moves: list[Move], weights: Weights, level: Level) -> Ply:
    """A rung of the 10-level ladder — the shared engine, handed that
    level's own depth/time/feature profile."""
    features = _Features(
        level.use_quiescence,
        QUIESCENCE_MAX_PLIES,
        level.use_move_ordering,
        level.use_pvs,
        level.use_reductions,
        level.use_aspiration,
        level.use_iid,
        level.use_see,
        level.check_extensions,
        level.use_quiescence_pruning,
        level.use_futility,
        level.use_history_pruning,
    )
    return _run_search(
        game,
        moves,
        weights,
        level.min_depth,
        level.max_depth,
        level.time_limit,
        level.critical_time_limit,
        features,
        level.use_transposition_table,
    )


def _run_search(
    game: Game,
    moves: list[Move],
    weights: Weights,
    min_depth: int,
    max_depth: int,
    time_limit: float,
    critical_time_limit: float,
    features: _Features,
    use_transposition_table: bool,
) -> Move:
    """Iterative-deepening alpha-beta: search ``min_depth`` plies (a
    guaranteed result), then try one ply deeper at a time up to
    ``max_depth`` as long as time remains, keeping the deepest result
    that finished before the clock ran out.

    A critical position (see is_critical) gets ``critical_time_limit``
    instead of the usual ``time_limit`` — worth spending longer to get
    right rather than budgeted like any other move. The transposition
    table is fresh for this one call: it lets deeper iterations reuse
    shallower ones' results (and their best move, for ordering), but
    isn't kept between turns, since a turn can promote or upgrade a
    piece and stale entries from before that would just be wrong.

    Stops as soon as any iteration finds a forced win (best_score
    reaches DECISIVE_SCORE) — nothing deeper, or the rest of the time
    budget, can find anything better than a proven win, so there's no
    reason to keep the clock running once one's in hand.
    """
    deadline = time.monotonic() + (critical_time_limit if is_critical(game) else time_limit)
    table: dict[tuple, _TTEntry] = {} if use_transposition_table else None
    killers: _KillerTable | None = {} if features.move_ordering else None
    history: _HistoryTable | None = {} if features.move_ordering else None
    best_ply = _default_ply(game, moves[0], weights)
    previous: float | None = None
    for depth in range(min_depth, max_depth + 1):
        try:
            best_ply, best_score = _root_with_aspiration(
                game, moves, weights, depth, deadline, table, features, killers, history, previous
            )
        except _TimeUp:
            break
        previous = best_score
        if best_score >= DECISIVE_SCORE:
            break
        if time.monotonic() >= deadline:
            break
    return best_ply


def _root_with_aspiration(
    game: Game,
    moves: list[Move],
    weights: Weights,
    depth: int,
    deadline: float,
    table: dict[tuple, _TTEntry] | None,
    features: _Features,
    killers: _KillerTable | None,
    history: _HistoryTable | None,
    previous: float | None,
) -> tuple[Ply, float]:
    """Search the root with a narrow window around the previous iteration's
    score; if the true score falls outside it, search again with the full
    window. The window only saves work — the answer is the same either way.
    """
    if features.aspiration and previous is not None and abs(previous) < DECISIVE_SCORE:
        low, high = previous - _ASPIRATION_WINDOW, previous + _ASPIRATION_WINDOW
        ply, score = _alpha_beta_root(
            game, moves, weights, depth, deadline, table, features, killers, history, low, high
        )
        if low < score < high:
            return ply, score
    return _alpha_beta_root(game, moves, weights, depth, deadline, table, features, killers, history)


def _alpha_beta_root(
    game: Game,
    moves: list[Move],
    weights: Weights,
    depth: int,
    deadline: float,
    table: dict[tuple, _TTEntry] | None,
    features: _Features,
    killers: _KillerTable | None = None,
    history: _HistoryTable | None = None,
    low: float = float("-inf"),
    high: float = float("inf"),
) -> tuple[Ply, float]:
    player = game.current
    tt_move = _tt_move(table, game)
    if features.move_ordering:
        moves = _order_moves(
            game, moves, tt_move, killers.get(depth) if killers is not None else None, history, features.see
        )
    alpha, beta = low, high
    best_ply, best_score = None, float("-inf")
    for index, (ply, child) in enumerate(_successor_pairs(game, moves, weights)):
        child_depth, child_extensions = _extended_depth(child, depth - 1, features.check_extensions)
        score = _child_value(
            child,
            child_depth,
            child_extensions,
            alpha,
            beta,
            True,
            index == 0,
            False,
            player,
            weights,
            deadline,
            table,
            features,
            killers,
            history,
        )
        if best_ply is None or score > best_score:
            best_score, best_ply = score, ply
        alpha = max(alpha, best_score)
        if best_score >= DECISIVE_SCORE:
            break  # a forced win beats anything else on offer
    if table is not None and low < best_score < high:
        table[_state_key(game)] = (depth, best_score, _EXACT, best_ply[:2])
    return best_ply, best_score


def _extended_depth(child: Game, depth: int, extensions_left: int) -> tuple[int, int]:
    """Return ``depth`` for ``child``'s subtree, extended by one extra
    ply (with ``extensions_left`` reduced by one) if ``child`` is a
    forcing check on whoever's about to move there and the line hasn't
    already used up its extension budget — see _MAX_CHECK_EXTENSIONS."""
    if extensions_left > 0 and child.in_check(child.current):
        return depth + 1, extensions_left - 1
    return depth, extensions_left


def _terminal_score(game: Game, player: Player, weights: Weights, plies_in_hand: int) -> float:
    """Return ``game``'s terminal score, nudged by ``plies_in_hand`` —
    however much search budget was still unspent at the node the outcome
    was found on, a stand-in for how few plies it took to get there —
    so a forced win found sooner scores higher than one found deeper,
    and a forced loss found sooner scores lower than one only found
    once the position was dragged out longer.

    Without this, every forced win looks exactly as good as every other
    (all DECISIVE_SCORE) and every forced loss exactly as bad, so
    alpha-beta has no reason to prefer the fastest mate over a slower
    one, or — losing either way — the line that survives longest over
    one that loses immediately. The adjustment is capped well under a
    single point per ply, tiny next to DECISIVE_SCORE, so it can only
    ever break a tie between two already-decisive lines, never compete
    with (or be mistaken for) an ordinary evaluated score.
    """
    score = evaluate(game, player, weights)
    if score >= DECISIVE_SCORE:
        return score + plies_in_hand
    if score <= -DECISIVE_SCORE:
        return score - plies_in_hand
    return score


_EPSILON = 1e-6
_LMR_FIRST_MOVE = 3
_LMR_MIN_DEPTH = 3


def _child_value(
    child: Game,
    depth: int,
    extensions: int,
    alpha: float,
    beta: float,
    maximizing: bool,
    first: bool,
    reducible: bool,
    player: Player,
    weights: Weights,
    deadline: float,
    table: dict[tuple, _TTEntry] | None,
    features: _Features,
    killers: _KillerTable | None,
    history: _HistoryTable | None,
) -> float:
    """Score one child of a node, with principal variation search and late
    move reductions layered on the plain alpha-beta window.

    The first child gets the full window. Later children are first probed
    with a null window at the bound they must beat, and only re-searched
    with the full window if the probe lands inside the window — most
    children fail the probe, which is far cheaper than a full search.
    A ``reducible`` child is searched a ply shallower first, and only
    searched at full depth if that already beats the bound.
    """

    def improves(score: float) -> bool:
        return score > alpha if maximizing else score < beta

    def search(depth_left: int, lo: float, hi: float) -> float:
        return _alpha_beta(
            child,
            depth_left,
            lo,
            hi,
            player,
            weights,
            deadline,
            table,
            features,
            killers,
            history,
            extensions,
        )

    if reducible:
        reduced = search(depth - 1, alpha, beta)
        if not improves(reduced):
            return reduced
    bound = alpha if maximizing else beta
    if first or not features.pvs or math.isinf(bound):
        return search(depth, alpha, beta)
    if maximizing:
        probe = search(depth, alpha, alpha + _EPSILON)
        inside = alpha < probe < beta
    else:
        probe = search(depth, beta - _EPSILON, beta)
        inside = alpha < probe < beta
    if inside:
        return search(depth, alpha, beta)
    return probe


def _alpha_beta(
    game: Game,
    depth: int,
    alpha: float,
    beta: float,
    player: Player,
    weights: Weights,
    deadline: float,
    table: dict[tuple, _TTEntry] | None,
    features: _Features,
    killers: _KillerTable | None = None,
    history: _HistoryTable | None = None,
    extensions_left: int = _MAX_CHECK_EXTENSIONS,
) -> float:
    if time.monotonic() >= deadline:
        raise _TimeUp
    if game.is_over:
        return _terminal_score(game, player, weights, depth)
    if depth <= 0:
        if features.quiescence:
            return _quiescence(
                game, alpha, beta, player, weights, deadline, features.quiescence_max_plies, features
            )
        return evaluate(game, player, weights)

    key = _state_key(game) if table is not None else None
    tt_move = None
    original_alpha, original_beta = alpha, beta
    if key is not None:
        entry = table.get(key)
        if entry is not None:
            entry_depth, entry_score, entry_flag, tt_move = entry
            if entry_depth >= depth:
                if entry_flag == _EXACT:
                    return entry_score
                if entry_flag == _LOWER:
                    alpha = max(alpha, entry_score)
                elif entry_flag == _UPPER:
                    beta = min(beta, entry_score)
                if alpha >= beta:
                    return entry_score

    if features.iid and key is not None and tt_move is None and depth >= _IID_MIN_DEPTH:
        _alpha_beta(
            game,
            depth - _IID_REDUCTION,
            alpha,
            beta,
            player,
            weights,
            deadline,
            table,
            features,
            killers,
            history,
            extensions_left,
        )
        stored = table.get(key)
        tt_move = stored[3] if stored is not None else None
    moves = game.all_legal_moves(game.current)
    if features.move_ordering:
        moves = _order_moves(
            game, moves, tt_move, killers.get(depth) if killers is not None else None, history, features.see
        )

    maximizing = game.current is player
    static_eval = evaluate(game, player, weights) if features.futility and depth == 1 else 0.0
    best = float("-inf") if maximizing else float("inf")
    best_move = None
    for index, (ply, child) in enumerate(_successor_pairs(game, moves, weights)):
        move = ply[:2]
        quiet = _is_quiet(game, ply, child)
        killer_moves = killers.get(depth, []) if killers is not None else []
        if (
            index > 0
            and features.futility
            and depth == 1
            and quiet
            and _futile(
                static_eval, alpha if maximizing else beta, maximizing, weights.material * _FUTILITY_MARGIN
            )
        ):
            continue
        if (
            features.history_pruning
            and history is not None
            and index >= _LMP_FIRST_MOVE
            and depth <= _LMP_MAX_DEPTH
            and quiet
            and history.get(move, 0) == 0
            and move not in killer_moves
        ):
            continue
        child_depth, child_extensions = _extended_depth(child, depth - 1, extensions_left)
        reducible = (
            features.reductions
            and index >= _LMR_FIRST_MOVE
            and child_depth >= _LMR_MIN_DEPTH
            and quiet
            and move not in killer_moves
        )
        score = _child_value(
            child,
            child_depth,
            child_extensions,
            alpha,
            beta,
            maximizing,
            index == 0,
            reducible,
            player,
            weights,
            deadline,
            table,
            features,
            killers,
            history,
        )
        if maximizing:
            if score > best:
                best, best_move = score, move
            alpha = max(alpha, best)
        else:
            if score < best:
                best, best_move = score, move
            beta = min(beta, best)
        if alpha >= beta:
            _record_cutoff(game, move, depth, killers, history)
            break

    if key is not None:
        if best <= original_alpha:
            flag = _UPPER
        elif best >= original_beta:
            flag = _LOWER
        else:
            flag = _EXACT
        table[key] = (depth, best, flag, best_move)
    return best


def _is_quiet(game: Game, ply: Ply, child: Game) -> bool:
    """Return True for a plain move: no upgrade, no capture, no check."""
    return ply[2] is None and game.board.get(ply[1]) is None and not child.in_check(child.current)


def _futile(static_eval: float, bound: float, maximizing: bool, margin: float) -> bool:
    """Return True if even a quiet move's static score plus ``margin``
    cannot reach ``bound``, so searching it is wasted work."""
    if maximizing:
        return static_eval + margin <= bound
    return static_eval - margin >= bound


def _record_cutoff(
    game: Game, move: Move, depth: int, killers: _KillerTable | None, history: _HistoryTable | None
) -> None:
    """Remember ``move`` as having caused a beta cutoff at ``depth``, so
    sibling branches try it early too — only for quiet (non-capture)
    moves, the same as real engines: a cutoff caused by a capture is
    already found first by move ordering anyway."""
    if game.board.get(move[1]) is not None:
        return
    if killers is not None:
        bucket = killers.setdefault(depth, [])
        if move in bucket:
            bucket.remove(move)
        bucket.insert(0, move)
        del bucket[_KILLERS_PER_DEPTH:]
    if history is not None:
        history[move] = history.get(move, 0) + depth * depth


def _quiescence(
    game: Game,
    alpha: float,
    beta: float,
    player: Player,
    weights: Weights,
    deadline: float,
    plies_left: int,
    features: _Features,
) -> float:
    """Keep following forcing moves — captures and checks — past the
    main search's depth limit until either none are left or
    ``plies_left`` runs out, then score the (hopefully now-quiet)
    position.

    Without this, a trade that looks great right at the depth limit (you
    just captured something) can actually be a loss the search simply
    can't see one more ply out (getting recaptured straight back, say).
    Checks are forcing in the same way a capture is — the reply is
    barely a real choice — so a check right at the depth limit gets the
    same "keep looking a little further" treatment a capture does,
    rather than being scored as if the position had settled down.
    "Stand pat" — just taking the static score instead of playing
    anything — is always an option too, the same as in a real game a
    player isn't forced to keep trading just because a capture is on the
    board.
    """
    if time.monotonic() >= deadline:
        raise _TimeUp
    if game.is_over:
        return _terminal_score(game, player, weights, plies_left)
    stand_pat = evaluate(game, player, weights)
    if plies_left <= 0:
        return stand_pat
    board = game.board
    forcing = [
        move
        for move in game.all_legal_moves(game.current)
        if board.get(move[1]) is not None or _gives_check(board, move, game.current)
    ]
    if features.quiescence_pruning:
        forcing = prune_quiescence(
            board,
            forcing,
            stand_pat,
            alpha if game.current is player else beta,
            weights,
            game.current is player,
        )
    if not forcing:
        return stand_pat
    if features.move_ordering:
        forcing = _order_moves(game, forcing, None)

    maximizing = game.current is player
    if maximizing:
        if stand_pat >= beta:
            return stand_pat
        best = stand_pat
        alpha = max(alpha, stand_pat)
        for _, child in _successor_pairs(game, forcing, weights):
            score = _quiescence(child, alpha, beta, player, weights, deadline, plies_left - 1, features)
            if score > best:
                best = score
            alpha = max(alpha, best)
            if alpha >= beta:
                break
        return best
    else:
        if stand_pat <= alpha:
            return stand_pat
        best = stand_pat
        beta = min(beta, stand_pat)
        for _, child in _successor_pairs(game, forcing, weights):
            score = _quiescence(child, alpha, beta, player, weights, deadline, plies_left - 1, features)
            if score < best:
                best = score
            beta = min(beta, best)
            if alpha >= beta:
                break
        return best


def _order_moves(
    game: Game,
    moves: list[Move],
    tt_move: Move | None,
    killer_moves: list[Move] | None = None,
    history: _HistoryTable | None = None,
    use_see: bool = True,
) -> list[Move]:
    """Sort ``moves`` so the ones most likely to cause an alpha-beta
    cutoff are tried first: the transposition table's remembered best
    move for this exact position (if given and still legal here), then
    captures (highest-value victim first), then this depth's killer
    moves (quiet moves that cut off a sibling branch earlier in this
    search — see _record_cutoff), then checks, then everything else,
    broken by history score (also from earlier cutoffs, but scored
    across every depth rather than one) instead of all_legal_moves'
    arbitrary order."""
    killer_set = killer_moves or ()

    def priority(move: Move) -> tuple[int, int]:
        if move == tt_move:
            return (4, 0)
        if game.board.get(move[1]) is not None:
            victim = game.board.get(move[1])
            return (3, see(game.board, move) if use_see else victim.cost)
        if move in killer_set:
            return (2, 0)
        if _gives_check(game.board, move, game.current):
            return (1, 0)
        return (0, history.get(move, 0) if history else 0)

    return sorted(moves, key=priority, reverse=True)


def _gives_check(board: Board, move: Move, mover: Player) -> bool:
    """Return True if playing ``move`` puts the opponent's Captain in
    check right now. Only used for move ordering, so this simulates
    directly on ``board`` and undoes it, the same as
    Game._leaves_captain_attacked, rather than copying the whole Game."""
    src, dst = move
    captured = board.move(src, dst)
    opponent = mover.opponent
    captain_square = next((square for square, piece in board.pieces(opponent) if piece.is_captain), None)
    check = captain_square is not None and any(
        captain_square in board.legal_moves(square) for square, _ in board.pieces(mover)
    )
    board.move(dst, src)
    if captured is not None:
        board.place(dst, captured)
    return check


def _tt_move(table: dict[tuple, _TTEntry] | None, game: Game) -> Move | None:
    if table is None:
        return None
    entry = table.get(_state_key(game))
    return entry[3] if entry is not None else None


def _state_key(game: Game) -> tuple:
    """Return a hashable key identifying this exact position: every
    piece's square, owner, spoke levels, Captain/bounty/promoted status,
    plus whose turn it is. Two different move orders that reach the same
    position (a transposition) get the same key, which is the whole
    point of the transposition table."""
    pieces = []
    for side in Player:
        for square, piece in game.board.pieces(side):
            pieces.append(
                (square, piece.owner, tuple(piece.spokes), piece.is_captain, piece.bounty, piece.promoted)
            )
    return (tuple(sorted(pieces)), game.current)
