"""Tests for movement, check rules, deployment and win conditions."""

import unittest

from spokebound.config import (
    BOARD_ROWS,
    BOUNTIES,
    BUILD_BUDGET,
    CAPTAIN_COLUMN,
    FLEET_SIZE,
    GOAL_SQUARES,
    LEVEL_COSTS,
    MIN_PIECE_COST,
    PIECE_CAP,
    PROMOTION_BONUS,
    SANCTUARY_DEPTH,
    TURN_LIMIT,
    UNLIMITED,
)
from spokebound.model.board import Board, Square
from spokebound.model.deployment import Deployment
from spokebound.model.game import Game, assign_bounties
from spokebound.model.pieces import SPOKE_COUNT, Piece, Player, make_captain
from spokebound.model.presets import PRESETS
from spokebound.model.spending import FleetBuilder, PendingUpgrade

N = 0  # index of the forward spoke
W = 6  # index of the west spoke


def one_spoke(spoke: int, level: int) -> list[int]:
    """Return a spoke-level list of 0s except ``spoke`` set to ``level``."""
    levels = [0] * SPOKE_COUNT
    levels[spoke] = level
    return levels


def place_all(pieces: dict[Square, Piece]) -> Board:
    """Return a Board with each square/piece pair placed directly."""
    board = Board()
    for square, piece in pieces.items():
        board.place(square, piece)
    return board


class MovementTests(unittest.TestCase):
    """Move generation and blocking."""

    def test_orange_forward_is_up_and_white_forward_is_down(self):
        board = place_all({
            (6, 0): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            (0, 0): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
        })
        game = Game(board)
        self.assertEqual(game.board.legal_moves((6, 0)), [(5, 0)])
        self.assertEqual(game.board.legal_moves((0, 0)), [(1, 0)])

    def test_ray_stops_and_captures_at_the_first_piece(self):
        board = place_all({
            (5, 3): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
            (3, 3): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
        })
        game = Game(board)
        self.assertEqual(game.board.legal_moves((5, 3)), [(4, 3), (3, 3)])

    def test_captain_moves_one_square_in_every_direction(self):
        board = place_all({(4, 3): make_captain(Player.ORANGE)})
        game = Game(board)
        moves = set(game.board.legal_moves((4, 3)))
        expected = {(3, 3), (3, 4), (4, 4), (5, 4),
                   (5, 3), (5, 2), (4, 2), (3, 2)}
        self.assertEqual(moves, expected)


class CheckTests(unittest.TestCase):
    """Leaving your own Captain attacked, checkmate and stalemate."""

    def test_a_move_that_leaves_your_own_captain_attacked_is_illegal(self):
        board = place_all({
            (0, 0): make_captain(Player.WHITE),
            (0, 3): Piece(Player.ORANGE, spokes=one_spoke(W, UNLIMITED)),
            (8, 0): make_captain(Player.ORANGE),
        })
        game = Game(board)
        game.current = Player.WHITE
        self.assertTrue(game.in_check(Player.WHITE))
        # (0, 1) is still on the attacked row; only stepping off it works.
        self.assertEqual(set(game.legal_moves((0, 0))), {(1, 0), (1, 1)})

    def test_checkmate_ends_the_game_for_the_mated_player(self):
        board = place_all({
            (0, 0): make_captain(Player.WHITE),
            (0, 3): Piece(Player.ORANGE, spokes=one_spoke(W, UNLIMITED)),
            (2, 0): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            (2, 1): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            (8, 6): make_captain(Player.ORANGE),
        })
        game = Game(board)
        game.current = Player.WHITE
        self.assertEqual(game.legal_moves((0, 0)), [])
        game._start_turn()
        self.assertEqual(game.outcome.winner, Player.ORANGE)
        self.assertIn("checkmated", game.outcome.reason)

    def test_a_stalemated_player_loses_rather_than_draws(self):
        board = place_all({
            (0, 0): make_captain(Player.WHITE),
            (2, 0): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            (2, 1): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            (0, 2): Piece(Player.ORANGE, spokes=one_spoke(W, 1)),
            (8, 6): make_captain(Player.ORANGE),
        })
        game = Game(board)
        game.current = Player.WHITE
        self.assertFalse(game.in_check(Player.WHITE))
        self.assertEqual(game.legal_moves((0, 0)), [])
        game._start_turn()
        self.assertEqual(game.outcome.winner, Player.ORANGE)
        self.assertIn("stalemated", game.outcome.reason)


class SpendingTests(unittest.TestCase):
    """Build budget and upgrade limits."""

    def test_builder_refuses_to_overspend(self):
        builder = FleetBuilder(Player.ORANGE)
        spent = 0
        while builder.adjust(spent % FLEET_SIZE, 0, 1):
            spent += 1
        self.assertGreaterEqual(builder.remaining, 0)
        self.assertLess(builder.remaining, BUILD_BUDGET)

    def test_upgrade_cannot_drop_below_starting_level(self):
        piece = Piece(Player.ORANGE, spokes=[1] * SPOKE_COUNT)
        upgrade = PendingUpgrade(piece, points=3)
        self.assertFalse(upgrade.adjust(N, -1))
        self.assertTrue(upgrade.adjust(N, 1))
        self.assertTrue(upgrade.adjust(N, -1))
        self.assertEqual(upgrade.points, 3)

    def test_every_preset_fits_the_current_build_rules(self):
        for name, fleet in PRESETS.items():
            with self.subTest(preset=name):
                self.assertEqual(len(fleet), FLEET_SIZE)
                total = 0
                for piece in fleet:
                    self.assertEqual(len(piece), SPOKE_COUNT)
                    cost = sum(LEVEL_COSTS[level] for level in piece)
                    self.assertGreaterEqual(cost, MIN_PIECE_COST)
                    self.assertLessEqual(cost, PIECE_CAP)
                    total += cost
                self.assertLessEqual(total, BUILD_BUDGET)

    def test_there_are_nine_presets(self):
        self.assertEqual(len(PRESETS), 9)

    def test_one_preset_has_a_queen(self):
        queen = [UNLIMITED] * SPOKE_COUNT
        self.assertTrue(any(queen in fleet for fleet in PRESETS.values()))

    def test_loading_a_preset_replaces_the_whole_fleet(self):
        builder = FleetBuilder(Player.ORANGE)
        builder.adjust(0, N, 1)  # a manual edit that loading should undo
        preset = next(iter(PRESETS.values()))
        builder.load_preset(preset)
        for piece, levels in zip(builder.pieces, preset, strict=True):
            self.assertEqual(piece.spokes, levels)
        self.assertFalse(builder.problems())

    def test_load_preset_refuses_a_wrong_sized_fleet(self):
        builder = FleetBuilder(Player.ORANGE)
        with self.assertRaises(ValueError):
            builder.load_preset([[1] * SPOKE_COUNT])


class DeploymentTests(unittest.TestCase):
    """Both Captains are fixed and automatic; only the built fleet is
    placed turn by turn."""

    def _fleets(self):
        return ([Piece(Player.ORANGE) for _ in range(FLEET_SIZE)],
                [Piece(Player.WHITE) for _ in range(FLEET_SIZE)])

    def test_both_captains_start_on_the_centre_column_behind_the_lines(self):
        deployment = Deployment(*self._fleets())
        board = deployment.board
        self.assertEqual(board.extra_squares[Player.ORANGE],
                         (BOARD_ROWS, CAPTAIN_COLUMN))
        self.assertEqual(board.extra_squares[Player.WHITE],
                         (-1, CAPTAIN_COLUMN))
        self.assertIs(board.get((BOARD_ROWS, CAPTAIN_COLUMN)),
                     deployment.captains[Player.ORANGE])
        self.assertIs(board.get((-1, CAPTAIN_COLUMN)),
                     deployment.captains[Player.WHITE])

    def test_only_the_built_fleet_is_placed_turn_by_turn(self):
        deployment = Deployment(*self._fleets())
        for row, _ in deployment.legal_squares():
            self.assertGreaterEqual(row, BOARD_ROWS - SANCTUARY_DEPTH)
        order = []
        while not deployment.is_done:
            order.append(deployment.current)
            deployment.place(deployment.legal_squares()[0])
        self.assertEqual(order, [Player.ORANGE, Player.WHITE] * FLEET_SIZE)

        board = deployment.board
        self.assertEqual(len(list(board.pieces(Player.ORANGE))),
                         FLEET_SIZE + 1)  # + the Captain
        self.assertEqual(len(list(board.pieces(Player.WHITE))),
                         FLEET_SIZE + 1)

    def test_cannot_deploy_a_regular_piece_outside_own_sanctuary(self):
        deployment = Deployment(*self._fleets())
        with self.assertRaises(ValueError):
            deployment.place((0, 0))  # White's sanctuary, not Orange's

    def test_roster_is_the_built_fleet_plus_the_captain(self):
        orange_fleet, white_fleet = self._fleets()
        deployment = Deployment(orange_fleet, white_fleet)
        roster = deployment.roster(Player.ORANGE)
        self.assertEqual(roster[:-1], orange_fleet)
        self.assertIs(roster[-1], deployment.captains[Player.ORANGE])


class GameFlowTests(unittest.TestCase):
    """Bounties, far-row promotion, the Captain and turn-limit points."""

    def test_assign_bounties_ranks_by_cost_with_left_tie_break(self):
        cheap_a = Piece(Player.ORANGE, spokes=one_spoke(N, 1))
        cheap_b = Piece(Player.ORANGE, spokes=one_spoke(N, 1))
        costly = Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED))
        assign_bounties([cheap_a, cheap_b, costly])
        self.assertEqual(costly.bounty, BOUNTIES[0])
        self.assertEqual(cheap_a.bounty, BOUNTIES[1])
        self.assertEqual(cheap_b.bounty, BOUNTIES[2])

    def test_capturing_a_bounty_opens_a_turn_ending_upgrade(self):
        mover = Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED))
        target = Piece(Player.WHITE, spokes=one_spoke(N, 1), bounty=3)
        board = place_all({
            (5, 3): mover, (3, 3): target,
            (0, 0): make_captain(Player.WHITE),
            (8, 6): make_captain(Player.ORANGE),
        })
        game = Game(board)
        game.move((5, 3), (3, 3))
        self.assertEqual(game.upgrade.points, 3)
        self.assertEqual(game.current, Player.ORANGE)
        game.finish_turn()
        self.assertEqual(game.current, Player.WHITE)

    def test_reaching_the_far_row_promotes_and_opens_an_upgrade(self):
        mover = Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED))
        board = place_all({
            (1, 3): mover,
            (0, 0): make_captain(Player.WHITE),
            (8, 6): make_captain(Player.ORANGE),
        })
        game = Game(board)
        game.move((1, 3), (0, 3))
        self.assertTrue(mover.promoted)
        self.assertEqual(game.upgrade.points, PROMOTION_BONUS)

    def test_captain_never_promotes_or_opens_an_upgrade(self):
        captain = make_captain(Player.ORANGE)
        board = place_all({
            (1, 3): captain,
            (0, 3): Piece(Player.WHITE, spokes=one_spoke(N, 1), bounty=2),
            (0, 0): make_captain(Player.WHITE),
        })
        game = Game(board)
        game.move((1, 3), (0, 3))
        self.assertFalse(captain.promoted)
        self.assertIsNone(game.upgrade)
        self.assertEqual(game.current, Player.WHITE)  # turn just ended

    def test_marching_the_captain_onto_the_centre_wins_instantly(self):
        goal_row, goal_col = next(iter(GOAL_SQUARES))
        start = (goal_row - 1, goal_col)
        board = place_all({
            start: make_captain(Player.ORANGE),
            (0, 0): make_captain(Player.WHITE),
        })
        game = Game(board)
        game.move(start, (goal_row, goal_col))
        self.assertEqual(game.outcome.winner, Player.ORANGE)
        self.assertIn("centre", game.outcome.reason)

    def test_copy_is_independent_of_the_original(self):
        mover = Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED))
        board = place_all({
            (5, 3): mover,
            (0, 0): make_captain(Player.WHITE),
            (8, 6): make_captain(Player.ORANGE),
        })
        game = Game(board)
        clone = game.copy()
        clone.move((5, 3), (4, 3))
        self.assertIsNone(game.board.get((4, 3)))
        self.assertEqual(game.current, Player.ORANGE)
        self.assertEqual(clone.current, Player.WHITE)

    def test_copy_keeps_the_pending_upgrade_pointed_at_the_cloned_piece(self):
        mover = Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED))
        target = Piece(Player.WHITE, spokes=one_spoke(N, 1), bounty=3)
        board = place_all({
            (5, 3): mover, (3, 3): target,
            (0, 0): make_captain(Player.WHITE),
            (8, 6): make_captain(Player.ORANGE),
        })
        game = Game(board)
        game.move((5, 3), (3, 3))
        clone = game.copy()
        cloned_piece = clone.board.get((3, 3))
        self.assertIs(clone.upgrade.piece, cloned_piece)
        self.assertIsNot(clone.upgrade.piece, game.upgrade.piece)

    def test_all_legal_moves_lists_every_piece_for_the_current_player(self):
        board = place_all({
            (6, 0): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            (6, 6): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            (0, 0): make_captain(Player.WHITE),
            (8, 6): make_captain(Player.ORANGE),
        })
        game = Game(board)
        moves = game.all_legal_moves(Player.ORANGE)
        self.assertCountEqual(
            moves, [((6, 0), (5, 0)), ((6, 6), (5, 6))])

    def test_all_legal_moves_is_empty_for_the_player_not_on_move(self):
        board = place_all({
            (6, 0): Piece(Player.ORANGE, spokes=one_spoke(N, 1)),
            (0, 0): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
            (8, 6): make_captain(Player.ORANGE),
            (1, 0): make_captain(Player.WHITE),
        })
        game = Game(board)
        self.assertEqual(game.all_legal_moves(Player.WHITE), [])

    def test_turn_limit_decides_the_game_on_points(self):
        board = place_all({
            (4, 0): Piece(Player.ORANGE, spokes=one_spoke(N, UNLIMITED)),
            (4, 6): Piece(Player.WHITE, spokes=one_spoke(N, 1)),
            (8, 3): make_captain(Player.ORANGE),
            (0, 3): make_captain(Player.WHITE),
        })
        game = Game(board)
        game.moves_made = {Player.ORANGE: TURN_LIMIT, Player.WHITE: TURN_LIMIT}
        game.finish_turn()
        self.assertTrue(game.is_over)
        self.assertEqual(game.outcome.winner, Player.ORANGE)


if __name__ == "__main__":
    unittest.main()
