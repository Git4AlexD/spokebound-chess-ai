"""Colours, fonts and widget helpers: dark navy and orange — a
near-black navy field, radar-grid cyan, bronze/copper stars and a
glowing orange accent."""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from spokebound.config import UNLIMITED
from spokebound.model.pieces import Player
from spokebound.ui import sound
from spokebound.ui.fit_text import fit_font_size

# The logo's own near-black navy field, lightened just enough to still
# read as a colour rather than pure black on a screen. TEXT is a warm
# off-white (echoing the wordmark's glow) rather than pure white, for
# a softer full-screen read. All three keep strong WCAG contrast
# against BACKGROUND (14.4:1 / 6.7:1 / 5.6:1 for TEXT / MUTED_TEXT /
# ACCENT respectively).
BACKGROUND = "#0B1D33"
PANEL = "#15304A"
TEXT = "#F1ECDF"
MUTED_TEXT = "#8FA6B5"
# The wordmark's glowing orange, pulled back just far enough that white
# text on top of it still clears ~3:1. ACCENT_DARK is the logo's
# bronze/copper star colour — used both as the pressed/hover shade of
# ACCENT-coloured buttons and as Orange's own player-text colour.
ACCENT = "#DD7A3A"
ACCENT_DARK = "#C2734B"
# A muted teal drawn from the logo's radar-grid lines, standing in for
# the old steel-blue "distinct from both BACKGROUND and PANEL" role.
DISABLED = "#33889D"
# The pressed/hover shade of DISABLED-coloured buttons — one step
# brighter, since lightening (not darkening) is what reads as "lifted"
# against a dark surface.
_ACTIVE_NEUTRAL = "#45A0B6"
# Text/foreground colour for anything sitting on an ACCENT-orange
# surface (the primary button, an enabled mode card). Kept as its own
# token rather than reusing BACKGROUND: orange can't hold BOTH a bold,
# eye-catching page backdrop AND enough contrast to stay legible as
# light text on top of itself — pure white is the most contrast that
# combination can offer (~3:1), so BACKGROUND is free to run bold
# while this stays as light as possible.
ON_ACCENT = "#FFFFFF"

# The board itself now carries the same navy-and-cyan identity as the
# rest of the app: dark squares recede into the chrome, and the light
# squares are the logo's own radar-cyan, so they're what actually
# "pops" — the goal squares' gold and the two sides' own colours are
# what breaks up the grid instead of a wood-toned board sitting apart
# from everything else on screen.
SQUARE_LIGHT = "#8FE8F0"
SQUARE_DARK = "#1A4468"
GOAL_SQUARE = "#D4AF37"
# No single flat colour reads clearly against every square type this
# board now has (dark navy, bright cyan, and gold, all at once) — see
# board_view.draw_selection/draw_move_mark, which draw a wide dark halo
# first and this bright colour on top, so at least one of the two
# always has strong contrast wherever it lands.
HIGHLIGHT = "#FFFFFF"
HIGHLIGHT_SHADOW = "#081420"
# A neutral pale steel — not ACCENT (Orange's own colour) or either
# team's own PIECE_COLOURS, since a legal-move marker means the same
# thing on either side's turn and shouldn't read as belonging to one
# team over the other.
MOVE_MARK = "#C9CFD6"
# One vivid "electric" cyan — the logo's own radar-grid colour — for
# every HUD/informational glyph on a piece: the outer movement-frame
# ring, the eight-direction tactical overlay, and the small
# range-category marker at each spoke tip. These are deliberately never
# team-coloured (a piece's own fill/outline already carries team
# identity) so they read the same regardless of side, and every one of
# them is drawn with HIGHLIGHT_SHADOW as a dark halo behind it — on its
# own this cyan is too close in lightness to both the pale board
# squares and the gold goal squares to read reliably, but the halo
# guarantees a strong edge against literally anything underneath.
GUIDE = "#3FD6DE"
PIECE_RING = "#3FD6DE"
PIECE_DIRECTION_GUIDE = "#3FD6DE"

# Each side's own sanctuary rows, hue-shifted from the board's own navy
# and cyan toward that side's colour (Orange's own warm copper, a cool
# icy blue for White) rather than a plain lighter/darker wash — keeps
# them looking like "territory" rather than just another open square.
SANCTUARY_LIGHT = {
    Player.ORANGE: "#C89879",
    Player.WHITE: "#9EBAC7",
}
SANCTUARY_DARK = {
    Player.ORANGE: "#593822",
    Player.WHITE: "#2C4055",
}

# (fill, outline) for each side's pieces. "White" is Blue Team now (see
# Player.label) — the same vivid electric cyan as the board's HUD
# overlay (PIECE_RING/GUIDE/PIECE_DIRECTION_GUIDE), now as the body
# colour rather than just an accent, shaded by a darker teal outline
# the same way Orange's own outline is a darker shade of its fill.
PIECE_COLOURS = {
    Player.ORANGE: ("#D97757", "#8A3E22"),
    Player.WHITE: ("#3FD6DE", "#0B5A63"),
}
# (fill, outline) for a piece no longer on the board, in the fleet tracker.
LOST_PIECE_COLOURS = ("#E6E4DC", "#ABA89D")
# Colour used for text naming each player — each side's own colour
# family, the same way its pieces are coloured, rather than plain TEXT.
PLAYER_TEXT = {Player.ORANGE: ACCENT_DARK, Player.WHITE: "#3FD6DE"}


def mix_hex(colour_a: str, colour_b: str, t: float = 0.5) -> str:
    """Return ``colour_a`` blended toward ``colour_b`` by ``t`` (0 keeps
    ``colour_a``, 1 is ``colour_b``, 0.5 is their plain RGB midpoint) —
    the general case other modules reach for directly (drawing.py's
    thermal exhaust bands and sun prongs; see also _blend_hex below)."""
    a = tuple(int(colour_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(colour_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(ac + (bc - ac) * t):02X}"
                         for ac, bc in zip(a, b))


def _blend_hex(colour_a: str, colour_b: str) -> str:
    """Return the plain RGB midpoint of two ``#rrggbb`` colours."""
    return mix_hex(colour_a, colour_b, 0.5)


# The Captain's own hexagon marker (always range level 1 — see
# spokebound.model.pieces.make_captain) runs its own accent colour per
# side: Orange's is gold, Blue's is white. Levels 2 and UNLIMITED are
# defined too, for drawing.draw_guides' legend, even though no real
# piece ever reaches them on the Captain specifically.
PIECE_MARKER_COLOURS = {
    Player.ORANGE: {1: "#D4AF37", UNLIMITED: "#A569E0"},
    Player.WHITE: {1: "#FFFFFF", UNLIMITED: "#8CFF5C"},
}
PIECE_MARKER_COLOURS[Player.ORANGE][2] = _blend_hex(
    PIECE_MARKER_COLOURS[Player.ORANGE][1],
    PIECE_MARKER_COLOURS[Player.ORANGE][UNLIMITED])
PIECE_MARKER_COLOURS[Player.WHITE][2] = "#9FCBE0"

# A non-Captain piece's own exhaust (see drawing._heat_gradient) fades
# toward plain white, the same on either side: each spoke's own hull
# colour at the root, desaturating and brightening up to white right at
# the tip of an unlimited-range spoke — one plain fade, not several
# colours chained together (red into white into blue reads as a little
# rainbow running down a long arm). White specifically, rather than
# another hue (red, blue), because it carries no hue of its own to
# blend toward — fading any colour to white only ever turns that same
# colour paler, it never has to pass through some unrelated colour
# partway (the way, say, Blue's own cyan fading toward a warm red would
# have to cross green or purple on the way), and it never makes one
# side start looking like it's adopting the other's own hue: Orange
# stays recognisably orange throughout, Blue stays recognisably cyan,
# right up to the same pale, neutral glow at the very tip. How far
# along the fade a given point sits depends on its own physical
# distance from the hub, the same for every spoke regardless of its own
# level (see drawing._physical_heat) — so a longer spoke's fade only
# ever continues on from a shorter one's, never restarts or compresses
# it.
HEAT_HOT = "#FFFFFF"

# The small cockpit at a non-Captain piece's own centre (see
# drawing._draw_cockpit) is a fixed, neutral grey "glass" — the same on
# both sides and at every range, not a ranking of anything and not
# tied to either side's own hull colour, so it reads as a plain
# cockpit window rather than another status indicator to decode.
COCKPIT_FILL = "#5C6B7A"
COCKPIT_HIGHLIGHT = "#D7E0E8"

# The sun drawn around the board's own centre square (drawing.draw_sun)
# is read in reverse — hot core, cooling outward — and isn't tied to
# any side's own hull colour, so it keeps its own fixed two colours
# rather than running drawing._heat_gradient.
SUN_CORE = "#FFFFFF"
SUN_TIP = "#FFA64D"
SUN_OUTLINE = mix_hex(SUN_TIP, "#000000", 0.55)

# Background starfield (see board_view._make_stars), scattered across
# the whole canvas but in practice only ever showing through the dead
# display cells outside the board and its two Captain squares, since
# every other cell is drawn over with an opaque square. Three
# brightness tiers, the dimmest blended almost into BACKGROUND, so it
# reads as depth rather than noise.
STAR_DIM = "#1E3B5C"
STAR_MID = "#6C8FB3"
STAR_BRIGHT = "#F3F7FF"

# The riveted metal "window" frame drawn around the board itself (see
# window_frame.py) — a dark outer hull shading up to a lighter inner
# bevel that catches the light right at the glass, plus its own rivets.
WINDOW_FRAME_DARK = "#060C14"
WINDOW_FRAME_LIGHT = "#4C83A6"
WINDOW_FRAME_RIVET = "#16283A"
WINDOW_FRAME_RIVET_HIGHLIGHT = "#6FA8C9"

# The sci-fi terminal housing built around the Piece Upgrade card (see
# terminal_panel.py) — a dark console bezel wrapped around the
# existing card rather than replacing its own colours (fleet_panel.
# CARD_FILL already reads as a dark console screen on its own).
TERMINAL_BEZEL = "#11202E"
TERMINAL_BEZEL_EDGE = "#2C4055"
# The outer end of the casing's own bevel (see terminal_panel.py) — a
# lit steel-blue shell colour, darkening band by band down to
# TERMINAL_BEZEL right at the glass, so the screen reads as recessed
# into the console rather than a flat panel with a border round it.
TERMINAL_CASE_OUTER = "#5C6C7C"
# A small row of decorative, non-functional buttons on the terminal's
# own casing — chunky plastic keys, not UI controls, so they get a flat
# fill plus a thin lighter top edge (the same raised-highlight trick
# window_frame.py's rivets use) rather than any hover/press state.
TERMINAL_BUTTON = "#C97A2B"
TERMINAL_BUTTON_EDGE = "#7A4718"
TERMINAL_BUTTON_HIGHLIGHT = "#F2B766"
# The terminal's decorative keyboard: plain grey keys, the same
# raised-highlight treatment as the buttons above, sitting alongside a
# scattered minority of those same orange keys for the reference
# console's own two-tone look.
KEYBOARD_KEY = "#D7DCE2"
KEYBOARD_KEY_EDGE = "#8B929A"
KEYBOARD_KEY_HIGHLIGHT = "#F2F5F8"

# The Piece Upgrade terminal's own "glass": a monochrome green CRT
# readout (the chart/guides and its frame), standing apart from the
# rest of the UI's blue chrome — the piece drawn on it, when there is
# one, keeps its own full team colour regardless, since that's real
# gameplay information rather than part of the screen's own look.
CRT_SCREEN_BG = "#07170D"
CRT_SCREEN_EDGE = "#1C3B24"
CRT_GREEN = "#4CFF8A"
CRT_GREEN_DIM = "#2B7A49"


# A self-contained dark-disc-with-light-text badge (see
# drawing.draw_badge) — its own fill provides the backdrop for its own
# text regardless of what it's drawn over, so both colours are fixed
# rather than tied to the surrounding chrome.
BADGE_FILL = "#141413"
BADGE_TEXT = "#F5F1E8"

# A plain, highly readable face for body copy — paragraphs, blurbs,
# anything meant to be read at length rather than glanced at.
FONT_FAMILY = "Segoe UI"
# A bold, condensed, technical display face for headings, titles and the
# hero banner, never body text, since a condensed face hurts
# readability at paragraph length and small sizes. Agency FB is
# installed with Microsoft Office; where it's missing, Tk substitutes a
# default font and everything still works.
DISPLAY_FONT_FAMILY = "Agency FB"
FONT_HERO = (DISPLAY_FONT_FAMILY, 44, "bold")
FONT_TITLE = (DISPLAY_FONT_FAMILY, 24, "bold")
FONT_HEADING = (DISPLAY_FONT_FAMILY, 17, "bold")
FONT_BODY = (FONT_FAMILY, 12)
FONT_SMALL = (FONT_FAMILY, 10)


def scaled_font(font: tuple, scale: float) -> tuple:
    """Return ``font`` (a ``(family, size, *style)`` tuple) with its
    size scaled by ``scale``, rounded, and never smaller than the
    original — for a screen that grows past its base design to fill a
    big window (see layout.window_scale) rather than sitting small and
    sparse on it, without ever shrinking a font below its normal size."""
    family, size, *rest = font
    return (family, max(size, round(size * scale)), *rest)


def apply_styles(root: tk.Tk) -> None:
    """Configure ttk styles; call once on the root window."""
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Accent.TButton", background=ACCENT,
                    foreground=ON_ACCENT, font=FONT_HEADING,
                    borderwidth=0, focusthickness=0, padding=(18, 8))
    style.map("Accent.TButton",
              background=[("disabled", DISABLED), ("active", ACCENT_DARK)],
              foreground=[("disabled", ON_ACCENT)])
    # A quieter button for secondary actions (presets, choices among many,
    # "Main menu") that shouldn't compete with the one accent-coloured
    # primary action. Its own colour has to read as a button against both
    # BACKGROUND and PANEL, which are too close to each other for a
    # same-as-the-page background to show up as one — DISABLED (an
    # actual teal, not just an off-white) is distinct from both.
    style.configure("Secondary.TButton", background=DISABLED, foreground=TEXT,
                    font=FONT_BODY, borderwidth=1, relief="solid",
                    focusthickness=0, padding=(14, 7))
    style.map("Secondary.TButton",
              background=[("disabled", PANEL), ("active", _ACTIVE_NEUTRAL)],
              foreground=[("disabled", MUTED_TEXT)],
              bordercolor=[("!disabled", MUTED_TEXT)])
    # A smaller chip for picking one of several short-labelled options
    # (preset fleets) side by side in a single row, without each one
    # taking as much room as an ordinary button.
    style.configure("Compact.TButton", background=DISABLED, foreground=TEXT,
                    font=FONT_SMALL, borderwidth=1, relief="solid",
                    focusthickness=0, padding=(8, 4))
    style.map("Compact.TButton",
              background=[("disabled", PANEL), ("active", _ACTIVE_NEUTRAL)],
              foreground=[("disabled", MUTED_TEXT)],
              bordercolor=[("!disabled", MUTED_TEXT)])


def make_label(parent: tk.Misc, text: str = "", font=FONT_BODY,
               fg: str = TEXT, bg: str = BACKGROUND,
               **options) -> tk.Label:
    """Return a themed label (not yet packed)."""
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, **options)


def make_button(parent: tk.Misc, text: str, command: Callable[[], None],
                secondary: bool = False, compact: bool = False) -> ttk.Button:
    """Return a themed button (not yet packed).

    ``secondary`` swaps the bold orange accent style for a quieter one,
    for actions that shouldn't outweigh the screen's one primary button.
    ``compact`` is smaller still, for picking one of several options set
    out side by side (takes precedence over ``secondary``).

    Every button made this way gets the same mechanical-keyboard clack
    on click — one hook here rather than at each of the many call
    sites, so nothing has to remember to wire it in.
    """
    if compact:
        style = "Compact.TButton"
    elif secondary:
        style = "Secondary.TButton"
    else:
        style = "Accent.TButton"

    def on_click() -> None:
        sound.play_button_click()
        command()

    return ttk.Button(parent, text=text, command=on_click, style=style,
                      takefocus=0)


def make_fixed_button(parent: tk.Misc, text: str, command: Callable[[], None],
                      width: int, height: int, compact: bool = True,
                      min_font_size: int = 7) -> tk.Frame:
    """Return a button pinned to an exact ``width`` x ``height`` in
    pixels, not yet packed — a preset name, an on/off label, anything
    whose text can vary or change at runtime without the button (and so
    the layout around it) changing shape. The label's own font shrinks
    to fit instead, down to ``min_font_size``.

    A plain :class:`tk.Button`, not :func:`make_button`'s ttk one: ttk
    styles a widget's font through a *style*, shared by every button
    using it, so it can't be resized per instance the way a change in
    font size here needs — a plain Tk button can. Coloured to match
    ``Compact.TButton``/``Secondary.TButton`` by hand instead. Still
    plays the same click sound as every other button.
    """
    holder = tk.Frame(parent, width=width, height=height, bg=BACKGROUND)
    holder.pack_propagate(False)
    family, base_size = (FONT_SMALL if compact else FONT_BODY)[:2]
    fitted = fit_font_size(holder, text, family, base_size, width - 12,
                          min_font_size)

    def on_click() -> None:
        sound.play_button_click()
        command()

    button = tk.Button(holder, text=text, command=on_click,
                       font=(family, fitted), bg=DISABLED, fg=TEXT,
                       activebackground=_ACTIVE_NEUTRAL, activeforeground=TEXT,
                       relief=tk.SOLID, borderwidth=1,
                       highlightthickness=0, cursor="hand2")
    button.pack(fill=tk.BOTH, expand=True)
    return holder


def points_text(points: int) -> str:
    """Return ``points`` with the right unit, e.g. ``'1 pt'``, ``'4 pts'``."""
    return f"{points} pt" if points == 1 else f"{points} pts"
