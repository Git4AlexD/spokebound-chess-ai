"""The main-menu screen for building and saving custom fleets, so they
later show up as presets — on the right, alongside the built-in ones on
the left — in the real build screen."""

import tkinter as tk
from collections.abc import Callable

from spokebound.config import LEVEL_COSTS
from spokebound.model import custom_fleets
from spokebound.model.pieces import Player
from spokebound.model.presets import PRESETS
from spokebound.model.spending import FleetBuilder
from spokebound.ui import starfield, theme
from spokebound.ui.fleet_editor import FleetEditor
from spokebound.ui.layout import fit_to_window, watch_resize, window_size
from spokebound.ui.name_dialog import NameDialog
from spokebound.ui.preset_column import build_preset_column
from spokebound.ui.settings_gear import add_gear

BASE_THUMB_SIZE = 88
BASE_EDITOR_SIZE = 300
BASE_PADY = 12
BASE_PRESET_WIDTH = 148
BASE_PRESET_HEIGHT = 32
BASE_PRESET_GAP = 4
MIN_THUMB_SIZE = 40
MIN_EDITOR_SIZE = 170
MIN_PRESET_WIDTH = 100
MIN_PRESET_HEIGHT = 22
CHROME_MARGIN = 40
# See the same constants on BuildScreen — real, visible breathing room
# between the window's true edge and this screen's own content, how far
# the preset columns may grow, and how far the editor may (a much
# higher, effectively-sanity-only cap, since that's solved against real
# measured space — see _build_content).
SIDE_MARGIN_X = 32
SIDE_MARGIN_Y = 20
MAX_SCALE = 2.2
MAX_PRESET_SCALE = 1.5
MAX_EDITOR_SCALE = 3.0
# A cap on how much of the window's own width the editor may claim —
# see the same constant on BuildScreen.
SIDE_WIDTH_FRACTION = 0.3

COST_HELP = (
    "Click a direction at the ring for the range you want, from the "
    "centre (0) out to the edge.\n"
    f"1 square = {LEVEL_COSTS[1]} pt (circle), 2 squares = {LEVEL_COSTS[2]} "
    f"pts (square), unlimited = {LEVEL_COSTS[3]} pts (spiky star)."
)

# The Captain isn't built here either, same as the real build screen —
# just the same shape of fleet it eventually needs, so a saved fleet
# always loads straight into FleetBuilder without conversion.
_BUILDER_OWNER = Player.ORANGE


class CustomFleetScreen(tk.Frame):
    """Build a fleet with the same editor the real game uses, then save
    it under a name — nothing here is tied to a live game or a
    particular side, so what's built can be saved, reloaded for more
    editing, or deleted freely."""

    def __init__(self, parent: tk.Misc, on_main_menu: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._on_main_menu = on_main_menu
        self._builder = FleetBuilder(_BUILDER_OWNER)
        self._rebuild()
        watch_resize(self, self._rebuild)

    def _rebuild(self) -> None:
        """(Re)build this screen's content to fill the window's current
        size — see the same note on BuildScreen._rebuild: the preset
        columns are pinned toward either edge, growing a little; the
        editor and fleet-so-far, in the middle, grow to fill whatever
        real width and height that leaves (measured, not guessed).
        Everything is packed straight into self, not into one enclosing
        frame spanning the whole window — see BuildScreen._rebuild for
        why: a frame sized to the whole screen would silently blot out
        the starfield (see add_starfield) behind every bit of empty
        space it claims but doesn't fill. SIDE_MARGIN_X/Y keeps
        everything a real, visible distance from the window's own
        edge, applied here as actual padding on each piece."""
        for child in self.winfo_children():
            child.destroy()
        # Rebuilt fresh every time alongside everything else above,
        # since the destroy loop just above wipes out the one from last
        # time too — add_starfield's own .lower() keeps it behind
        # whatever's about to be built here regardless of order.
        starfield.add_starfield(self)
        window_width, window_height = window_size(self)
        available_width = window_width - CHROME_MARGIN - 2 * SIDE_MARGIN_X
        available_height = window_height - CHROME_MARGIN - 2 * SIDE_MARGIN_Y
        self._build_content(available_width, available_height)
        add_gear(self)

    def _build_content(self, available_width: int, available_height: int) -> None:
        scale = max(1.0, min(MAX_SCALE, available_height / 720))
        pady = max(3, round(BASE_PADY * scale))
        half_pady = max(2, pady // 2)

        preset_scale = min(scale, MAX_PRESET_SCALE)
        preset_width = max(MIN_PRESET_WIDTH, round(BASE_PRESET_WIDTH * preset_scale))
        preset_height = max(MIN_PRESET_HEIGHT, round(BASE_PRESET_HEIGHT * preset_scale))
        preset_gap = max(2, round(BASE_PRESET_GAP * preset_scale))

        theme.make_button(self, "Main Menu", self._on_main_menu, secondary=True).pack(
            anchor=tk.W, padx=SIDE_MARGIN_X, pady=(SIDE_MARGIN_Y + pady, half_pady)
        )
        theme.make_label(self, "Build a Custom Fleet", theme.FONT_TITLE, fg=theme.ACCENT).pack(pady=(0, pady))

        # Packed to the bottom before the columns row below, so its real
        # height is already known (not guessed) once it's time to work
        # out how much room the editor has left to grow into.
        bottom = tk.Frame(self, bg=theme.BACKGROUND)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=SIDE_MARGIN_X, pady=(0, SIDE_MARGIN_Y))
        theme.make_label(
            bottom, COST_HELP, theme.FONT_SMALL, fg=theme.MUTED_TEXT, wraplength=available_width
        ).pack(pady=half_pady)
        self._save_button = theme.make_button(bottom, "Save Fleet", self._save)
        self._save_button.pack(pady=pady)

        self.update_idletasks()
        editor_height_budget = available_height - self.winfo_reqheight()

        # Packed directly into self rather than into one wrapper frame
        # filling the whole row — see BuildScreen._build_content's
        # comment: side=LEFT with all three expand=True still divides
        # self's own remaining cavity into three equal expanding zones,
        # but with no frame of self's own painted over that cavity, the
        # gaps this leaves around and between them show the starfield
        # behind self, not a blank, same-coloured rectangle.
        custom = custom_fleets.load_all()
        preset_column = build_preset_column(
            self,
            "Start From a Preset",
            [(name, lambda name=name: self._load(PRESETS[name])) for name in PRESETS],
            preset_width,
            preset_height,
            preset_gap,
        )
        preset_column.pack(side=tk.LEFT, expand=True, anchor=tk.N, padx=(SIDE_MARGIN_X, 0))

        editor_width_budget = available_width * (1 - 2 * SIDE_WIDTH_FRACTION)
        editor_area = tk.Frame(self, bg=theme.BACKGROUND)
        editor_area.pack(side=tk.LEFT, expand=True, anchor=tk.N)

        custom_column = build_preset_column(
            self,
            "Custom Fleets",
            [(name, lambda fleet=fleet: self._load(fleet)) for name, fleet in custom.items()],
            preset_width,
            preset_height,
            preset_gap,
            empty_text="No Custom Fleets Built Yet",
            on_delete=self._delete,
        )
        custom_column.pack(side=tk.LEFT, expand=True, anchor=tk.N, padx=(0, SIDE_MARGIN_X))

        def build_editor(editor_scale: float) -> tk.Frame:
            frame = tk.Frame(editor_area, bg=theme.BACKGROUND)
            editor_size = max(MIN_EDITOR_SIZE, round(BASE_EDITOR_SIZE * editor_scale))
            thumb_size = max(MIN_THUMB_SIZE, round(BASE_THUMB_SIZE * editor_scale))
            self._fleet_editor = FleetEditor(
                frame, self._builder, thumb_size, editor_size, pady, on_change=self._refresh
            )
            self._fleet_editor.pack()
            return frame

        fit_to_window(
            editor_area,
            build_editor,
            max(MIN_EDITOR_SIZE, editor_width_budget),
            max(MIN_EDITOR_SIZE, editor_height_budget),
            min_scale=MIN_EDITOR_SIZE / BASE_EDITOR_SIZE,
            max_scale=MAX_EDITOR_SCALE,
        )

        self._refresh()

    def _load(self, fleet: list[list[int]]) -> None:
        """Replace the whole fleet with a preset or a saved custom
        fleet's, still editable after."""
        self._fleet_editor.load_preset(fleet)

    def _save(self) -> None:
        """Ask for a name and persist the fleet as built so far."""
        if not self._fleet_editor.is_valid():
            return
        name = NameDialog(self, "Save Fleet", "Name this fleet:").result
        if not name:
            return
        spokes = [list(piece.spokes) for piece in self._fleet_editor.pieces]
        custom_fleets.save(name, spokes)
        self._rebuild()

    def _delete(self, name: str) -> None:
        custom_fleets.delete(name)
        self._rebuild()

    def _refresh(self) -> None:
        self._save_button.state(["!disabled"] if self._fleet_editor.is_valid() else ["disabled"])
