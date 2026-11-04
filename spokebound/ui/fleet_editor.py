"""The piece-thumbnails-plus-spoke-editor widget shared by every screen
that lets someone spend a build budget on a fleet: the real build
screen and the custom-fleet builder alike, so neither duplicates the
thumbnail drawing, selection or budget/validity display."""

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

from spokebound.config import BUILD_BUDGET
from spokebound.model.spending import FleetBuilder
from spokebound.ui import drawing, theme
from spokebound.ui.spoke_editor import SpokeEditor


class FleetEditor(tk.Frame):
    """Wraps one :class:`~spokebound.model.spending.FleetBuilder`: a row
    of piece thumbnails (click to select), the big spoke-editing star
    for whichever piece is selected, a running budget total, and any
    reason the fleet can't be locked in yet.

    Callers only ever touch :attr:`pieces`, :meth:`is_valid`,
    :meth:`load_preset` and :meth:`refresh` — the thumbnail/selection/
    spoke-editing machinery is entirely internal. ``on_change``, if
    given, fires after any edit that could affect validity (a spoke
    change, loading a preset) — never from the initial draw — so an
    owning screen can keep something of its own (a Lock In button's
    enabled state) in sync without reaching into this widget's
    internals.
    """

    def __init__(
        self,
        parent: tk.Misc,
        builder: FleetBuilder,
        thumb_size: int,
        editor_size: int,
        pady: int,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._builder = builder
        self._selected = 0
        self._thumb_size = thumb_size
        self._on_change = on_change

        self._budget = theme.make_label(self, font=theme.FONT_HEADING)
        self._budget.pack()
        count = len(builder.pieces)
        # Room under each thumbnail for its cost, sized from the font's
        # real line height rather than a fixed guess — a DPI-aware
        # window renders FONT_SMALL taller than a fixed allowance holds.
        self._cost_height = tkfont.Font(font=theme.FONT_SMALL).metrics("linespace") + 4
        self._thumbs = tk.Canvas(
            self,
            width=thumb_size * count,
            height=thumb_size + self._cost_height,
            bg=theme.BACKGROUND,
            highlightthickness=0,
        )
        self._thumbs.bind("<Button-1>", self._select_thumb)
        self._thumbs.pack(pady=pady)
        self._editor = SpokeEditor(self, self._adjust, size=editor_size)
        self._editor.pack()
        self._problems = theme.make_label(self, font=theme.FONT_SMALL, fg=theme.ACCENT_DARK)
        self._problems.pack()
        self.refresh()

    @property
    def pieces(self) -> list:
        """The fleet as built so far, in placement order."""
        return self._builder.pieces

    def is_valid(self) -> bool:
        """Return True if every piece meets the minimum to be locked in
        or saved (see :meth:`FleetBuilder.problems`)."""
        return not self._builder.problems()

    def load_preset(self, fleet: list[list[int]]) -> None:
        """Replace the whole fleet with a preset's, still editable
        after."""
        self._builder.load_preset(fleet)
        self.refresh()
        if self._on_change:
            self._on_change()

    def _adjust(self, spoke: int, step: int) -> bool:
        accepted = self._builder.adjust(self._selected, spoke, step)
        if accepted:
            self.refresh()
            if self._on_change:
                self._on_change()
        return accepted

    def _select_thumb(self, event: tk.Event) -> None:
        last = len(self._builder.pieces) - 1
        self._selected = min(event.x // self._thumb_size, last)
        self.refresh()

    def refresh(self) -> None:
        """Bring the budget, thumbnails, editor and problem text up to
        date with the underlying builder — needed after anything
        outside this widget changes it, such as loading a preset."""
        self._budget.config(text=f"{self._builder.remaining} of {BUILD_BUDGET} Points Left")
        self._draw_thumbs()
        self._editor.show(self._builder.pieces[self._selected])
        self._problems.config(text="\n".join(self._builder.problems()))

    def _draw_thumbs(self) -> None:
        """Draw every piece small, with its cost underneath."""
        canvas = self._thumbs
        size = self._thumb_size
        canvas.delete("all")
        for index, piece in enumerate(self._builder.pieces):
            left = index * size
            if index == self._selected:
                canvas.create_rectangle(
                    left + 2, 2, left + size - 2, size - 2, width=2, outline=theme.HIGHLIGHT
                )
            centre = (left + size / 2, size / 2)
            drawing.draw_star(canvas, centre, size * 0.36, piece)
            canvas.create_text(
                centre[0],
                size + 2,
                anchor="n",
                text=str(piece.cost),
                fill=theme.MUTED_TEXT,
                font=theme.FONT_SMALL,
            )
