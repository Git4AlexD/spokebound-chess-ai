"""AI deployment: place each piece on whichever legal square leaves the
whole position scoring best right now, not just a fixed row rule.
"""

import random

from spokebound.ai.config import DEFAULT_WEIGHTS, Weights
from spokebound.ai.evaluate import evaluate
from spokebound.config import BOARD_COLS
from spokebound.model.board import Square
from spokebound.model.deployment import Deployment
from spokebound.model.game import Game
from spokebound.model.pieces import Player


def choose_deploy_square(
    deployment: Deployment, player: Player, weights: Weights = DEFAULT_WEIGHTS, skill: float = 1.0
) -> Square:
    """Return the square the AI should place its next piece on.

    Both Captains, and everything either side has placed so far, are
    already on the board at this point (see Deployment), so trying the
    piece on every legal square and scoring the result with
    :func:`spokebound.ai.evaluate.evaluate` already weighs mutual
    defence and the opponent's own pieces so far, not just this one
    piece's own reach — unlike a fixed "strong pieces go in the back
    row" rule, which can't tell a back row that's actually covered from
    one that's just empty.

    ``skill`` (see spokebound.ai.levels.Level.pregame_skill) is how much
    that evaluation is actually trusted: at 1.0 (the default), the
    highest-scoring legal square always wins, exactly as before. Below
    that, every square's score is perturbed by random noise sized as a
    fraction of this turn's own best-to-worst spread — the same
    evaluation, just trusted less — so a low-skill level can still
    stumble into a good square, but far less reliably than a high one,
    down to picking almost blind at skill=0.0. Ties at skill=1.0 (most
    often early on, before enough is down for most squares to look any
    different) break toward the centre column, closest to the Captain's
    own file and to whatever's already been placed.
    """
    piece = deployment.next_piece(player)
    legal = deployment.legal_squares()
    if piece is None or not legal:
        raise ValueError("Nothing left for the AI to deploy")

    board = deployment.board
    centre = BOARD_COLS // 2

    def raw_score(square: Square) -> float:
        board.place(square, piece)
        result = evaluate(Game(board), player, weights)
        board.remove(square)
        return result

    scores = {square: raw_score(square) for square in legal}
    spread = max(scores.values()) - min(scores.values())
    noise_scale = max(0.0, 1.0 - skill) * spread

    def key(square: Square) -> tuple[float, int]:
        noise = random.uniform(-noise_scale, noise_scale) if noise_scale else 0.0
        return (scores[square] + noise, -abs(square[1] - centre))

    return max(legal, key=key)
