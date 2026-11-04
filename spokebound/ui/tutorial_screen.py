"""The Instructions screen: a plain-text explanation of every rule,
illustrated with real board and piece renders and screenshots of the
actual game. Not a step-by-step walkthrough, just what a new player
needs to know before their first game.

The page fills the window like every other screen: each section's text
sits beside its picture across the full width, fonts and piece diagrams
grow with the window, and on a window too narrow for both side by side
the picture moves below its text instead.

Every number on this page (budget, costs, bounties, turn limit...) is
read from spokebound.config rather than written into the text, so a
balance change can never leave the rules here out of date.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from spokebound.ai.levels import LEVELS
from spokebound.config import (
    BOARD_COLS,
    BOARD_ROWS,
    BOUNTIES,
    BUILD_BUDGET,
    FLEET_SIZE,
    LEVEL_COSTS,
    MIN_PIECE_COST,
    PIECE_CAP,
    PROMOTION_BONUS,
    SANCTUARY_DEPTH,
    TURN_LIMIT,
    UNLIMITED,
)
from spokebound.model.pieces import Piece, Player, make_captain
from spokebound.resources import package_dir
from spokebound.ui import starfield, theme
from spokebound.ui.layout import watch_resize, window_scale, window_size
from spokebound.ui.settings_gear import add_gear
from spokebound.ui.spoke_editor import SpokeEditor

ASSETS = package_dir() / "assets" / "tutorial"
# Space between the page's content and the window's edges.
MARGIN = 40
COLUMN_GAP = 40
# Width given to a section's picture: the screenshots are saved at most
# this wide, and the piece galleries are laid out to fit within it.
VISUAL_WIDTH = 900
# Narrower than this (at the current scale) and a section's text would
# be squeezed into a thin strip beside its picture, so the picture moves
# below the text instead.
MIN_TEXT_WIDTH = 440
GALLERY_PIECE_SIZE = 150

# (title, spokes, what it does). Chess-equivalent pieces first, then a
# few shapes chess has no equivalent for: the same 8-spoke system
# stretched past the traditional pieces. Each card adds its own cost,
# worked out from its spokes.
CHESS_EQUIVALENTS = [
    ("Pawn", [1, 0, 0, 0, 0, 0, 0, 0],
     "1 square forward only, the cheapest a piece can be."),
    ("Rook", [UNLIMITED, 0, UNLIMITED, 0, UNLIMITED, 0, UNLIMITED, 0],
     "Unlimited range, but only the 4 straight directions."),
    ("Bishop", [0, UNLIMITED, 0, UNLIMITED, 0, UNLIMITED, 0, UNLIMITED],
     "Unlimited range, but only the 4 diagonals."),
    ("Queen", [UNLIMITED] * 8,
     "Unlimited range in every direction."),
]
CUSTOM_PIECES = [
    ("The Lancer", [UNLIMITED, 2, 1, 0, 0, 0, 1, 2],
     "A long forward spear with short cover on its flanks, and nothing "
     "at all behind it."),
    ("The Flanker", [0, UNLIMITED, 0, 0, 0, 0, 0, UNLIMITED],
     "Unlimited range on both forward diagonals, blind everywhere else."),
    ("The Turtle", [1, 1, 1, 1, 1, 1, 1, 1],
     "1 square in every direction, like the Captain, but this one's "
     "built and paid for like any other piece."),
]

TextWriter = Callable[[tk.Frame, int], None]
VisualBuilder = Callable[[tk.Frame, int], None]


def _no_adjust(spoke: int, step: int) -> bool:
    """Refuse every edit: the gallery pieces are shown, not tweaked."""
    return False


def _either(values) -> str:
    """Return ``(8, 4, 2)`` as ``'8, 4 or 2'``."""
    parts = [str(value) for value in values]
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} or {parts[-1]}"


class TutorialScreen(tk.Frame):
    """A scrollable page of rules text, real piece diagrams, and
    screenshots of the actual game, rebuilt to fit whenever the window
    is resized. Nothing on it is interactive except the Main Menu
    button."""

    def __init__(self, parent: tk.Misc,
                 on_main_menu: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._on_main_menu = on_main_menu
        self._images: list[tk.PhotoImage] = []
        self._canvas: tk.Canvas | None = None
        # The page scrolls with the wheel anywhere on it (see _rebuild);
        # that binding is app-wide, so it's removed again the moment this
        # screen goes, rather than following the user onto another one.
        root = self.winfo_toplevel()
        self.bind("<Destroy>", lambda event: event.widget is self
                  and root.unbind_all("<MouseWheel>"))
        self._rebuild()
        watch_resize(self, self._rebuild)

    def _rebuild(self) -> None:
        scroll = self._canvas.yview()[0] if self._canvas is not None else 0.0
        for child in self.winfo_children():
            child.destroy()
        self._images.clear()
        starfield.add_starfield(self)

        scale = window_scale(self)
        self._scale = scale
        self._body = theme.scaled_font(theme.FONT_BODY, scale)
        self._small = theme.scaled_font(theme.FONT_SMALL, scale)
        self._title = theme.scaled_font(theme.FONT_TITLE, scale)
        self._card_title = theme.scaled_font(theme.FONT_HEADING, scale)
        self._piece_size = round(GALLERY_PIECE_SIZE * scale)

        theme.make_button(self, "Main Menu", self._on_main_menu,
                          secondary=True).pack(anchor=tk.NW, padx=16,
                                               pady=16)
        canvas = tk.Canvas(self, bg=theme.BACKGROUND, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._canvas = canvas

        window_width, _ = window_size(self)
        self._width = max(1, window_width - 2 * MARGIN
                          - scrollbar.winfo_reqwidth())
        content = tk.Frame(canvas, bg=theme.BACKGROUND)
        canvas.create_window((MARGIN, 0), window=content, anchor=tk.NW,
                             width=self._width)

        # The scroll region starts at x=0, not wherever the content's own
        # bounding box starts: Tk lines the region's left edge up with
        # the window's, so a region starting at MARGIN would swallow the
        # margin and push the page flush against the window's edge.
        def sync_scrollregion(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=(
                0, 0, window_width, canvas.bbox("all")[3]))

        content.bind("<Configure>", sync_scrollregion)
        self.winfo_toplevel().bind_all(
            "<MouseWheel>",
            lambda event: canvas.yview_scroll(int(-event.delta / 120),
                                              "units"))

        theme.make_label(content, "How to Play",
                         theme.scaled_font(theme.FONT_HERO, scale),
                         fg=theme.ACCENT, bg=theme.BACKGROUND).pack(
            anchor=tk.W, pady=(round(24 * scale), 4))
        self._para(
            content, "Spokebound is a chess-style strategy game for two "
            "players. Each side secretly builds a fleet of eight-direction "
            "pieces "
            "from the same points budget, deploys it, then wins by "
            "marching their Captain onto the board's centre square, or by "
            "checkmating the opponent's Captain.", self._width,
            fg=theme.MUTED_TEXT)

        self._section_modes(content)
        self._section_building(content)
        self._section_board(content)
        self._section_movement(content)
        self._section_capturing(content)
        self._section_upgrade(content)
        self._section_winning(content)
        tk.Frame(content, bg=theme.BACKGROUND,
                 height=round(32 * scale)).pack()

        add_gear(self)
        # Back to where the reader was, rather than the top, after a
        # resize rebuilds everything.
        canvas.update_idletasks()
        sync_scrollregion()
        canvas.yview_moveto(scroll)

    # -- building blocks --------------------------------------------------

    def _section(self, parent: tk.Misc, title: str, write_text: TextWriter,
                 build_visual: VisualBuilder) -> None:
        """A heading, then the section's text beside its picture, or above
        it when the window is too narrow for both side by side.
        ``write_text(frame, wrap)`` adds the text wrapped to ``wrap``
        pixels; ``build_visual(frame, budget)`` adds the picture, no
        wider than ``budget``.

        The picture is built first and its real width measured, rather
        than estimated: text given more room than is actually left gets
        squeezed and centred by Tk, clipping letters off both edges."""
        theme.make_label(parent, title, self._title, fg=theme.ACCENT,
                         bg=theme.BACKGROUND).pack(
            anchor=tk.W,
            pady=(round(36 * self._scale), round(10 * self._scale)))
        row = tk.Frame(parent, bg=theme.BACKGROUND)
        row.pack(fill=tk.X, anchor=tk.W)
        visual = tk.Frame(row, bg=theme.BACKGROUND)
        build_visual(visual, VISUAL_WIDTH)
        visual.update_idletasks()
        text_width = self._width - visual.winfo_reqwidth() - COLUMN_GAP
        text = tk.Frame(row, bg=theme.BACKGROUND)
        if text_width >= MIN_TEXT_WIDTH * self._scale:
            row.columnconfigure(0, weight=1)
            text.grid(row=0, column=0, sticky="nw")
            visual.grid(row=0, column=1, sticky="ne", padx=(COLUMN_GAP, 0))
            write_text(text, text_width)
        else:
            visual.destroy()
            visual = tk.Frame(row, bg=theme.BACKGROUND)
            text.pack(anchor=tk.W, fill=tk.X)
            visual.pack(anchor=tk.W, pady=(round(8 * self._scale), 0))
            write_text(text, self._width)
            build_visual(visual, self._width)

    def _image_section(self, parent: tk.Misc, title: str,
                       write_text: TextWriter, filename: str) -> None:
        image = tk.PhotoImage(file=str(ASSETS / filename))
        self._images.append(image)
        self._section(parent, title, write_text,
                      lambda frame, budget: self._show_image(frame, image,
                                                             budget))

    def _show_image(self, parent: tk.Misc, image: tk.PhotoImage,
                    budget: int) -> None:
        """Show a screenshot, halved (or more) on a window too narrow for
        it at full size. Kept in ``self._images``: Tk drops a PhotoImage
        the moment nothing else references it."""
        if image.width() > budget:
            factor = -(-image.width() // budget)
            image = image.subsample(factor, factor)
            self._images.append(image)
        tk.Label(parent, image=image, bg=theme.BACKGROUND,
                 highlightthickness=1,
                 highlightbackground=theme.DISABLED).pack(anchor=tk.NW)

    def _para(self, parent: tk.Misc, text: str, wrap: int,
              fg: str = theme.TEXT, pady=None) -> None:
        # Wrapped a few pixels short of ``wrap``: a label is a little
        # wider than its wrapped text (its own internal padding), and one
        # wider than its space gets squeezed and clipped.
        theme.make_label(parent, text, self._body, fg=fg,
                         bg=theme.BACKGROUND, justify=tk.LEFT,
                         wraplength=wrap - 8).pack(
            anchor=tk.W, pady=pady or (0, round(10 * self._scale)))

    def _bullets(self, parent: tk.Misc, items: list[str], wrap: int) -> None:
        for item in items:
            self._para(parent, f"•  {item}", wrap,
                       pady=(0, round(8 * self._scale)))

    def _gallery(self, parent: tk.Misc, cards: list[tuple[str, Piece, str]],
                 budget: int) -> None:
        """Lay a set of piece cards out in as many columns as ``budget``
        pixels allow, wrapping onto further rows after that."""
        # Each card is as wide as its note (wrapped to piece + 20, plus
        # the label's own padding), with 12 px of grid padding each side.
        cell = self._piece_size + 24 + 24
        columns = max(1, min(len(cards), budget // cell))
        grid = tk.Frame(parent, bg=theme.BACKGROUND)
        grid.pack(anchor=tk.NW, pady=(0, round(12 * self._scale)))
        for index, (title, piece, note) in enumerate(cards):
            card = tk.Frame(grid, bg=theme.BACKGROUND)
            editor = SpokeEditor(card, _no_adjust, size=self._piece_size,
                                 bg=theme.BACKGROUND)
            editor.show(piece)
            editor.pack()
            theme.make_label(card, title, self._card_title, fg=theme.TEXT,
                             bg=theme.BACKGROUND).pack(pady=(2, 2))
            theme.make_label(card, note, self._small, fg=theme.MUTED_TEXT,
                             bg=theme.BACKGROUND, justify=tk.CENTER,
                             wraplength=self._piece_size + 20).pack()
            card.grid(row=index // columns, column=index % columns,
                      padx=12, pady=8, sticky="n")

    @staticmethod
    def _priced(entries: list[tuple[str, list[int], str]]
                ) -> list[tuple[str, Piece, str]]:
        """Turn (title, spokes, description) entries into gallery cards,
        each description ending in that piece's own cost."""
        cards = []
        for title, spokes, description in entries:
            piece = Piece(Player.ORANGE, spokes=spokes)
            cards.append((title, piece,
                          f"{description} {theme.points_text(piece.cost)}."))
        return cards

    # -- sections -----------------------------------------------------

    def _section_modes(self, parent: tk.Misc) -> None:
        levels = sorted(LEVELS.values(), key=lambda level: level.number)

        def write(frame: tk.Frame, wrap: int) -> None:
            self._bullets(frame, [
                "2-Player Local: two people, one device. Each player "
                "builds their fleet while the other looks away (a handover "
                "screen in between keeps it secret), and during play the "
                "board turns to face whoever is moving.",
                f"Play vs AI: you play Orange against the computer, at "
                f"one of {len(levels)} difficulty levels from "
                f"{levels[0].name} to {levels[-1].name}. Every level runs "
                f"the same engine; the lower ones simply think less "
                f"deeply.",
                "Online Match: choose Invite a Friend, then Host to get a "
                "short room code to share, or Join to type in the code a "
                "friend gives you.",
                "Custom Fleets: design fleets and save them by name. Saved "
                "fleets appear on the right of the build screen in every "
                "later game, beside the built-in presets on the left.",
                "The gear button in the top-right corner of every screen "
                "opens Settings, with separate mute switches for music and "
                "sound effects.",
            ], wrap)

        self._image_section(parent, "Ways to play", write, "menu.png")

    def _section_building(self, parent: tk.Misc) -> None:
        def write(frame: tk.Frame, wrap: int) -> None:
            self._para(
                frame, f"Each side spends a {BUILD_BUDGET}-point budget "
                f"across {FLEET_SIZE} pieces. Every piece needs at least "
                f"{theme.points_text(MIN_PIECE_COST)} spent on it so it "
                f"can move, and no single piece can cost more than "
                f"{PIECE_CAP} points. The Captain is separate: free, fixed, "
                f"and every fleet gets exactly one.", wrap)
            self._para(
                frame, "Click a thumbnail to choose a piece, then on the "
                "large star click a direction at the ring for the range "
                "you want, from the centre (0) out to the edge. “Forward” "
                "is always at the top. Load a preset on the left, or one "
                "of your own saved fleets on the right, as a starting "
                "point and tweak from there. Lock In Fleet unlocks once "
                "every piece is valid.", wrap)

        self._image_section(parent, "Building your fleet", write,
                            "building.png")

    def _section_board(self, parent: tk.Misc) -> None:
        def write(frame: tk.Frame, wrap: int) -> None:
            self._para(
                frame, f"The board is {BOARD_ROWS}×{BOARD_COLS}. The "
                f"{SANCTUARY_DEPTH} rows nearest each side's own edge are "
                f"that side's sanctuary, the only squares its built fleet "
                f"can be deployed onto. The single gold square at the very "
                f"centre is the goal both Captains are racing for. Each "
                f"Captain starts on a fixed square of its own, one row "
                f"behind its side's sanctuary.", wrap)
            self._para(
                frame, f"Once both fleets are locked in they're revealed, "
                f"and each side's {len(BOUNTIES)} most expensive pieces "
                f"automatically carry a bounty of {_either(BOUNTIES)} "
                f"points, shown as a small dark badge on the piece. "
                f"Capturing one pays out (see “Bounties, promotion and the "
                f"Piece Upgrade” below).", wrap)
            self._para(
                frame, "Players then take turns placing one piece at a "
                "time, Orange first. The order your pieces go down in is "
                "fixed: bounty pieces first, highest bounty first, then "
                "the rest in the order you built them. Your only choice is "
                "where, so click any highlighted square in your own "
                "sanctuary. The fleet tracker on the left rings whichever "
                "piece is up next.", wrap)

        self._image_section(parent, "The board and deployment", write,
                            "deployment.png")

    def _section_movement(self, parent: tk.Misc) -> None:
        one, two, unlimited = (LEVEL_COSTS[1], LEVEL_COSTS[2],
                               LEVEL_COSTS[UNLIMITED])
        classic = [("Captain", make_captain(Player.ORANGE),
                    "Free, fixed for the whole game, and never built. "
                    "Every fleet gets exactly one."),
                   *self._priced(CHESS_EQUIVALENTS)]
        custom = self._priced(CUSTOM_PIECES)

        def write(frame: tk.Frame, wrap: int) -> None:
            self._para(
                frame, "Every piece (other than the Captain) is defined by "
                "eight spokes, one for each compass direction, always "
                "drawn from the piece's own point of view: “N” is always "
                "forward, toward the opponent's side, whichever side of "
                "the board that piece's owner is actually on.", wrap)
            self._para(
                frame, f"Each spoke has its own range, set while building "
                f"the fleet: none, 1 square, 2 squares, or unlimited "
                f"distance, costing 0, {one}, {two} and {unlimited} points "
                f"respectively. A piece's tip markers show its ranges at a "
                f"glance: a circle for a 1-square spoke, a square for 2 "
                f"squares, and a spiky star for unlimited. A piece doesn't "
                f"have to use every direction; most spend their points on "
                f"a handful of spokes and leave the rest at 0.", wrap)
            self._para(
                frame, "However far a spoke reaches, movement along it is "
                "a straight line. It stops at the edge of the board, or at "
                "the first piece in the way. An empty square along the way "
                "is a legal move, and the first enemy piece in the way can "
                "be captured by moving onto it, which also ends that "
                "spoke's movement there. A friendly piece in the way "
                "blocks the spoke entirely: it can't be jumped or "
                "captured.", wrap)
            self._para(
                frame, "The Captain is the one exception: it always moves "
                "exactly 1 square in every direction, for free, and that "
                "never changes over the course of the game.", wrap)
            self._para(
                frame, "The example pieces show the range: the Captain, "
                "the four classic chess moves built in this system, then "
                "three shapes chess has no equivalent for.", wrap,
                fg=theme.MUTED_TEXT)

        def build(frame: tk.Frame, budget: int) -> None:
            self._gallery(frame, classic, budget)
            self._gallery(frame, custom, budget)

        self._section(parent, "How pieces move", write, build)

    def _section_capturing(self, parent: tk.Misc) -> None:
        def write(frame: tk.Frame, wrap: int) -> None:
            self._para(
                frame, "Click one of your pieces to mark every square it "
                "can legally move to: a dot on an empty square, or a ring "
                "around an enemy piece it can capture there. Click a "
                "marked square to move.", wrap)
            self._para(
                frame, "The Captain rule works exactly as in chess: a move "
                "that would leave your own Captain under attack is never "
                "offered, so if you're in check (the left panel warns "
                "you), you must play a move that gets out of it. Unlike "
                "chess, though, having no legal move at all, in check or "
                "not, loses the game outright for whoever is stuck. "
                "There's no stalemate-as-a-draw here.", wrap)
            self._para(
                frame, "The fleet tracker on the left keeps both full "
                "fleets on show for the whole game, fading and crossing "
                "out every piece that's been captured, and the score cards "
                "above it count each side's moves used and points still on "
                "the board.", wrap)

        self._image_section(parent, "Moving and capturing", write,
                            "legal_moves.png")

    def _section_upgrade(self, parent: tk.Misc) -> None:
        def write(frame: tk.Frame, wrap: int) -> None:
            self._para(
                frame, f"Capturing an enemy piece that carries a bounty "
                f"badge pays you its value: {_either(BOUNTIES)} points. "
                f"Separately, the first time any of your own pieces (other "
                f"than the Captain) reaches your opponent's back row, it "
                f"promotes and earns a flat {PROMOTION_BONUS}-point bonus, "
                f"once per piece for the rest of the game.", wrap)
            self._para(
                frame, f"Either bonus, or both at once if a single move "
                f"captures a bounty piece while also promoting, goes "
                f"straight onto the piece that just moved. Your turn "
                f"doesn't end yet: that piece's spoke chart opens in the "
                f"Piece Upgrade terminal on the right, where you click "
                f"directions to extend its ranges. You can take back a "
                f"change you made during this upgrade, but never lower a "
                f"spoke below where it started, and no piece can grow past "
                f"{PIECE_CAP} points. Points you don't spend are lost, and "
                f"pressing Done ends your turn. The Captain never upgrades, "
                f"so a bonus it would have earned is simply lost.", wrap)

        self._image_section(parent, "Bounties, promotion and the Piece "
                                    "Upgrade", write, "upgrade.png")

    def _section_winning(self, parent: tk.Misc) -> None:
        def write(frame: tk.Frame, wrap: int) -> None:
            self._para(frame, "A game ends one of four ways:", wrap)
            for line in (
                "1. March your Captain onto the centre square. This wins "
                "instantly, however many pieces either side still has on "
                "the board.",
                "2. Checkmate. Your opponent's Captain is under attack and "
                "they have no legal move that gets it out of check.",
                "3. Stalemate. Your opponent simply has no legal move at "
                "all, even though they aren't in check. As covered above, "
                "that's an immediate loss for them, not a draw.",
                f"4. The turn limit. Each player gets {TURN_LIMIT} moves. "
                f"If neither Captain has reached the centre and neither "
                f"side has been checkmated or stalemated by then, whoever "
                f"has more total points still on the board wins, each "
                f"piece counting for its current value, upgrades included. "
                f"Equal points on both sides is a draw.",
            ):
                self._para(frame, line, wrap,
                           pady=(0, round(8 * self._scale)))

        self._image_section(parent, "Winning the game", write, "win.png")
