"""Position scoring: a weighted sum of features, always from ``player``'s
own point of view — positive is good for ``player``, negative is good
for their opponent.
"""

from spokebound.ai.config import CRITICAL_PIECE_VALUE, DEFAULT_WEIGHTS, Weights
from spokebound.config import GOAL_SQUARES
from spokebound.model.board import Board, Square
from spokebound.model.game import Game
from spokebound.model.pieces import Player

# A decisive game (win, loss or the game not being over yet doesn't reach
# this) dwarfs anything the weighted features alone could add up to, so
# search always prefers an actual won position over just a good-looking
# one, and a search that only sees the win a few plies deep still steers
# toward it well before then.
DECISIVE_SCORE = 10_000.0

# board.legal_moves(square) result cache, scoped to one evaluate() (or
# is_critical()) call — never kept any longer than that, so it's always
# safe regardless of anything mutating the board or a piece's spokes
# between calls. Every feature below independently asks "what can this
# piece reach" for overlapping sets of squares (goal_attackers and
# goal_area_control alone ask it for 9 squares each, every one of them
# iterating the whole fleet) — profiling a single self-play game showed
# this recomputing the exact same board.legal_moves(square) result
# millions of times over; caching it for the lifetime of one evaluate()
# call cut that down by roughly two orders of magnitude. ``None``
# (the default everywhere below) just means "don't bother caching" —
# every feature function is still callable (and correct) on its own,
# the way the tests call many of them directly, without one.
_LegalMovesCache = dict[Square, list[Square]]


def _legal_moves(board: Board, square: Square,
                 cache: _LegalMovesCache | None) -> list[Square]:
    if cache is None:
        return board.legal_moves(square)
    cached = cache.get(square)
    if cached is None:
        cached = board.legal_moves(square)
        cache[square] = cached
    return cached


def evaluate(game: Game, player: Player,
            weights: Weights = DEFAULT_WEIGHTS) -> float:
    """Score ``game`` from ``player``'s perspective under ``weights``."""
    if game.outcome is not None:
        winner = game.outcome.winner
        if winner is None:
            return 0.0
        return DECISIVE_SCORE if winner is player else -DECISIVE_SCORE

    opponent = player.opponent
    cache: _LegalMovesCache = {}
    return (weights.material * _material(game, player, opponent)
           + weights.bounty_risk * _bounty_risk(game, player, opponent, cache)
           + weights.captain_distance * _captain_distance(game, player,
                                                           opponent)
           + weights.captain_safety * _captain_safety(game, player,
                                                       opponent, cache)
           + weights.goal_attackers * _goal_attackers(game, player,
                                                       opponent, cache)
           + weights.goal_urgency * _goal_urgency(game, player, opponent,
                                                   cache)
           + weights.goal_area_control * _goal_area_control(game, player,
                                                             opponent, cache)
           + weights.piece_safety * _piece_safety(game, player, opponent,
                                                   cache)
           + weights.captain_escape * _captain_escape(game, player,
                                                       opponent, cache)
           + weights.mobility * _mobility(game, player, opponent, cache))


def _material(game: Game, player: Player, opponent: Player) -> float:
    """Points on the board, this player's minus the opponent's."""
    return game.score(player) - game.score(opponent)


def _bounty_risk(game: Game, player: Player, opponent: Player,
                 cache: _LegalMovesCache | None = None) -> float:
    """Bounty points the opponent has hanging one capture away from being
    lost, minus the same for this player — threatened bounties the
    opponent would lose are good for ``player``, and vice versa."""
    return (_bounty_at_risk(game.board, opponent, player, cache)
           - _bounty_at_risk(game.board, player, opponent, cache))


def _threatened_squares(board: Board, attacker: Player,
                        cache: _LegalMovesCache | None = None) -> set[Square]:
    """Return every square ``attacker`` could move a piece to right now
    (pseudo-legally — good enough for a risk estimate, and far cheaper
    than filtering every one of these squares for check every time)."""
    threatened: set[Square] = set()
    for square, _ in board.pieces(attacker):
        threatened.update(_legal_moves(board, square, cache))
    return threatened


def _bounty_at_risk(board: Board, owner: Player, attacker: Player,
                    cache: _LegalMovesCache | None = None) -> int:
    """Return ``owner``'s bounty points sitting on a square ``attacker``
    could move to right now."""
    threatened = _threatened_squares(board, attacker, cache)
    return sum(piece.bounty for square, piece in board.pieces(owner)
              if piece.bounty and square in threatened)


# Extra credit once a Captain is within this many moves of the goal, on
# top of the steady per-square score below — the race is close to a
# decision, not just incremental progress, once it's this close. Squared,
# so the danger ramps up fast within the range instead of mattering
# evenly throughout it: one move out is far more than "twice as
# dangerous" as two.
CAPTAIN_CLOSE_RANGE = 2


def _captain_distance(game: Game, player: Player,
                      opponent: Player) -> float:
    """How much closer this player's Captain is to the goal than the
    opponent's, counted two ways at once: a steady, even score for every
    square of difference across the whole board — so making progress
    always matters, not just once a Captain happens to already be close
    — plus a bonus that ramps up sharply within striking range.
    """
    mine = _captain_distance_to_goal(game.board, player)
    theirs = _captain_distance_to_goal(game.board, opponent)
    if mine is None or theirs is None:
        return 0.0
    steady = theirs - mine
    close_bonus = _close_bonus(mine) - _close_bonus(theirs)
    return steady + close_bonus


def _close_bonus(distance: int) -> float:
    return max(0, CAPTAIN_CLOSE_RANGE - distance) ** 2


def _captain_distance_to_goal(board: Board, player: Player) -> int | None:
    """Return the Captain's distance to the goal in moves.

    Chebyshev, not Manhattan: the Captain moves one square in any of the
    8 directions (diagonals included) per turn, so a diagonal approach
    reaches the goal in fewer moves than the sum of its row and column
    distances would suggest.
    """
    square = _captain_square(board, player)
    if square is None:
        return None
    goal_row, goal_col = next(iter(GOAL_SQUARES))
    return max(abs(square[0] - goal_row), abs(square[1] - goal_col))


def _goal_attackers(game: Game, player: Player, opponent: Player,
                    cache: _LegalMovesCache | None = None) -> float:
    """Count of this player's pieces that hold or could reach the goal
    square right now, minus the opponent's.

    A count, not a yes/no: it can tell a goal covered by three defenders
    (still safe even if one gets traded off) from one covered by a
    single piece about to be the only thing stopping a rush — the same
    mechanic behind captain_distance's proximity signal (a square a
    piece can move to counts as "attacked" for check purposes, see
    Game._leaves_captain_attacked, so holding it makes moving an enemy
    Captain onto it outright illegal), just with a finer sense of how
    solid that hold actually is.
    """
    goal = next(iter(GOAL_SQUARES))
    mine = _attacker_count(game.board, player, goal, cache)
    theirs = _attacker_count(game.board, opponent, goal, cache)
    return mine - theirs


def _goal_urgency(game: Game, player: Player, opponent: Player,
                  cache: _LegalMovesCache | None = None) -> float:
    """How urgently the opponent's Captain is closing in on a
    *completely undefended* goal, versus the same for this player's own
    advance.

    Zero the moment the goal has even one defender (see goal_attackers):
    a close but guarded Captain isn't actually in a position to walk
    in — the rules already forbid it — so this is specifically the
    "nothing at all is stopping them" alarm, sharper and narrower than
    captain_distance's steady proximity score.
    """
    goal = next(iter(GOAL_SQUARES))
    i_defend = _attacker_count(game.board, player, goal, cache) > 0
    they_defend = _attacker_count(game.board, opponent, goal, cache) > 0
    mine = 0.0 if they_defend else _inverse_distance(game.board, player)
    theirs = 0.0 if i_defend else _inverse_distance(game.board, opponent)
    return mine - theirs


def _inverse_distance(board: Board, player: Player) -> float:
    distance = _captain_distance_to_goal(board, player)
    return 1.0 / distance if distance else 0.0


def _attacker_count(board: Board, attacker: Player, square: Square,
                    cache: _LegalMovesCache | None = None) -> int:
    """Count ``attacker``'s pieces that could move to ``square`` right
    now, plus one if they already hold it with a piece of their own —
    occupying it denies it to the opponent's Captain exactly as
    attacking it from outside does."""
    occupant = board.get(square)
    count = 1 if (occupant is not None and occupant.owner is attacker) else 0
    count += sum(1 for attacker_square, _ in board.pieces(attacker)
                if square in _legal_moves(board, attacker_square, cache))
    return count


def _goal_area_control(game: Game, player: Player, opponent: Player,
                       cache: _LegalMovesCache | None = None) -> float:
    """Control of the 8 squares immediately around the goal — not the
    goal square itself, that's goal_attackers' job — this player's minus
    the opponent's.

    This is a wider ring than goal_attackers or goal_urgency look at, so
    it can flag the approaches to the goal being cut off (or opened up)
    before a Captain is actually close enough for either of those to see
    anything: holding the ring makes it hard for an enemy Captain to
    even get adjacent to the goal in the first place, let alone onto it.
    """
    area = _neighbours(next(iter(GOAL_SQUARES)))
    mine = sum(_attacker_count(game.board, player, square, cache)
              for square in area)
    theirs = sum(_attacker_count(game.board, opponent, square, cache)
                for square in area)
    return mine - theirs


def _piece_safety(game: Game, player: Player, opponent: Player,
                  cache: _LegalMovesCache | None = None) -> float:
    """Value of this player's pieces that are under attack with nothing
    of their own able to recapture, minus the same for the opponent.

    Not the same thing as bounty_risk (which only looks at bounty
    pieces) or material (which only counts what's already been
    captured): a piece under attack but defended is a fair trade if it's
    taken, not a real threat, while one under attack with no defender at
    all is material about to be lost for free — the evaluation
    otherwise has no way to tell those two apart.
    """
    return (_undefended_value(game.board, opponent, player, cache)
           - _undefended_value(game.board, player, opponent, cache))


def _undefended_value(board: Board, owner: Player, attacker: Player,
                      cache: _LegalMovesCache | None = None) -> int:
    """Return the total cost of ``owner``'s pieces that ``attacker``
    threatens and no other piece of ``owner``'s could recapture."""
    threatened = _threatened_squares(board, attacker, cache)
    return sum(piece.cost for square, piece in board.pieces(owner)
              if square in threatened and not _is_defended(board, square))


def _is_defended(board: Board, square: Square) -> bool:
    """Return True if some other piece belonging to whoever holds
    ``square`` could recapture there if the piece on it were taken.

    Checked by pretending the piece on ``square`` briefly belongs to the
    opponent (the same trick Game._leaves_captain_attacked uses for
    check) so a friendly piece's ray correctly stops there as a capture,
    rather than either being blocked early (as it would be by a piece it
    actually recognises as its own) or passing straight through.

    Deliberately never uses the shared _LegalMovesCache other features
    thread through evaluate(): while ``square``'s owner is swapped, any
    other square's legal_moves that rays through it would compute
    differently than usual — caching that value would either read a now
    -stale cached result from before the swap, or (worse) write a
    swap-context-specific result other, unrelated callers could later
    read back as if it were the board's normal state.
    """
    piece = board.get(square)
    if piece is None:
        return False
    owner = piece.owner
    piece.owner = owner.opponent
    try:
        return any(square in board.legal_moves(other_square)
                  for other_square, _ in board.pieces(owner))
    finally:
        piece.owner = owner


def _captain_escape(game: Game, player: Player, opponent: Player,
                    cache: _LegalMovesCache | None = None) -> float:
    """This player's Captain's count of safe escape squares (legal moves
    that land somewhere the opponent doesn't currently attack), minus
    the opponent's.

    Different from captain_safety, which counts attackers near the
    Captain: a Captain can have no attacker adjacent yet, still, have
    nowhere safe to actually go — boxed in by its own pieces or the
    edge of the board — which is its own kind of danger captain_safety
    alone wouldn't catch.
    """
    return (_escape_count(game, player, opponent, cache)
           - _escape_count(game, opponent, player, cache))


def _escape_count(game: Game, owner: Player, attacker: Player,
                  cache: _LegalMovesCache | None = None) -> int:
    square = _captain_square(game.board, owner)
    if square is None:
        return 0
    threatened = _threatened_squares(game.board, attacker, cache)
    return sum(1 for dst in _legal_moves(game.board, square, cache)
              if dst not in threatened)


def _captain_safety(game: Game, player: Player, opponent: Player,
                    cache: _LegalMovesCache | None = None) -> float:
    """How much more surrounded this player's Captain is than the
    opponent's — a rough tactical-danger proxy alongside material."""
    mine = _attackers_near_captain(game.board, player, opponent, cache)
    theirs = _attackers_near_captain(game.board, opponent, player, cache)
    return theirs - mine


def _attackers_near_captain(board: Board, owner: Player, attacker: Player,
                            cache: _LegalMovesCache | None = None) -> int:
    """Count ``attacker``'s pieces that could reach ``owner``'s Captain's
    square or a square right next to it."""
    square = _captain_square(board, owner)
    if square is None:
        return 0
    danger = {square} | _neighbours(square)
    count = 0
    for attacker_square, _ in board.pieces(attacker):
        if danger & set(_legal_moves(board, attacker_square, cache)):
            count += 1
    return count


def _neighbours(square: Square) -> set[Square]:
    row, col = square
    return {(row + d_row, col + d_col)
           for d_row in (-1, 0, 1) for d_col in (-1, 0, 1)
           if (d_row, d_col) != (0, 0)}


def _captain_square(board: Board, player: Player) -> Square | None:
    for square, piece in board.pieces(player):
        if piece.is_captain:
            return square
    return None


def _mobility(game: Game, player: Player, opponent: Player,
             cache: _LegalMovesCache | None = None) -> float:
    """Pseudo-legal move counts, this player's minus the opponent's —
    cheaper than filtering for check, and good enough as a "how much
    room to manoeuvre" signal."""
    mine = sum(len(_legal_moves(game.board, square, cache))
              for square, _ in game.board.pieces(player))
    theirs = sum(len(_legal_moves(game.board, square, cache))
                for square, _ in game.board.pieces(opponent))
    return mine - theirs


def is_critical(game: Game) -> bool:
    """Return True if this position is worth spending extra search time
    on (see a Level's own critical_time_limit): either Captain is in check,
    either Captain is racing a completely undefended goal, or a piece
    worth CRITICAL_PIECE_VALUE points or more is hanging for either
    side. Not tied to whichever player the AI is — a position is
    critical or it isn't, regardless of whose turn it looks more
    dangerous for.
    """
    for player in Player:
        if game.in_check(player):
            return True
    cache: _LegalMovesCache = {}
    for player in Player:
        if _goal_urgency(game, player, player.opponent, cache) != 0.0:
            return True
    return (_hanging_piece_value(game, Player.ORANGE, cache) >= CRITICAL_PIECE_VALUE
           or _hanging_piece_value(game, Player.WHITE, cache) >= CRITICAL_PIECE_VALUE)


def _hanging_piece_value(game: Game, owner: Player,
                         cache: _LegalMovesCache | None = None) -> int:
    """Return the highest cost among ``owner``'s pieces sitting on a
    square the opponent could capture right now (pseudo-legally)."""
    threatened = _threatened_squares(game.board, owner.opponent, cache)
    values = [piece.cost for square, piece in game.board.pieces(owner)
             if square in threatened]
    return max(values, default=0)
