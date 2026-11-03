"""Tunable rules for Spokebound.

Every balance number lives here, so playtest tuning never touches game
logic. Board squares are ``(row, col)`` tuples with row 0 at the top of
the screen (White's sanctuary) and row 6 at the bottom (Orange's
sanctuary).
"""

BOARD_ROWS = 7
BOARD_COLS = 7
FLEET_SIZE = 6

# Rows deep, from each player's own edge, that make up their sanctuary:
# where the built fleet (not the Captain) is deployed before play.
SANCTUARY_DEPTH = 2

# The single true centre square: BOARD_ROWS and BOARD_COLS are both odd,
# so this is exact, not just close.
GOAL_SQUARES = frozenset({(BOARD_ROWS // 2, BOARD_COLS // 2)})

BUILD_BUDGET = 48
PIECE_CAP = 32
MIN_PIECE_COST = 1

# Cost of each range level: 0 = none, 1 = one square, 2 = two squares,
# 3 = unlimited distance.
LEVEL_COSTS = (0, 1, 2, 4)
UNLIMITED = len(LEVEL_COSTS) - 1

# The Captain moves one square in every direction and is free: it doesn't
# spend any of the build budget, and its spokes are fixed, never upgraded.
CAPTAIN_REACH = 1

# Column, behind each side's sanctuary, that both Captains start on.
CAPTAIN_COLUMN = BOARD_COLS // 2

# Bounties go to each fleet's most expensive pieces, highest first.
BOUNTIES = (8, 4, 2)
PROMOTION_BONUS = 4

# Moves per player before the game is decided on points.
TURN_LIMIT = 48
