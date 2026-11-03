"""Computer opponent: one entry point, :func:`choose_move`, for playing
a turn, plus supporting helpers for the other phases (building a fleet,
deploying it, and spending upgrade points) each screen calls directly.
"""

from spokebound.ai.search import choose_move

__all__ = ["choose_move"]
