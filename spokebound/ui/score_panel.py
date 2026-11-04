"""Side-panel scoreboard: each side's moves used and points on the board,
as a pair of small cards rather than a line of text."""

import tkinter as tk

from spokebound.config import TURN_LIMIT
from spokebound.model.game import Game
from spokebound.model.pieces import Player
from spokebound.ui import theme

BASE_CARD_WIDTH = 226
BASE_CARD_HEIGHT = 112
BASE_BAR_HEIGHT = 8
PADDING = 16
# Gap between one line of a card and the next, measured from the bottom
# of the line above, so the rows stay clear whatever size the font is.
ROW_GAP = 6
# A raised dark card (matching fleet_panel.CARD_FILL) rather than
# theme.SANCTUARY_LIGHT — that palette is the board's own light tint for
# marking sanctuary rows, and reusing it here would leave this card a
# stray light rectangle against the rest of the dark chrome. Each side's
# identity now comes from its own coloured border instead of a tinted
# fill.
CARD_FILL = "#1D3E5C"


class ScorePanel(tk.Frame):
    """Two cards side by side, one per player: moves used (with a
    progress bar against the turn limit) and points left on the board.
    """

    def __init__(
        self,
        parent: tk.Misc,
        game: Game,
        card_width: int = BASE_CARD_WIDTH,
        card_height: int = BASE_CARD_HEIGHT,
    ) -> None:
        super().__init__(parent, bg=theme.PANEL)
        self._game = game
        self._width = card_width
        self._height = card_height
        self._cards: dict[Player, tk.Canvas] = {}
        for index, player in enumerate(Player):
            canvas = tk.Canvas(
                self,
                width=card_width,
                height=card_height,
                bg=CARD_FILL,
                highlightthickness=1,
                highlightbackground=theme.PLAYER_TEXT[player],
            )
            canvas.grid(row=0, column=index, padx=(0, 8) if index == 0 else 0)
            self._cards[player] = canvas
        # Not drawn here: DeployScreen's own _refresh (right after
        # _rebuild) always redraws this immediately afterwards anyway
        # — an eager draw here would only ever be thrown away unseen
        # on fit_height's own throwaway probe builds (which measure
        # this panel's size, then discard it), wasting real time on
        # drawing nothing ever shows.

    def set_game(self, game: Game) -> None:
        """Point this panel at a different Game — used once, the
        moment deployment hands off to actual play, so the same panel
        (built upfront, during deployment, against a placeholder Game
        wrapping that same board purely so this has real move/score
        figures to show from the start) keeps tracking real moves and
        score from then on, rather than being rebuilt."""
        self._game = game

    def redraw(self) -> None:
        """Refresh both cards from the game's current state."""
        game = self._game
        for player, canvas in self._cards.items():
            canvas.delete("all")
            colour = theme.PLAYER_TEXT[player]
            bar_width = self._width - 2 * PADDING
            name = canvas.create_text(
                PADDING, PADDING, anchor="nw", text=player.label, font=theme.FONT_HEADING, fill=colour
            )
            moves = canvas.create_text(
                PADDING,
                _below(canvas, name),
                anchor="nw",
                text=f"{game.moves_made[player]}/{TURN_LIMIT} moves",
                font=theme.FONT_SMALL,
                fill=theme.MUTED_TEXT,
            )
            bar_top = _below(canvas, moves)
            # A recessed track (theme.BACKGROUND, not theme.DISABLED) —
            # DISABLED's teal sits too close in luminance to Orange's
            # copper PLAYER_TEXT fill to tell filled from empty.
            canvas.create_rectangle(
                PADDING,
                bar_top,
                PADDING + bar_width,
                bar_top + BASE_BAR_HEIGHT,
                fill=theme.BACKGROUND,
                outline="",
            )
            fraction = min(1.0, game.moves_made[player] / TURN_LIMIT) if TURN_LIMIT else 0.0
            if fraction > 0:
                canvas.create_rectangle(
                    PADDING,
                    bar_top,
                    PADDING + bar_width * fraction,
                    bar_top + BASE_BAR_HEIGHT,
                    fill=colour,
                    outline="",
                )
            points = canvas.create_text(
                PADDING,
                bar_top + BASE_BAR_HEIGHT + ROW_GAP,
                anchor="nw",
                text=f"{theme.points_text(game.score(player))} on board",
                font=theme.FONT_SMALL,
                fill=theme.TEXT,
            )
            bottom = canvas.bbox(points)[3] + PADDING
            canvas.configure(height=max(self._height, bottom))


def _below(canvas: tk.Canvas, item: int) -> float:
    """Return the y position for a line stacked just under ``item``."""
    return canvas.bbox(item)[3] + ROW_GAP
