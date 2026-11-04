"""Tests for the computer opponent: evaluation, search, and the build,
deploy and upgrade helpers for the other phases.
"""

import json
import math
import random
import tempfile
import time
import unittest
from pathlib import Path

from spokebound.ai.benchmarks import (
    grabber_move,
    hoarder_move,
    opportunist_move,
    rusher_move,
    turtle_move,
)
from spokebound.ai.build import build_fleet, build_fleet_spec, materialize_fleet
from spokebound.ai.cma_es import (
    CMAES,
    _restore,
    _to_vector,
    jacobi_eigh,
    load_state,
    run_cma_es,
    save_state,
)
from spokebound.ai.config import (
    DEFAULT_FLEET_RULES,
    DEFAULT_WEIGHTS,
    QUIESCENCE_MAX_PLIES,
    FleetRules,
    Weights,
)
from spokebound.ai.deploy import choose_deploy_square
from spokebound.ai.evaluate import (
    DECISIVE_SCORE,
    _captain_distance,
    _captain_escape,
    _goal_area_control,
    _is_defended,
    evaluate,
    is_critical,
)
from spokebound.ai.levels import Level
from spokebound.ai.search import (
    _KILLERS_PER_DEPTH,
    _MAX_CHECK_EXTENSIONS,
    _extended_depth,
    _Features,
    _gives_check,
    _order_moves,
    _quiescence,
    _record_cutoff,
    _state_key,
    _terminal_score,
    apply_move,
    choose_move,
    choose_move_at,
)
from spokebound.ai.selfplay import play_round
from spokebound.ai.upgrade import spend_upgrade
from spokebound.config import (
    BUILD_BUDGET,
    FLEET_SIZE,
    GOAL_SQUARES,
    LEVEL_COSTS,
    MIN_PIECE_COST,
    UNLIMITED,
)
from spokebound.model.board import Board, Square
from spokebound.model.deployment import Deployment
from spokebound.model.game import Game, Outcome
from spokebound.model.pieces import SPOKE_COUNT, Piece, Player, make_captain
from spokebound.model.spending import FleetBuilder, PendingUpgrade

N = 0  # index of the forward spoke


def one_spoke(spoke: int, level: int) -> list[int]:
    levels = [0] * SPOKE_COUNT
    levels[spoke] = level
    return levels


def place_all(pieces: dict[Square, Piece]) -> Board:
    board = Board()
    for square, piece in pieces.items():
        board.place(square, piece)
    return board


class EvaluateTests(unittest.TestCase):
    def test_more_material_scores_higher(self):
        # Captains sit at equal distance from goal either way, so this
        # isolates material as the only thing that differs.
        board = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 2)),
                (1, 3): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
                (6, 3): make_captain(Player.ORANGE),
                (0, 3): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        self.assertGreater(
            evaluate(game, Player.ORANGE, DEFAULT_WEIGHTS), evaluate(game, Player.WHITE, DEFAULT_WEIGHTS)
        )

    def test_a_decisive_outcome_dwarfs_the_weighted_features(self):
        board = place_all({(8, 3): make_captain(Player.ORANGE)})
        game = Game(board)
        game.outcome = Outcome(winner=Player.ORANGE, reason="test")
        self.assertEqual(evaluate(game, Player.ORANGE, DEFAULT_WEIGHTS), DECISIVE_SCORE)
        self.assertEqual(evaluate(game, Player.WHITE, DEFAULT_WEIGHTS), -DECISIVE_SCORE)

    def test_a_drawn_outcome_scores_zero(self):
        board = place_all({(8, 3): make_captain(Player.ORANGE)})
        game = Game(board)
        game.outcome = Outcome(winner=None, reason="test")
        self.assertEqual(evaluate(game, Player.ORANGE, DEFAULT_WEIGHTS), 0.0)

    def test_decisive_outcomes_score_exactly_plus_minus_10000(self):
        board = place_all({(8, 3): make_captain(Player.ORANGE)})
        game = Game(board)
        game.outcome = Outcome(winner=Player.ORANGE, reason="test")
        self.assertEqual(evaluate(game, Player.ORANGE, DEFAULT_WEIGHTS), 10_000.0)
        self.assertEqual(evaluate(game, Player.WHITE, DEFAULT_WEIGHTS), -10_000.0)

    def test_an_unguarded_enemy_captain_one_step_from_goal_scores_badly(self):
        # Nothing defends the centre, and White's Captain is one move
        # from an instant win next turn — this has to score strongly
        # negative for Orange well before any search would otherwise see
        # the win coming on its own.
        board = place_all(
            {
                (8, 6): make_captain(Player.ORANGE),
                (2, 3): make_captain(Player.WHITE),  # one move from (3, 3)
            }
        )
        score = evaluate(Game(board), Player.ORANGE, DEFAULT_WEIGHTS)
        self.assertLess(score, -20)

    def test_an_enemy_captain_near_the_goal_outweighs_modest_material(self):
        # Orange has a bit of spare material either way; the only
        # difference is how close White's Captain is to the goal. That
        # threat has to matter enough on its own that the AI steers
        # toward blocking it long before a shallow search would
        # otherwise see the win coming.
        near_goal = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 2)),
                (8, 6): make_captain(Player.ORANGE),
                (2, 3): make_captain(Player.WHITE),  # one move from (3, 3)
            }
        )
        far_from_goal = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 2)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        near_score = evaluate(Game(near_goal), Player.ORANGE, DEFAULT_WEIGHTS)
        far_score = evaluate(Game(far_from_goal), Player.ORANGE, DEFAULT_WEIGHTS)
        self.assertLess(near_score, far_score)

    def test_controlling_the_goal_square_scores_higher(self):
        # A piece that can reach the goal square makes it illegal for the
        # opponent's Captain to move there at all (the same way moving a
        # king into check is illegal in chess), so holding it should
        # score clearly better than not.
        controlled = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        uncontrolled = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        self.assertIn((3, 3), Game(controlled).board.legal_moves((5, 3)))
        self.assertNotIn((3, 3), Game(uncontrolled).board.legal_moves((5, 3)))
        controlled_score = evaluate(Game(controlled), Player.ORANGE, DEFAULT_WEIGHTS)
        uncontrolled_score = evaluate(Game(uncontrolled), Player.ORANGE, DEFAULT_WEIGHTS)
        self.assertGreater(controlled_score, uncontrolled_score)

    def test_piece_safety_favours_a_defended_piece_over_undefended(self):
        def board_with_defender(include_defender):
            pieces = {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (1, 3): Piece(Player.WHITE, spokes=one_spoke(N, UNLIMITED)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
            if include_defender:
                pieces[(5, 5)] = Piece(Player.ORANGE, spokes=[UNLIMITED] * SPOKE_COUNT)
            return place_all(pieces)

        defended = Game(board_with_defender(True))
        undefended = Game(board_with_defender(False))
        self.assertIn((5, 3), defended.board.legal_moves((1, 3)))
        self.assertTrue(_is_defended(defended.board, (5, 3)))
        self.assertFalse(_is_defended(undefended.board, (5, 3)))
        defended_score = evaluate(defended, Player.ORANGE, DEFAULT_WEIGHTS)
        undefended_score = evaluate(undefended, Player.ORANGE, DEFAULT_WEIGHTS)
        self.assertGreater(defended_score, undefended_score)

    def test_goal_area_control_rewards_holding_the_ring_around_the_goal(self):
        holding = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=[UNLIMITED] * SPOKE_COUNT),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        not_holding = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        self.assertIn((4, 3), Game(holding).board.legal_moves((5, 3)))
        holding_area = _goal_area_control(Game(holding), Player.ORANGE, Player.WHITE)
        not_holding_area = _goal_area_control(Game(not_holding), Player.ORANGE, Player.WHITE)
        self.assertGreater(holding_area, not_holding_area)

    def test_captain_escape_rewards_more_safe_squares(self):
        boxed = place_all(
            {
                (5, 5): make_captain(Player.ORANGE),
                (4, 4): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (4, 5): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (4, 6): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (5, 4): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (5, 6): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (6, 4): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (6, 5): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        open_board = place_all(
            {
                (5, 5): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        boxed_escape = _captain_escape(Game(boxed), Player.ORANGE, Player.WHITE)
        open_escape = _captain_escape(Game(open_board), Player.ORANGE, Player.WHITE)
        self.assertGreater(open_escape, boxed_escape)

    def test_diagonal_distance_to_goal_counts_the_same_as_orthogonal(self):
        # The Captain moves one square in any of 8 directions per turn,
        # so a diagonal neighbour of the goal is exactly as urgent as an
        # orthogonal one for _captain_distance specifically, not
        # "further away" as a Manhattan count would suggest. Checked
        # against _captain_distance directly, not the full evaluate():
        # goal_area_control legitimately does score these two positions
        # differently (a captain adjacent to the goal orthogonally
        # overlaps more of the surrounding ring than one adjacent
        # diagonally), which isn't a Manhattan-vs-Chebyshev bug, just a
        # different feature answering a different question.
        diagonal = place_all(
            {
                (2, 2): make_captain(Player.WHITE),
                (8, 6): make_captain(Player.ORANGE),
            }
        )
        orthogonal = place_all(
            {
                (2, 3): make_captain(Player.WHITE),
                (8, 6): make_captain(Player.ORANGE),
            }
        )
        diagonal_score = _captain_distance(Game(diagonal), Player.ORANGE, Player.WHITE)
        orthogonal_score = _captain_distance(Game(orthogonal), Player.ORANGE, Player.WHITE)
        self.assertEqual(diagonal_score, orthogonal_score)


class SearchTests(unittest.TestCase):
    def _free_capture_position(self) -> Game:
        """Orange can capture White's only piece for free, or make a
        pointless sideways move instead — an easy position to check the
        AI actually prefers the capture."""
        board = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
                (3, 3): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        return Game(board)

    def test_the_easiest_level_still_takes_the_free_capture(self):
        # No randomness at any level any more — even level 1 (a single
        # ply, no quiescence or ordering) is still a real search, and a
        # free capture is visible one ply out.
        game = self._free_capture_position()
        self.assertEqual(choose_move(game, 1), ((5, 3), (3, 3)))

    def test_the_hardest_level_takes_the_free_capture(self):
        game = self._free_capture_position()
        self.assertEqual(choose_move(game, 10), ((5, 3), (3, 3)))

    def test_a_single_legal_move_is_returned_immediately(self):
        # The Captain (at (5, 5), well away from the goal) is boxed in
        # by its own immobile pieces on every side, so it's the only
        # piece with any move at all, and only one move at that.
        board = place_all(
            {
                (5, 5): make_captain(Player.ORANGE),
                (4, 4): Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT),
                (4, 5): Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT),
                (4, 6): Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT),
                (5, 4): Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT),
                (5, 6): Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT),
                (6, 4): Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT),
                (6, 5): Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        moves = game.all_legal_moves(Player.ORANGE)
        self.assertEqual(len(moves), 1)
        started = time.monotonic()
        move = choose_move(game, 10)
        elapsed = time.monotonic() - started
        self.assertEqual(move, moves[0])
        self.assertLess(elapsed, 0.5)

    def test_hard_stops_early_once_it_finds_a_forced_win(self):
        # Orange's Captain can march straight onto the goal this move,
        # winning outright; a second, unrelated piece gives it something
        # else to weigh that move against, so this isn't just testing
        # the single-legal-move shortcut above.
        goal_row, goal_col = next(iter(GOAL_SQUARES))
        start = (goal_row - 1, goal_col)
        board = place_all(
            {
                start: make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
                (5, 5): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            }
        )
        game = Game(board)
        started = time.monotonic()
        move = choose_move(game, 10)
        elapsed = time.monotonic() - started
        self.assertEqual(move, (start, (goal_row, goal_col)))
        self.assertLess(elapsed, 1.0)  # nowhere near the full time budget

    def test_unknown_difficulty_is_rejected(self):
        game = self._free_capture_position()
        with self.assertRaises(ValueError):
            choose_move(game, "impossible")

    def test_an_out_of_range_level_number_is_rejected(self):
        game = self._free_capture_position()
        with self.assertRaises(ValueError):
            choose_move(game, 0)
        with self.assertRaises(ValueError):
            choose_move(game, 11)


class LevelTests(unittest.TestCase):
    def _free_capture_position(self) -> Game:
        board = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
                (3, 3): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        return Game(board)

    def test_every_level_returns_a_legal_move(self):
        for number in range(1, 11):
            game = self._free_capture_position()
            move = choose_move(game, number)
            self.assertIn(
                move, game.all_legal_moves(Player.ORANGE), f"level {number} returned an illegal move"
            )

    def test_every_level_reliably_takes_the_free_capture(self):
        # No randomness at any level — this is completely deterministic
        # from level 1 up (see levels.py).
        for number in range(1, 11):
            game = self._free_capture_position()
            self.assertEqual(
                choose_move(game, number), ((5, 3), (3, 3)), f"level {number} missed the free capture"
            )

    def test_level_ten_stops_early_on_a_forced_win(self):
        goal_row, goal_col = next(iter(GOAL_SQUARES))
        start = (goal_row - 1, goal_col)
        board = place_all(
            {
                start: make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
                (5, 5): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            }
        )
        game = Game(board)
        started = time.monotonic()
        move = choose_move(game, 10)
        elapsed = time.monotonic() - started
        self.assertEqual(move, (start, (goal_row, goal_col)))
        self.assertLess(elapsed, 1.0)


class UpgradeTests(unittest.TestCase):
    def test_spends_every_point_it_can(self):
        mover = Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED))
        target = Piece(Player.WHITE, spokes=one_spoke(N, 1), bounty=8)
        board = place_all(
            {
                (5, 3): mover,
                (3, 3): target,
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        game.move((5, 3), (3, 3))
        self.assertIsNotNone(game.upgrade)
        spend_upgrade(game)
        self.assertEqual(game.upgrade.points, 0)

    def test_does_nothing_with_no_pending_upgrade(self):
        board = place_all({(8, 6): make_captain(Player.ORANGE)})
        game = Game(board)
        spend_upgrade(game)  # just shouldn't raise

    def test_prefers_defending_a_hanging_ally_over_raw_mobility(self):
        # The mover stands right next to an undefended, attacked ally: a
        # "W" spoke defends it (see _is_defended) but — blocked by that
        # very ally — adds not one single new move square, while every
        # other spoke opens exactly one new (irrelevant) square. The old
        # "whichever adds the most new squares" rule could never pick a
        # direction with zero gain; scoring the position itself, this
        # picks the one spoke that actually matters.
        W = 6
        ally = Piece(Player.ORANGE, spokes=one_spoke(N, 1))
        attacker = Piece(Player.WHITE, spokes=one_spoke(N, UNLIMITED))
        mover = Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT)
        board = place_all(
            {
                (5, 3): ally,
                (1, 3): attacker,
                (5, 4): mover,
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        self.assertFalse(_is_defended(board, (5, 3)))
        game.upgrade = PendingUpgrade(mover, 1)
        spend_upgrade(game, Weights())
        self.assertEqual(game.upgrade.points, 0)
        self.assertEqual(mover.spokes[W], 1)
        self.assertTrue(_is_defended(board, (5, 3)))


class BenchmarkTests(unittest.TestCase):
    def test_rusher_always_advances_the_captain_when_it_can(self):
        board = place_all(
            {
                (6, 3): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        src, dst = rusher_move(game)
        self.assertEqual(src, (6, 3))
        # (5, 3) is the one move straight toward the goal at (3, 3); any
        # other legal Captain move is sideways or worse.
        self.assertEqual(dst, (5, 3))

    def test_rusher_falls_back_to_search_with_nothing_useful_to_advance(self):
        # The Captain (at (5, 5), well away from the goal at (3, 3)) is
        # boxed in on every side by its own pieces, so rushing it is
        # impossible; the rusher should still return some legal move
        # rather than raising.
        board = place_all(
            {
                (5, 5): make_captain(Player.ORANGE),
                (4, 4): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (4, 5): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (4, 6): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (5, 4): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (5, 6): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (6, 4): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (6, 5): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (6, 6): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        src, dst = rusher_move(game)
        self.assertIn((src, dst), game.all_legal_moves(Player.ORANGE))

    def test_grabber_takes_the_single_biggest_capture_on_offer(self):
        # Two separate captures available, of clearly different value —
        # grabber should take the more expensive target, not just the
        # first one found.
        board = place_all(
            {
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
                (3, 3): Piece(Player.WHITE, spokes=one_spoke(N, 1)),  # cheap
                (5, 5): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
                (3, 5): Piece(Player.WHITE, spokes=one_spoke(N, UNLIMITED)),  # expensive
            }
        )
        game = Game(board)
        src, dst = grabber_move(game)
        self.assertEqual((src, dst), ((5, 5), (3, 5)))

    def test_grabber_falls_back_to_search_with_nothing_to_take(self):
        board = place_all(
            {
                (5, 3): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        src, dst = grabber_move(game)
        self.assertIn((src, dst), game.all_legal_moves(Player.ORANGE))

    def test_turtle_never_moves_the_captain_while_anything_else_can(self):
        board = place_all(
            {
                (5, 3): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
                (4, 4): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            }
        )
        game = Game(board)
        src, _dst = turtle_move(game)
        self.assertNotEqual(src, (5, 3))

    def test_turtle_falls_back_to_the_captain_with_nothing_else_to_move(self):
        board = place_all(
            {
                (5, 3): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        src, dst = turtle_move(game)
        self.assertIn((src, dst), game.all_legal_moves(Player.ORANGE))

    def test_hoarder_never_captures_while_a_quiet_move_exists(self):
        board = place_all(
            {
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
                (3, 3): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
            }
        )
        game = Game(board)
        _src, dst = hoarder_move(game)
        self.assertIsNone(game.board.get(dst))

    def test_hoarder_still_returns_a_legal_move_with_nothing_to_avoid(self):
        board = place_all(
            {
                (5, 3): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        src, dst = hoarder_move(game)
        self.assertIn((src, dst), game.all_legal_moves(Player.ORANGE))

    def test_opportunist_takes_a_free_capture_over_racing(self):
        board = place_all(
            {
                (6, 1): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
                (5, 5): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
                (3, 5): Piece(Player.WHITE, spokes=one_spoke(N, 1)),  # undefended
            }
        )
        game = Game(board)
        src, dst = opportunist_move(game)
        self.assertEqual((src, dst), ((5, 5), (3, 5)))

    def test_opportunist_ignores_a_defended_capture_and_races_instead(self):
        # (3, 5) is now defended by the all-directions piece at (3, 6) —
        # not a free capture any more, so opportunist should fall
        # through to exactly what rusher_move would do here.
        board = place_all(
            {
                (6, 1): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
                (5, 5): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
                (3, 5): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
                (3, 6): Piece(Player.WHITE, spokes=[UNLIMITED] * SPOKE_COUNT),
            }
        )
        game = Game(board)
        self.assertEqual(opportunist_move(game), rusher_move(game))


class CMAESTests(unittest.TestCase):
    """CMA-ES is what spokebound.ai.evolve/evolve_fleet actually search
    Weights/FleetRules space with — these tests validate the
    from-scratch linear algebra and optimizer against known-correct
    results on cheap, analytic functions, entirely separate from real
    game-playing, so a bug here can't hide behind game-outcome noise."""

    def test_jacobi_eigh_recovers_known_eigenvalues(self):
        # A diagonal matrix's eigenvalues are just its diagonal.
        diagonal = [[3.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 2.0]]
        values, _ = jacobi_eigh(diagonal)
        self.assertEqual(sorted(round(v, 9) for v in values), [1.0, 2.0, 3.0])

        # [[2,1],[1,2]] has known eigenvalues 1 and 3.
        known = [[2.0, 1.0], [1.0, 2.0]]
        values, vectors = jacobi_eigh(known)
        self.assertEqual(sorted(round(v, 9) for v in values), [1.0, 3.0])
        # A @ v == lambda * v for every recovered eigenpair.
        n = len(known)
        for k in range(n):
            v = [vectors[i][k] for i in range(n)]
            av = [sum(known[i][j] * v[j] for j in range(n)) for i in range(n)]
            lv = [values[k] * x for x in v]
            for a, b in zip(av, lv, strict=True):
                self.assertAlmostEqual(a, b, places=9)

    def test_cma_es_converges_on_a_simple_offset_quadratic(self):
        # Unequal per-dimension scales, so this can't be solved by
        # treating every field independently — sigma has to shrink
        # non-uniformly across the 4 axes for this to converge cleanly.
        target = [3.0, -2.0, 5.0, 0.5]

        def fitness(x):
            return -sum((xi - ti) ** 2 for xi, ti in zip(x, target, strict=True))

        es = CMAES([0.0] * len(target), sigma0=2.0, population_size=10, rng=random.Random(0))
        for _ in range(60):
            candidates = es.ask()
            es.tell(candidates, [fitness(c) for c in candidates])
        distance = math.sqrt(sum((m - t) ** 2 for m, t in zip(es.mean, target, strict=True)))
        self.assertLess(distance, 0.05)

    def test_run_cma_es_returns_the_right_genome_type_and_converges(self):
        # Wires the driver's genome<->vector conversion through a tiny,
        # fast, synthetic fitness (distance from an arbitrary target
        # Weights) rather than real games — this is testing the
        # plumbing, not asking CMA-ES to play chess.
        target = DEFAULT_WEIGHTS.nudged("material", 1.5).nudged("mobility", 0.5)
        target_vec = [getattr(target, f) for f in target.field_names()]

        def evaluate_population(genomes, incumbent):
            del incumbent  # unused — this test isn't exercising it
            return [
                -sum(
                    (getattr(genome, f) - t) ** 2
                    for f, t in zip(genome.field_names(), target_vec, strict=True)
                )
                for genome in genomes
            ]

        result = run_cma_es(
            label="test",
            seed_genome=DEFAULT_WEIGHTS,
            sigma0=0.5,
            evaluate_population=evaluate_population,
            generations=40,
            population_size=10,
            seed=0,
        )
        self.assertIsInstance(result, Weights)
        for field, expected in zip(target.field_names(), target_vec, strict=True):
            self.assertAlmostEqual(getattr(result, field), expected, places=1)

    def test_run_cma_es_passes_the_pre_update_mean_as_incumbent(self):
        # The incumbent handed to evaluate_population should be the
        # search distribution's mean *before* that generation's own
        # update — generation 1's incumbent is therefore exactly the
        # seed (nothing has updated yet), and generation 2's incumbent
        # should differ from generation 1's (the mean moved after
        # generation 1's tell()), not be a copy of whatever the
        # population looked like that generation.
        seen_incumbents = []

        def evaluate_population(genomes, incumbent):
            seen_incumbents.append(incumbent)
            return [
                -sum(
                    (getattr(genome, f) - getattr(DEFAULT_WEIGHTS, f) - 1) ** 2 for f in genome.field_names()
                )
                for genome in genomes
            ]

        run_cma_es(
            label="test",
            seed_genome=DEFAULT_WEIGHTS,
            sigma0=0.5,
            evaluate_population=evaluate_population,
            generations=2,
            population_size=6,
            seed=0,
        )
        self.assertEqual(seen_incumbents[0], DEFAULT_WEIGHTS)
        self.assertNotEqual(seen_incumbents[1], DEFAULT_WEIGHTS)
        self.assertNotEqual(seen_incumbents[0], seen_incumbents[1])

    def _toy_evaluate(self, genomes, incumbent):
        del incumbent
        return [
            -sum((getattr(genome, f) - getattr(DEFAULT_WEIGHTS, f)) ** 2 for f in genome.field_names())
            for genome in genomes
        ]

    def test_save_state_and_restore_round_trips_exactly(self):
        field_names = DEFAULT_WEIGHTS.field_names()
        es = CMAES(
            _to_vector(DEFAULT_WEIGHTS, field_names), sigma0=0.5, population_size=6, rng=random.Random(0)
        )
        for _ in range(2):
            candidates = es.ask()
            es.tell(
                candidates,
                self._toy_evaluate(
                    [Weights(**dict(zip(field_names, c, strict=True))) for c in candidates], None
                ),
            )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_state(path, es, field_names, "test", seed=0)
            restored = _restore(load_state(path), random.Random(0))

        self.assertEqual(restored.mean, es.mean)
        self.assertEqual(restored.sigma, es.sigma)
        self.assertEqual(restored.C, es.C)
        self.assertEqual(restored.p_sigma, es.p_sigma)
        self.assertEqual(restored.p_c, es.p_c)
        self.assertEqual(restored.generation, es.generation)
        self.assertEqual(restored.params.population_size, es.params.population_size)

    def test_run_cma_es_resume_continues_instead_of_restarting(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            calls = []

            def counting_evaluate(genomes, incumbent):
                calls.append(incumbent)
                return self._toy_evaluate(genomes, incumbent)

            run_cma_es(
                label="test",
                seed_genome=DEFAULT_WEIGHTS,
                sigma0=0.5,
                evaluate_population=counting_evaluate,
                generations=3,
                population_size=6,
                state_path=state_path,
                seed=0,
            )
            self.assertEqual(len(calls), 3)

            calls.clear()
            run_cma_es(
                label="test",
                seed_genome=DEFAULT_WEIGHTS,
                sigma0=0.5,
                evaluate_population=counting_evaluate,
                generations=6,
                population_size=6,
                state_path=state_path,
                seed=0,
            )
            # Only the 3 remaining generations (4, 5, 6) get evaluated —
            # not 6 fresh ones — and the resumed run continues from
            # wherever generation 3 actually left off, not the seed.
            self.assertEqual(len(calls), 3)
            self.assertNotEqual(calls[0], DEFAULT_WEIGHTS)

    def test_run_cma_es_resume_false_ignores_existing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            calls = []

            def counting_evaluate(genomes, incumbent):
                calls.append(incumbent)
                return self._toy_evaluate(genomes, incumbent)

            run_cma_es(
                label="test",
                seed_genome=DEFAULT_WEIGHTS,
                sigma0=0.5,
                evaluate_population=counting_evaluate,
                generations=3,
                population_size=6,
                state_path=state_path,
                seed=0,
            )
            calls.clear()
            run_cma_es(
                label="test",
                seed_genome=DEFAULT_WEIGHTS,
                sigma0=0.5,
                evaluate_population=counting_evaluate,
                generations=2,
                population_size=6,
                state_path=state_path,
                resume=False,
                seed=0,
            )
            # Starts over from generation 1 (2 fresh generations), not
            # from the 3 already saved — and the first incumbent it
            # sees is the seed again, not wherever the old run got to.
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], DEFAULT_WEIGHTS)

    def test_run_cma_es_rejects_a_state_file_for_a_different_genome_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with state_path.open("w", encoding="utf-8") as f:
                json.dump(
                    {
                        "field_names": ["not", "a", "real", "shape"],
                        "seed": 0,
                        "population_size": 6,
                        "generation": 1,
                        "sigma": 0.5,
                        "mean": [0, 0, 0, 0],
                        "C": [[1]],
                        "p_sigma": [0],
                        "p_c": [0],
                    },
                    f,
                )
            with self.assertRaises(ValueError):
                run_cma_es(
                    label="test",
                    seed_genome=DEFAULT_WEIGHTS,
                    sigma0=0.5,
                    evaluate_population=self._toy_evaluate,
                    generations=1,
                    population_size=6,
                    state_path=state_path,
                )


class EvolveScoringTests(unittest.TestCase):
    """spokebound.ai.evolve/evolve_fleet's own margin-of-victory scoring
    and hall-of-fame bookkeeping — pure, fast, non-game-playing pieces
    of logic worth locking in directly, the same way CMAESTests does
    for the optimizer itself."""

    def test_score_outcome_always_dominates_margin(self):
        import spokebound.ai.evolve as evolve

        # However lopsided the margin, a win never scores below a draw,
        # and a draw never scores below a loss.
        self.assertGreater(evolve._score("win", -1000), evolve._score("draw", 1000))
        self.assertGreater(evolve._score("draw", -1000), evolve._score("loss", 1000))

    def test_score_margin_refines_within_the_same_outcome(self):
        import spokebound.ai.evolve as evolve

        self.assertGreater(evolve._score("win", 20), evolve._score("win", 5))
        self.assertGreater(evolve._score("loss", -5), evolve._score("loss", -20))

    def test_score_matches_between_evolve_and_evolve_fleet(self):
        import spokebound.ai.evolve as evolve
        import spokebound.ai.evolve_fleet as evolve_fleet

        for outcome, margin in [("win", 12), ("draw", 0), ("loss", -7)]:
            self.assertEqual(evolve._score(outcome, margin), evolve_fleet._score(outcome, margin))

    def test_add_to_hall_of_fame_keeps_only_the_newest_entries(self):
        import spokebound.ai.evolve as evolve

        hall_of_fame = []
        seeds = [DEFAULT_WEIGHTS.nudged("material", factor) for factor in (1.1, 1.2, 1.3, 1.4)]
        for seed in seeds:
            evolve._add_to_hall_of_fame(hall_of_fame, seed)
        self.assertEqual(len(hall_of_fame), evolve.HALL_OF_FAME_SIZE)
        # The oldest (first-added) entry was evicted; the newest 3 remain.
        self.assertEqual(hall_of_fame, seeds[-evolve.HALL_OF_FAME_SIZE :])

    def test_hall_of_fame_save_and_load_round_trips(self):
        import spokebound.ai.evolve as evolve

        with tempfile.TemporaryDirectory() as tmp:
            original_path = evolve.HALL_OF_FAME_PATH
            evolve.HALL_OF_FAME_PATH = Path(tmp) / "hall_of_fame.json"
            try:
                saved = [DEFAULT_WEIGHTS, DEFAULT_WEIGHTS.nudged("mobility", 2.0)]
                evolve._save_hall_of_fame(saved)
                loaded = evolve._load_hall_of_fame()
                self.assertEqual(loaded, saved)
            finally:
                evolve.HALL_OF_FAME_PATH = original_path

    def test_play_full_game_result_carries_plausible_final_scores(self):
        # A tiny, fast, fully-deterministic game (level 1) — checking
        # GameResult's scores are real board-derived numbers. Never
        # negative — but *can* exceed BUILD_BUDGET (bounty upgrades
        # during play let a piece grow past what it originally cost to
        # build), so this only checks the one real invariant.
        from spokebound.ai.selfplay import play_full_game

        orange_fleet = build_fleet(1, Player.ORANGE)
        white_fleet = build_fleet(1, Player.WHITE)

        def choose_for(player):
            return lambda game: choose_move(game, 1)

        result = play_full_game(orange_fleet, white_fleet, choose_for)
        self.assertGreaterEqual(result.orange_score, 0)
        self.assertGreaterEqual(result.white_score, 0)


class BuildTests(unittest.TestCase):
    def test_returns_a_full_fleet_within_budget(self):
        fleet = build_fleet(1, Player.ORANGE)
        self.assertEqual(len(fleet), FLEET_SIZE)
        self.assertTrue(all(p.owner is Player.ORANGE for p in fleet))
        self.assertLessEqual(sum(p.cost for p in fleet), BUILD_BUDGET)

    def test_a_low_skill_level_still_returns_a_full_fleet_within_budget(self):
        # Level 1 has pregame_skill=0.0 (built almost entirely from
        # NEUTRAL_FLEET_RULES) — make sure that blended-toward-neutral
        # path still produces a legitimate fleet.
        fleet = build_fleet(1, Player.WHITE)
        self.assertEqual(len(fleet), FLEET_SIZE)
        self.assertLessEqual(sum(p.cost for p in fleet), BUILD_BUDGET)

    def test_a_bare_level_number_blends_rules_by_its_own_pregame_skill(self):
        # No explicit rules given: build_fleet_spec should derive them
        # from NEUTRAL_FLEET_RULES blended toward DEFAULT_FLEET_RULES by
        # that level's own pregame_skill — check the derivation directly
        # rather than just that *some* fleet comes out.
        from spokebound.ai.build import _rules_for_level
        from spokebound.ai.config import NEUTRAL_FLEET_RULES
        from spokebound.ai.levels import LEVELS

        expected = NEUTRAL_FLEET_RULES.blended(DEFAULT_FLEET_RULES, LEVELS[6].pregame_skill)
        self.assertEqual(_rules_for_level(6), expected)

    def test_an_unknown_level_number_falls_back_to_full_strength_rules(self):
        from spokebound.ai.build import _rules_for_level

        self.assertEqual(_rules_for_level(999), DEFAULT_FLEET_RULES)

    def test_no_level_ever_looks_at_an_opponents_fleet(self):
        # build_fleet/build_fleet_spec take no opponent_fleet argument
        # at all any more — nothing in the AI ever peeks at what the
        # other side built (see spokebound.ai.levels).
        import inspect

        self.assertNotIn("opponent_fleet", inspect.signature(build_fleet).parameters)
        self.assertNotIn("opponent_fleet", inspect.signature(build_fleet_spec).parameters)

    def test_every_generated_fleet_gives_every_piece_a_legal_move(self):
        # Every piece reserves one level-1 spoke before the rest of the
        # budget is spent freely, specifically so nothing ends up
        # unable to move at all — check that holds across a spread of
        # very different rules, not just the default.
        rules_to_try = [
            DEFAULT_FLEET_RULES,
            FleetRules(bias_n=10.0),
            FleetRules(concentration=3.0),
            FleetRules(concentration=0.2),
            FleetRules(variety=1.0),
        ]
        for rules in rules_to_try:
            for _ in range(5):
                spec = build_fleet_spec(1, rules=rules)
                for piece in spec:
                    cost = sum(LEVEL_COSTS[level] for level in piece)
                    self.assertGreaterEqual(cost, MIN_PIECE_COST, f"a 0-cost piece under {rules}")


class FleetSpecTests(unittest.TestCase):
    """build_fleet_spec/materialize_fleet split a fleet's design from
    who owns it, so the same design can be given to both sides of a
    self-play game (see spokebound.ai.evolve) instead of two
    independently-random ones."""

    def test_build_fleet_returns_the_same_as_materializing_its_own_spec(self):
        import random

        state = random.getstate()
        random.seed(0)
        spec = build_fleet_spec(1)
        random.setstate(state)
        random.seed(0)
        fleet = build_fleet(1, Player.ORANGE)
        random.setstate(state)
        self.assertEqual([list(p.spokes) for p in fleet], spec)

    def test_materialize_fleet_owns_every_piece(self):
        spec = build_fleet_spec(1)
        orange = materialize_fleet(spec, Player.ORANGE)
        white = materialize_fleet(spec, Player.WHITE)
        self.assertTrue(all(p.owner is Player.ORANGE for p in orange))
        self.assertTrue(all(p.owner is Player.WHITE for p in white))
        self.assertEqual([list(p.spokes) for p in orange], [list(p.spokes) for p in white])

    def test_a_dominant_direction_bias_usually_wins_the_weighted_pick(self):
        # Every other direction biased near zero (but never literally
        # zero — _weighted_direction floors every direction at a small
        # minimum weight, and variety=0 still leaves the floor in
        # place) — N should still be picked the great majority of the
        # time.
        import random

        from spokebound.ai.build import _weighted_direction

        rng_state = random.getstate()
        random.seed(0)
        rules = FleetRules(
            bias_n=1.0,
            bias_ne=0.0001,
            bias_e=0.0001,
            bias_se=0.0001,
            bias_s=0.0001,
            bias_sw=0.0001,
            bias_w=0.0001,
            bias_nw=0.0001,
            variety=0.0,
        )
        picks = [_weighted_direction(rules) for _ in range(200)]
        random.setstate(rng_state)
        self.assertGreater(picks.count(N), 180)

    def test_a_forward_biased_fleet_spends_most_of_its_budget_forward(self):
        # The concrete feature this redesign is for: a fleet built
        # under a heavy forward (N) bias should actually end up with
        # most of its points spent on N, aggregated across the whole
        # fleet — not just a bias field with no visible effect. (A
        # single direction can never exceed FLEET_SIZE *
        # LEVEL_COSTS[UNLIMITED] — every piece maxed out on it and
        # nothing else — which happens to be exactly half of
        # BUILD_BUDGET, so "most of" is checked against that real
        # ceiling, not naively against the other 7 directions' total.)
        rules = FleetRules(
            bias_n=20.0,
            bias_ne=1.0,
            bias_e=1.0,
            bias_se=1.0,
            bias_s=1.0,
            bias_sw=1.0,
            bias_w=1.0,
            bias_nw=1.0,
            variety=0.05,
        )
        spec = build_fleet_spec(1, rules=rules)
        totals = [0] * SPOKE_COUNT
        for piece in spec:
            for spoke, level in enumerate(piece):
                totals[spoke] += LEVEL_COSTS[level]
        ceiling = FLEET_SIZE * LEVEL_COSTS[UNLIMITED]
        self.assertEqual(max(range(SPOKE_COUNT), key=lambda i: totals[i]), N)
        self.assertGreaterEqual(totals[N], ceiling - LEVEL_COSTS[UNLIMITED])


class FleetRulesTests(unittest.TestCase):
    def test_field_names_cover_every_field(self):
        self.assertEqual(
            set(DEFAULT_FLEET_RULES.field_names()),
            {
                "bias_n",
                "bias_ne",
                "bias_e",
                "bias_se",
                "bias_s",
                "bias_sw",
                "bias_w",
                "bias_nw",
                "concentration",
                "variety",
            },
        )

    def test_nudged_scales_one_field_only(self):
        nudged = DEFAULT_FLEET_RULES.nudged("concentration", 2.0)
        self.assertEqual(nudged.concentration, DEFAULT_FLEET_RULES.concentration * 2.0)
        self.assertEqual(nudged.bias_n, DEFAULT_FLEET_RULES.bias_n)

    def test_describe_diff_reports_zero_change_against_itself(self):
        text = DEFAULT_FLEET_RULES.describe_diff(DEFAULT_FLEET_RULES)
        self.assertIn("+0%", text)
        self.assertNotIn("nan", text.lower())


class _FakePool:
    """A stand-in for multiprocessing.Pool that runs everything
    synchronously, in-process — play_round's own task-building/prepare
    logic doesn't depend on real subprocess behaviour, so a fast, plain
    ``map`` is enough to test it without real multiprocessing overhead."""

    def imap_unordered(self, func, iterable):
        return map(func, iterable)


class PlayRoundTests(unittest.TestCase):
    def test_without_prepare_every_game_shares_the_same_static_args(self):
        seen = []

        def play_game_fn(a, b):
            seen.append((a, b))
            return Player.ORANGE

        play_round(_FakePool(), play_game_fn, a="A", b="B", games=6)
        # Every task sees the same static pair, just colour-swapped —
        # the pre-existing behaviour every non-evolve.py caller
        # (tournament.py, evolve_fleet.py's own play_game) relies on.
        self.assertTrue(all(pair in (("A", "B"), ("B", "A")) for pair in seen))

    def test_prepare_is_called_once_per_pair_not_once_per_game(self):
        calls = []

        def prepare():
            calls.append(1)
            return (f"a{len(calls)}", f"b{len(calls)}")

        def play_game_fn(a, b):
            return Player.ORANGE

        play_round(_FakePool(), play_game_fn, games=6, prepare=prepare)
        self.assertEqual(len(calls), 3)  # 6 games / 2 per pair

    def test_a_prepared_pair_is_shared_by_both_games_in_its_round(self):
        prepared = [("a1", "b1"), ("a2", "b2")]

        def prepare():
            return prepared.pop(0)

        seen = []

        def play_game_fn(a, b):
            seen.append((a, b))
            return Player.ORANGE

        play_round(_FakePool(), play_game_fn, games=4, prepare=prepare)
        # Tasks 0-1 share the first prepared pair, tasks 2-3 the second
        # (colour-swapped within each pair) — a genuinely fresh fleet
        # every round, not the same one replayed for both colours.
        self.assertEqual(seen[0], ("a1", "b1"))
        self.assertEqual(seen[1], ("b1", "a1"))
        self.assertEqual(seen[2], ("a2", "b2"))
        self.assertEqual(seen[3], ("b2", "a2"))


class DeployTests(unittest.TestCase):
    def test_returns_a_legal_square_for_the_ai_to_place_on(self):
        orange = FleetBuilder(Player.ORANGE)
        for piece in orange.pieces:
            piece.spokes = one_spoke(N, 1)
        white = FleetBuilder(Player.WHITE)
        for piece in white.pieces:
            piece.spokes = one_spoke(N, 1)
        deployment = Deployment(orange.pieces, white.pieces)
        square = choose_deploy_square(deployment, Player.ORANGE)
        self.assertIn(square, deployment.legal_squares())

    def test_chooses_whichever_legal_square_scores_best(self):
        # Not a fixed row rule any more (see choose_deploy_square) — it
        # tries every legal square and keeps whichever actually scores
        # best for the deploying player, so this checks that contract
        # directly rather than a specific expected square.
        orange = FleetBuilder(Player.ORANGE)
        orange.pieces[0].spokes = one_spoke(N, UNLIMITED)  # the strongest
        for piece in orange.pieces[1:]:
            piece.spokes = one_spoke(N, 1)
        white = FleetBuilder(Player.WHITE)
        for piece in white.pieces:
            piece.spokes = one_spoke(N, 1)
        deployment = Deployment(orange.pieces, white.pieces)
        board = deployment.board
        piece = deployment.next_piece(Player.ORANGE)
        legal = deployment.legal_squares()

        def score_at(square):
            board.place(square, piece)
            result = evaluate(Game(board), Player.ORANGE, DEFAULT_WEIGHTS)
            board.remove(square)
            return result

        best_score = max(score_at(square) for square in legal)
        chosen = choose_deploy_square(deployment, Player.ORANGE)
        self.assertIs(deployment.next_piece(Player.ORANGE), piece)
        self.assertEqual(score_at(chosen), best_score)

    def test_low_skill_stops_reliably_choosing_the_best_square(self):
        # skill (see spokebound.ai.levels.Level.pregame_skill) trusts
        # the very same evaluation less, rather than switching to some
        # separate "dumb" rule — so at skill=0.0 the choice should
        # genuinely vary across repeats of the same position, and at
        # skill=1.0 (the default) it should still always be the single
        # best-scoring square, exactly as before this knob existed.
        import random

        def make_deployment() -> Deployment:
            orange = FleetBuilder(Player.ORANGE)
            orange.pieces[0].spokes = one_spoke(N, UNLIMITED)
            for piece in orange.pieces[1:]:
                piece.spokes = one_spoke(N, 1)
            white = FleetBuilder(Player.WHITE)
            for piece in white.pieces:
                piece.spokes = one_spoke(N, 1)
            return Deployment(orange.pieces, white.pieces)

        rng_state = random.getstate()
        random.seed(0)
        low_skill_squares = {
            choose_deploy_square(make_deployment(), Player.ORANGE, skill=0.0) for _ in range(30)
        }
        full_skill_squares = {
            choose_deploy_square(make_deployment(), Player.ORANGE, skill=1.0) for _ in range(30)
        }
        random.setstate(rng_state)
        self.assertGreater(len(low_skill_squares), 1)
        self.assertEqual(len(full_skill_squares), 1)


class FullGameSmokeTests(unittest.TestCase):
    """Runs a whole AI-vs-AI game end to end, to catch anything the
    narrower tests above wouldn't (a phase handing the next one
    something it doesn't expect, an infinite loop, an unhandled
    exception on some rarer board shape)."""

    def test_level_one_plays_to_completion(self):
        orange_fleet = build_fleet(1, Player.ORANGE)
        white_fleet = build_fleet(1, Player.WHITE)
        deployment = Deployment(orange_fleet, white_fleet)
        while not deployment.is_done:
            square = choose_deploy_square(deployment, deployment.current)
            deployment.place(square)

        game = Game(deployment.board)
        for _ in range(300):  # generous ceiling against a real bug looping
            if game.is_over:
                break
            move = choose_move(game, 1)
            game.move(*move)
            if game.upgrade is not None:
                spend_upgrade(game)
                game.finish_turn()
        self.assertTrue(game.is_over)

    def test_the_full_engine_plays_to_completion(self):
        # The real top level's time/depth budget (up to several
        # seconds a move) would make a full game far too slow for a
        # unit test; this only needs to exercise the whole search path
        # (quiescence, ordering, the transposition table, iterative
        # deepening, killer moves, check extensions) without hanging
        # the suite — a fast Level of its own, not one of the 10
        # player-facing rungs, does that (see choose_move_at).
        fast_level = Level(
            number=99,
            name="Test",
            min_depth=2,
            max_depth=4,
            time_limit=0.1,
            critical_time_limit=0.2,
            use_quiescence=True,
            use_move_ordering=True,
            use_transposition_table=True,
            pregame_skill=1.0,
        )
        orange_fleet = materialize_fleet(build_fleet_spec(fast_level.number), Player.ORANGE)
        white_fleet = materialize_fleet(build_fleet_spec(fast_level.number), Player.WHITE)
        deployment = Deployment(orange_fleet, white_fleet)
        while not deployment.is_done:
            square = choose_deploy_square(deployment, deployment.current)
            deployment.place(square)

        game = Game(deployment.board)
        for _ in range(600):  # generous ceiling against a real bug looping
            if game.is_over:
                break
            move = choose_move_at(game, fast_level)
            game.move(*move)
            if game.upgrade is not None:
                spend_upgrade(game)
                game.finish_turn()
        self.assertTrue(game.is_over)


class CriticalityTests(unittest.TestCase):
    def test_check_is_critical(self):
        # Orange's piece already threatens (3, 3) where White's Captain
        # stands, no move needed to see the check.
        mover = Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED))
        board = place_all(
            {
                (5, 3): mover,
                (8, 3): make_captain(Player.ORANGE),
                (3, 3): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        self.assertTrue(game.in_check(Player.WHITE))
        self.assertTrue(is_critical(game))

    def test_an_unguarded_close_captain_is_critical(self):
        board = place_all(
            {
                (8, 6): make_captain(Player.ORANGE),
                (2, 3): make_captain(Player.WHITE),  # one move from (3, 3)
            }
        )
        self.assertTrue(is_critical(Game(board)))

    def test_a_hanging_valuable_piece_is_critical(self):
        # Two unlimited spokes: 4 + 4 = 8 points, right at
        # CRITICAL_PIECE_VALUE.
        hanging = Piece(Player.ORANGE, spokes=[UNLIMITED, 0, UNLIMITED, 0, 0, 0, 0, 0])
        attacker = Piece(Player.WHITE, spokes=one_spoke(N, UNLIMITED))
        board = place_all(
            {
                (5, 3): hanging,
                (1, 3): attacker,
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        self.assertEqual(hanging.cost, 8)
        self.assertIn((5, 3), Game(board).board.legal_moves((1, 3)))
        self.assertTrue(is_critical(Game(board)))

    def test_a_calm_midgame_position_is_not_critical(self):
        board = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (1, 3): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
                (6, 0): make_captain(Player.ORANGE),
                (0, 6): make_captain(Player.WHITE),
            }
        )
        self.assertFalse(is_critical(Game(board)))


class MoveOrderingTests(unittest.TestCase):
    def test_captures_are_tried_before_quiet_moves(self):
        mover = Piece(Player.ORANGE, spokes=[UNLIMITED] * SPOKE_COUNT)
        board = place_all(
            {
                (3, 3): mover,
                (3, 6): Piece(Player.WHITE, spokes=one_spoke(N, 1)),  # capturable
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        moves = game.all_legal_moves(Player.ORANGE)
        ordered = _order_moves(game, moves, tt_move=None)
        self.assertEqual(ordered[0], ((3, 3), (3, 6)))

    def test_the_transposition_table_move_is_tried_first(self):
        mover = Piece(Player.ORANGE, spokes=[UNLIMITED] * SPOKE_COUNT)
        board = place_all(
            {
                (3, 3): mover,
                (3, 6): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        moves = game.all_legal_moves(Player.ORANGE)
        tt_move = ((3, 3), (4, 4))  # a quiet move, not the capture
        ordered = _order_moves(game, moves, tt_move)
        self.assertEqual(ordered[0], tt_move)

    def test_gives_check_detects_a_move_that_attacks_the_enemy_captain(self):
        # N (forward) unlimited, W one square, so it has a real choice
        # between staying on the Captain's file (check) and stepping off
        # it (no check) — a pure N-only piece can only ever move along
        # that one file, so both moves would "give check" trivially.
        W = 6
        mover = Piece(Player.ORANGE, spokes=[UNLIMITED, 0, 0, 0, 0, 0, 0, 0])
        mover.spokes[W] = 1
        board = place_all(
            {
                (5, 3): mover,
                (8, 6): make_captain(Player.ORANGE),
                (2, 3): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        self.assertTrue(_gives_check(game.board, ((5, 3), (3, 3)), Player.ORANGE))
        self.assertFalse(_gives_check(game.board, ((5, 3), (5, 2)), Player.ORANGE))
        # Simulating for the check test must not leave the board changed.
        self.assertIsNotNone(game.board.get((5, 3)))
        self.assertIsNone(game.board.get((3, 3)))

    def test_a_killer_move_is_tried_before_a_check_or_other_quiet_moves(self):
        W = 6
        mover = Piece(Player.ORANGE, spokes=[UNLIMITED, 0, 0, 0, 0, 0, 0, 0])
        mover.spokes[W] = 1
        board = place_all(
            {
                (5, 3): mover,
                (8, 6): make_captain(Player.ORANGE),
                (2, 3): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        moves = game.all_legal_moves(Player.ORANGE)
        killer_move = ((5, 3), (5, 2))  # quiet, not a check (see above)
        check_move = ((5, 3), (3, 3))
        self.assertIn(killer_move, moves)
        self.assertIn(check_move, moves)
        ordered = _order_moves(game, moves, tt_move=None, killer_moves=[killer_move], history=None)
        self.assertLess(ordered.index(killer_move), ordered.index(check_move))


class RecordCutoffTests(unittest.TestCase):
    """Tests for _record_cutoff, the killer-move/history bookkeeping a
    beta cutoff during alpha-beta feeds back into move ordering (see
    _alpha_beta and _order_moves)."""

    def _open_board_position(self) -> Game:
        mover = Piece(Player.ORANGE, spokes=[UNLIMITED] * SPOKE_COUNT)
        board = place_all(
            {
                (3, 3): mover,
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        return Game(board)

    def test_a_quiet_move_is_recorded_as_a_killer_and_bumps_history(self):
        game = self._open_board_position()
        quiet_move = ((3, 3), (3, 4))
        self.assertIsNone(game.board.get(quiet_move[1]))
        killers: dict = {}
        history: dict = {}
        _record_cutoff(game, quiet_move, 3, killers, history)
        self.assertEqual(killers[3], [quiet_move])
        self.assertEqual(history[quiet_move], 9)  # depth ** 2

    def test_a_capture_is_not_recorded_as_a_killer(self):
        mover = Piece(Player.ORANGE, spokes=[UNLIMITED] * SPOKE_COUNT)
        target = Piece(Player.WHITE, spokes=one_spoke(N, 1))
        board = place_all(
            {
                (3, 3): mover,
                (3, 6): target,
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        capture_move = ((3, 3), (3, 6))
        killers: dict = {}
        history: dict = {}
        _record_cutoff(game, capture_move, 2, killers, history)
        self.assertEqual(killers, {})
        self.assertEqual(history, {})

    def test_killer_bucket_keeps_only_the_most_recent_entries(self):
        game = self._open_board_position()
        killers: dict = {}
        history: dict = {}
        moves = [((3, 3), (3, 4)), ((3, 3), (3, 5)), ((3, 3), (4, 3))]
        for move in moves:
            _record_cutoff(game, move, 1, killers, history)
        self.assertEqual(len(killers[1]), _KILLERS_PER_DEPTH)
        self.assertEqual(killers[1][0], moves[-1])


class CheckExtensionTests(unittest.TestCase):
    """Tests for _extended_depth: a move that gives check gets one extra
    ply of search rather than being cut off at the normal depth limit
    (see _alpha_beta/_alpha_beta_root), up to _MAX_CHECK_EXTENSIONS
    total per line."""

    def _position(self) -> Game:
        W = 6
        mover = Piece(Player.ORANGE, spokes=[UNLIMITED, 0, 0, 0, 0, 0, 0, 0])
        mover.spokes[W] = 1
        board = place_all(
            {
                (5, 3): mover,
                (8, 6): make_captain(Player.ORANGE),
                (2, 3): make_captain(Player.WHITE),
            }
        )
        return Game(board)

    def test_extends_when_the_move_gives_check(self):
        game = self._position()
        child = apply_move(game, ((5, 3), (3, 3)), DEFAULT_WEIGHTS)
        self.assertTrue(child.in_check(child.current))
        depth, extensions_left = _extended_depth(child, 0, _MAX_CHECK_EXTENSIONS)
        self.assertEqual(depth, 1)
        self.assertEqual(extensions_left, _MAX_CHECK_EXTENSIONS - 1)

    def test_does_not_extend_a_quiet_move(self):
        game = self._position()
        child = apply_move(game, ((5, 3), (5, 2)), DEFAULT_WEIGHTS)
        self.assertFalse(child.in_check(child.current))
        depth, extensions_left = _extended_depth(child, 2, _MAX_CHECK_EXTENSIONS)
        self.assertEqual((depth, extensions_left), (2, _MAX_CHECK_EXTENSIONS))

    def test_does_not_extend_once_the_budget_is_spent(self):
        game = self._position()
        child = apply_move(game, ((5, 3), (3, 3)), DEFAULT_WEIGHTS)
        depth, extensions_left = _extended_depth(child, 0, 0)
        self.assertEqual((depth, extensions_left), (0, 0))


class TerminalScoreTests(unittest.TestCase):
    """_terminal_score is what _alpha_beta/_quiescence score a finished
    game with, instead of evaluate() directly — see the note there on
    why: preferring the fastest win, and the slowest loss, among
    otherwise-equally-decisive lines."""

    def test_a_win_found_with_more_plies_in_hand_scores_higher(self):
        board = place_all({(8, 3): make_captain(Player.ORANGE)})
        game = Game(board)
        game.outcome = Outcome(winner=Player.ORANGE, reason="test")
        sooner = _terminal_score(game, Player.ORANGE, DEFAULT_WEIGHTS, 5)
        later = _terminal_score(game, Player.ORANGE, DEFAULT_WEIGHTS, 1)
        self.assertGreater(sooner, later)
        self.assertGreaterEqual(later, DECISIVE_SCORE)

    def test_a_loss_found_with_more_plies_in_hand_scores_lower(self):
        board = place_all({(8, 3): make_captain(Player.ORANGE)})
        game = Game(board)
        game.outcome = Outcome(winner=Player.WHITE, reason="test")
        sooner = _terminal_score(game, Player.ORANGE, DEFAULT_WEIGHTS, 5)
        later = _terminal_score(game, Player.ORANGE, DEFAULT_WEIGHTS, 1)
        self.assertLess(sooner, later)
        self.assertLessEqual(sooner, -DECISIVE_SCORE)

    def test_a_draw_is_unaffected(self):
        board = place_all({(8, 3): make_captain(Player.ORANGE)})
        game = Game(board)
        game.outcome = Outcome(winner=None, reason="test")
        self.assertEqual(_terminal_score(game, Player.ORANGE, DEFAULT_WEIGHTS, 5), 0.0)

    def test_a_non_decisive_score_is_unaffected(self):
        board = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        static = evaluate(game, Player.ORANGE, DEFAULT_WEIGHTS)
        adjusted = _terminal_score(game, Player.ORANGE, DEFAULT_WEIGHTS, 5)
        self.assertEqual(static, adjusted)


class TranspositionTests(unittest.TestCase):
    def test_the_same_position_produces_the_same_key(self):
        board_a = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        board_b = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        self.assertEqual(_state_key(Game(board_a)), _state_key(Game(board_b)))

    def test_a_different_position_produces_a_different_key(self):
        board_a = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        board_b = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 2)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        self.assertNotEqual(_state_key(Game(board_a)), _state_key(Game(board_b)))


class QuiescenceTests(unittest.TestCase):
    def test_quiescence_sees_a_recapture_a_static_eval_misses(self):
        # Orange can capture a cheap White piece, but doing so lands its
        # own, more valuable piece on a square White can immediately
        # recapture on -- a bad trade a plain depth-limited eval right
        # after the first capture wouldn't see coming.
        mover = Piece(Player.ORANGE, spokes=one_spoke(N, 2))  # cost 2
        target = Piece(Player.WHITE, spokes=one_spoke(N, 1))  # cost 1
        # Spoke index 7 ("NW") for White physically moves (+1, +1) — see
        # board_delta — so this reaches (1, 1) -> (3, 3) diagonally.
        recapturer = Piece(Player.WHITE, spokes=one_spoke(7, UNLIMITED))
        board = place_all(
            {
                (5, 3): mover,
                (3, 3): target,
                (1, 1): recapturer,
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        after_capture = apply_move(game, ((5, 3), (3, 3)), DEFAULT_WEIGHTS)
        self.assertIn((3, 3), after_capture.board.legal_moves((1, 1)))

        static = evaluate(after_capture, Player.ORANGE, DEFAULT_WEIGHTS)
        deadline = time.monotonic() + 5.0
        features = _Features(True, QUIESCENCE_MAX_PLIES, True)
        settled = _quiescence(
            after_capture,
            float("-inf"),
            float("inf"),
            Player.ORANGE,
            DEFAULT_WEIGHTS,
            deadline,
            QUIESCENCE_MAX_PLIES,
            features,
        )
        self.assertLess(settled, static)

    def test_quiescence_returns_the_static_score_when_already_quiet(self):
        board = place_all(
            {
                (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
                (8, 6): make_captain(Player.ORANGE),
                (0, 0): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        static = evaluate(game, Player.ORANGE, DEFAULT_WEIGHTS)
        deadline = time.monotonic() + 5.0
        features = _Features(True, QUIESCENCE_MAX_PLIES, True)
        settled = _quiescence(
            game,
            float("-inf"),
            float("inf"),
            Player.ORANGE,
            DEFAULT_WEIGHTS,
            deadline,
            QUIESCENCE_MAX_PLIES,
            features,
        )
        self.assertEqual(settled, static)

    def test_quiescence_follows_a_check_not_just_a_capture(self):
        # Orange's mover has no capture available, only a non-capturing
        # move that gives check — without also treating checks as
        # forcing, quiescence would stop right here ("no captures left")
        # and miss that the position is actually better for Orange one
        # ply further in (White's Captain is now under direct attack,
        # denting its safety/escape-square features) than the static
        # eval right here suggests.
        W, SE = 6, 3
        mover = Piece(Player.ORANGE, spokes=[0] * SPOKE_COUNT)
        mover.spokes[W] = UNLIMITED
        mover.spokes[SE] = UNLIMITED
        board = place_all(
            {
                (0, 5): mover,
                (5, 1): make_captain(Player.ORANGE),
                (1, 5): make_captain(Player.WHITE),
            }
        )
        game = Game(board)
        check_move = ((0, 5), (0, 4))
        self.assertIsNone(game.board.get(check_move[1]))  # not a capture
        self.assertTrue(_gives_check(game.board, check_move, Player.ORANGE))

        static = evaluate(game, Player.ORANGE, Weights())
        deadline = time.monotonic() + 5.0
        features = _Features(True, QUIESCENCE_MAX_PLIES, True)
        settled = _quiescence(
            game,
            float("-inf"),
            float("inf"),
            Player.ORANGE,
            Weights(),
            deadline,
            QUIESCENCE_MAX_PLIES,
            features,
        )
        self.assertGreater(settled, static)
        after_check = apply_move(game, check_move, Weights())
        self.assertEqual(settled, evaluate(after_check, Player.ORANGE, Weights()))
