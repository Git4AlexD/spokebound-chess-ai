"""The secret fleet-building screen for one player."""

import tkinter as tk
from collections.abc import Callable

from spokebound.config import LEVEL_COSTS
from spokebound.model import custom_fleets
from spokebound.model.pieces import Piece, Player
from spokebound.model.presets import PRESETS
from spokebound.model.spending import FleetBuilder
from spokebound.net.session import DISCONNECTED, ERROR, NetworkSession
from spokebound.ui import starfield, theme
from spokebound.ui.fleet_editor import FleetEditor
from spokebound.ui.layout import fit_to_window, watch_resize, window_size
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
# Real, visible breathing room between the window's true edge and this
# screen's own content — buttons and columns previously sat flush
# against the edge, since CHROME_MARGIN alone only shrank the space
# fit_to_window solved against, not anything actually keeping content
# away from the edge (a fill=BOTH pack ignores a frame's own requested
# width). Applied as real padding on the outer pack call — see _rebuild.
SIDE_MARGIN_X = 32
SIDE_MARGIN_Y = 20
MAX_SCALE = 2.2
# The preset columns are just named buttons — useful to grow a bit on a
# big window, but nowhere near as much as the editor should (see
# _build_content): capped well under MAX_SCALE.
MAX_PRESET_SCALE = 1.5
# How far the editor (star chart + team-so-far thumbnails) may grow
# past its base size — this is solved against real measured space (see
# _build_content), not guessed, so this is just an outer sanity cap for
# a very large screen, not the thing doing the actual fitting.
MAX_EDITOR_SCALE = 3.0
# A cap on how much of the window's own width the editor may claim,
# leaving the rest for the two single-column side lists — just a
# sanity bound (see _build_content: the editor is still fitted to its
# own real measured needs, down from here, not grown to fill it), so a
# very wide window doesn't offer the editor literally all the space
# there is at the two side lists' expense.
SIDE_WIDTH_FRACTION = 0.3

COST_HELP = (
    "Click a direction at the ring for the range you want, from the "
    "centre (0) out to the edge.\n"
    f"1 square = {LEVEL_COSTS[1]} pt (circle), 2 squares = {LEVEL_COSTS[2]} "
    f"pts (square), unlimited = {LEVEL_COSTS[3]} pts (spiky star)."
)


class BuildScreen(tk.Frame):
    """Lets one player spend the build budget on their fleet."""

    def __init__(
        self,
        parent: tk.Misc,
        player: Player,
        on_done: Callable[[list[Piece]], None],
        on_main_menu: Callable[[], None],
        session: NetworkSession | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._builder = FleetBuilder(player)
        self._on_done = on_done
        self._on_main_menu = on_main_menu
        self._session = session
        self._on_disconnected = on_disconnected
        self._player = player
        self._poll_job: str | None = None

        self._rebuild()
        watch_resize(self, self._rebuild)

        self.bind("<Destroy>", self._on_destroy)
        self._poll()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)

    def _poll(self) -> None:
        if self._session is not None:
            for event in self._session.poll():
                if event.kind in (DISCONNECTED, ERROR):
                    if self._on_disconnected is not None:
                        self._on_disconnected()
                    else:
                        self._on_main_menu()
                    return
            self._poll_job = self.after(100, self._poll)

    def _rebuild(self) -> None:
        """(Re)build this screen's content to fill the window's current
        size — the preset columns pinned toward either edge, growing a
        little; the actual editor and fleet-so-far, in the middle,
        growing to fill whatever real space that leaves (measured, not
        guessed — see _build_content) rather than scaling by the same
        small multiplier as everything else. Everything is packed
        straight into self, not into one enclosing frame spanning the
        whole window — a Tk frame always paints its own full rectangle
        regardless of how little of it its own children actually use,
        so a frame sized to the whole screen would silently blot out
        the starfield (see add_starfield) behind every bit of empty
        space it claims but doesn't fill, rather than only behind the
        real content. SIDE_MARGIN_X/Y keeps everything a real, visible
        distance from the window's own edge, applied here as actual
        padding on each piece rather than one outer frame's — see
        _build_content."""
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
        """Build the whole screen's content, packed straight into self,
        to fit exactly ``available_width`` x ``available_height``."""
        # Fonts/padding still scale with the window, capped like every
        # other screen — just no longer tied to the editor's own size.
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
        theme.make_label(
            self,
            f"{self._player.label}: Build Your Fleet",
            theme.FONT_TITLE,
            fg=theme.PLAYER_TEXT[self._player],
        ).pack(pady=(0, pady))

        # Packed to the bottom before the columns row below, so its real
        # height is already known (not guessed) once it's time to work
        # out how much room the editor has left to grow into.
        bottom = tk.Frame(self, bg=theme.BACKGROUND)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=SIDE_MARGIN_X, pady=(0, SIDE_MARGIN_Y))
        theme.make_label(
            bottom, COST_HELP, theme.FONT_SMALL, fg=theme.MUTED_TEXT, wraplength=available_width
        ).pack(pady=half_pady)
        self._confirm = theme.make_button(bottom, "Lock In Fleet", self._lock_in)
        self._confirm.pack(pady=pady)

        self.update_idletasks()
        editor_height_budget = available_height - self.winfo_reqheight()

        # Packed directly into self rather than into one wrapper frame
        # filling the whole row: side=LEFT with all three expand=True
        # still divides self's own remaining cavity into three equal
        # expanding zones (each pack claims its share of whatever
        # cavity is left when its own turn comes) — so the preset
        # list, the editor and the custom list each sit centred in
        # their own third of the window instead of all three huddling
        # together in the middle — but with no frame of self's own
        # painted over that cavity, the gaps this leaves around and
        # between them show the starfield behind self, not a blank,
        # same-coloured rectangle silently covering it.
        custom = custom_fleets.load_all()
        preset_column = build_preset_column(
            self,
            "Preset Fleets",
            [(name, lambda name=name: self._load_preset(PRESETS[name])) for name in PRESETS],
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
            "Your Custom Fleets",
            [(name, lambda fleet=fleet: self._load_preset(fleet)) for name, fleet in custom.items()],
            preset_width,
            preset_height,
            preset_gap,
            empty_text="No Custom Fleets Built Yet",
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

    def _load_preset(self, fleet: list[list[int]]) -> None:
        self._fleet_editor.load_preset(fleet)

    def _lock_in(self) -> None:
        self._on_done(self._fleet_editor.pieces)

    def _refresh(self) -> None:
        self._confirm.state(["!disabled"] if self._fleet_editor.is_valid() else ["disabled"])
