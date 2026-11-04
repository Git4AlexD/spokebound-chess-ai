"""The Piece Upgrade terminal: the dark console housing
(terminal_panel.build_shell) wrapped around a fixed-size card showing a
piece's spoke chart. Used by DeployScreen in both of its phases: idle
(no piece, no points) during deployment, then with points actually to
spend on whichever piece is upgrading once play begins — the same
terminal throughout, so the screen looks the same either side of that
handoff."""

import tkinter as tk
from collections.abc import Callable

from spokebound.ui import terminal_panel, theme
from spokebound.ui.spoke_editor import SpokeEditor

# The card itself is the terminal's own CRT glass, not the blue card
# look fleet_panel/score_panel use elsewhere on screen — see
# theme.CRT_SCREEN_BG and friends.
SCREEN_FILL = theme.CRT_SCREEN_BG
SCREEN_OUTLINE = theme.CRT_SCREEN_EDGE

BASE_CARD_PAD = 16
MIN_EDITOR_SIZE = 150


def build(
    parent: tk.Misc,
    scale: float,
    *,
    width: int,
    on_adjust: Callable[[int, int], bool] | None = None,
) -> tuple[tk.Frame, tk.Frame, SpokeEditor, tk.Label, tk.Frame, int]:
    """Return (bezel, card, editor, label, label_holder, card_width).

    Pack ``bezel`` (not ``card``) into ``parent``. ``card`` is the
    fixed card inside the terminal's own screen area — already holding
    a "Piece Upgrade" title, the blank chart, and an always-present (if
    currently empty) label holder — so a caller that wants a Done
    button, or that needs to fix the label holder's height against its
    own worst-case text, packs those into ``card``/``label_holder``
    itself. ``on_adjust`` becomes the editor's own on_change callback;
    pass ``None`` for a terminal that only ever shows a blank chart
    (nothing in it will ever call this), as DeployScreen does.
    """
    card_pad = max(10, round(BASE_CARD_PAD * scale))

    bezel, screen = terminal_panel.build_shell(parent, width)

    # The casing's own stepped bevel and left-hand button/speaker
    # sidebar (see terminal_panel.py) both eat into the width actually
    # left for the screen, on top of the old bezel padding this budget
    # already accounted for.
    card_width = (
        width
        - terminal_panel.CASING_INSET
        - terminal_panel.SIDEBAR_WIDTH
        - terminal_panel.SIDEBAR_GAP
        - 2 * terminal_panel.BEZEL_PADDING
        - 4
    )
    # Filling the full width the card is given at full scale, not some
    # fraction of it chosen up front — the chart is the one thing in
    # this terminal worth spending every spare pixel on. Still scaled
    # by ``scale`` like everything else here (rather than a fixed
    # ceiling), so this still shrinks on a short window the way
    # fit_height (which assumes every build(scale) is monotonically
    # shorter as scale drops) expects — computing it straight from
    # card_width and the *current*, already-scaled card_pad would grow
    # the chart as scale shrinks instead (less padding leaves more
    # room), which fit_height's own linear solve can't handle.
    max_editor_at_full_scale = card_width - 2 * BASE_CARD_PAD
    editor_size = max(MIN_EDITOR_SIZE, round(max_editor_at_full_scale * scale))
    card = tk.Frame(
        screen,
        bg=SCREEN_FILL,
        highlightthickness=1,
        highlightbackground=SCREEN_OUTLINE,
        padx=card_pad,
        pady=card_pad,
        width=card_width,
    )
    # expand=True (no fill) centres the card within the terminal's own
    # screen area, which is taller than the card itself needs.
    card.pack(expand=True)
    theme.make_label(card, "Piece Upgrade", theme.FONT_HEADING, fg=theme.CRT_GREEN, bg=SCREEN_FILL).pack(
        anchor=tk.W
    )

    # Always present (even idle, with nothing in it) so the editor
    # below always starts at the same spot rather than jumping up when
    # there's no prompt to show.
    label_holder = tk.Frame(card, bg=SCREEN_FILL)
    label_holder.pack(anchor=tk.W, fill=tk.X)
    # Wrapped to the card's padded interior, not its outer card_width:
    # the label sits inside card's own padx, and a line wider than that
    # gets squeezed and centred, clipping a character off each edge.
    # The extra few pixels cover card's 1px outline and the label's own
    # internal padding.
    label = theme.make_label(
        label_holder,
        bg=SCREEN_FILL,
        fg=theme.CRT_GREEN,
        justify=tk.LEFT,
        wraplength=card_width - 2 * card_pad - 8,
    )

    # The chart itself: always on screen (even with no piece to show),
    # tinted the same green as the rest of this glass — the piece drawn
    # on it, once there is one, keeps its own full team colour on top,
    # same as everywhere else on the board.
    editor = SpokeEditor(
        card,
        on_adjust or (lambda spoke, step: False),
        size=editor_size,
        bg=SCREEN_FILL,
        guide_colour=theme.CRT_GREEN_DIM,
    )
    editor.pack(pady=(max(3, round(10 * scale)), 0))
    # Not shown here: SpokeEditor draws nothing at all until its first
    # .show() call, and every real call site already makes one of its
    # own right after settling on a kept build — DeployScreen's own
    # _refresh_upgrade once play begins, its _rebuild directly while
    # still idle during deployment — the same way FleetPanel/ScorePanel
    # defer their own first real draw (see their own __init__). Showing
    # it here too would just mean fit_height's own throwaway probe
    # builds (measured, then discarded) draw a chart nothing ever sees.
    return bezel, card, editor, label, label_holder, card_width
