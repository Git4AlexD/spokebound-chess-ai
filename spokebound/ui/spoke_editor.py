"""A large clickable star for editing a piece's spokes."""

import tkinter as tk
from collections.abc import Callable

from spokebound.model.pieces import Piece
from spokebound.ui import drawing, sound, theme

# Called with (spoke, step); returns True if the change was accepted.
AdjustCallback = Callable[[int, int], bool]


class SpokeEditor(tk.Canvas):
    """Shows one piece large, facing forward (up).

    Click a direction at the ring for the range you want that spoke to
    have; the spoke jumps straight to that level, including back down
    to 0. Each change is passed to ``on_adjust``, which applies the
    rules.
    """

    def __init__(self, parent: tk.Misc, on_adjust: AdjustCallback,
                 size: int = 260, bg: str = theme.BACKGROUND,
                 guide_colour: str = theme.GUIDE) -> None:
        # A dedicated strip above the star for the "Forward" label, scaled
        # with the star rather than pinned a fixed number of pixels above
        # it — a fixed offset pushes the label above the canvas entirely
        # (clipping it) once the star gets small.
        label_area = max(18, round(size * 0.1))
        super().__init__(parent, width=size, height=size + label_area,
                         bg=bg, highlightthickness=0)
        self._on_adjust = on_adjust
        self._piece: Piece | None = None
        self._centre = (size / 2, label_area + size / 2)
        self._radius = size * 0.34
        self._label_y = label_area / 2
        self._guide_colour = guide_colour
        # Any button sets the clicked spoke to the level under the pointer.
        for button in ("<Button-1>", "<Button-2>", "<Button-3>"):
            self.bind(button, self._click)

    def show(self, piece: Piece | None) -> None:
        """Display ``piece`` for editing, or ``None`` for a blank chart."""
        self._piece = piece
        self.redraw()

    def redraw(self) -> None:
        """Redraw the guides and the current piece."""
        self.delete("all")
        drawing.draw_guides(self, self._centre, self._radius,
                            colour=self._guide_colour)
        x, _ = self._centre
        self.create_text(x, self._label_y, text="Forward",
                         fill=self._guide_colour, font=theme.FONT_SMALL)
        if self._piece is not None:
            drawing.draw_star(self, self._centre, self._radius, self._piece)

    def _click(self, event: tk.Event) -> None:
        """Set the spoke nearest the click to the level under it.

        Plays a gentle rejection buzz if the change is refused (not
        enough points, or below the floor for an in-game upgrade). Does
        nothing if the spoke is already at that level.
        """
        if self._piece is None:
            return
        spoke = drawing.spoke_at(self._centre, event.x, event.y)
        level = drawing.level_at(self._centre, self._radius, event.x, event.y)
        step = level - self._piece.spokes[spoke]
        if step == 0:
            return
        if self._on_adjust(spoke, step):
            self.redraw()
            sound.play_unit_click()
        else:
            sound.play_reject()
