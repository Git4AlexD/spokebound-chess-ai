"""The shared match screen: both players place their built fleet, then
play the game straight through on the exact same screen — status and
the fleet tracker on the left, the board centred and framed like a
ship's own viewport, the Piece Upgrade terminal on the right, for a
consistent look whether you're still deploying or already playing.

Deployment and play share this one screen, rather than handing off to
a separate one once deployment ends, and every widget on it — the
board, the fleet tracker, the score cards, the Piece Upgrade terminal —
is built exactly once, during the very first _rebuild, and never
destroyed or rebuilt again just because play has begun. Nothing about
any of them actually needs to be rebuilt at that boundary: the board
only ever needed redrawing (same squares, same pieces, just a possible
flip), the fleet tracker only needed its tracking mode flipped (see
FleetPanel.track_losses/next_index), the score cards only needed
pointing at the real Game instead of a placeholder one wrapping the
same board (see ScorePanel.set_game), and the terminal already shows a
blank chart with no Done button whenever there's nothing to upgrade —
which is exactly deployment's own idle state too. See _begin_game. The
class keeps the name DeployScreen throughout both phases — not just
before this comment was written, but by design — since that's the
identity this screen has during deployment, including to tests that
check for it by name.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox

from spokebound.ai.deploy import choose_deploy_square
from spokebound.ai.levels import LEVELS
from spokebound.ai.search import choose_turn as ai_choose_turn
from spokebound.ai.search import play_ply as ai_play_ply
from spokebound.model.board import Square
from spokebound.model.deployment import Deployment
from spokebound.model.game import Game
from spokebound.model.pieces import Piece, Player
from spokebound.net import protocol
from spokebound.net.session import NetworkSession
from spokebound.ui import sound, theme, upgrade_terminal
from spokebound.ui.board_view import available_board_size
from spokebound.ui.fleet_panel import FleetPanel
from spokebound.ui.layout import fit_height, freeze_height, watch_resize
from spokebound.ui.network_poll import NetworkPoller
from spokebound.ui.score_panel import BASE_CARD_HEIGHT, BASE_CARD_WIDTH, ScorePanel
from spokebound.ui.settings_gear import add_gear
from spokebound.ui.window_frame import create_window_board

# The left (turn/fleets) and right (Piece Upgrade terminal) columns
# either side of the board — shared by both phases, so the board ends
# up the exact same size throughout (the combined side-width budget
# passed to available_board_size never changes), rather than jumping
# size the moment deployment ends.
#
# LEFT_PANEL_WIDTH has to fit each side's full roster — FLEET_SIZE
# built pieces plus the Captain, always FLEET_SIZE + 1 pieces, laid
# out FleetPanel's own way (max 2 rows, so ceil((FLEET_SIZE + 1) / 2)
# columns wide) — at BASE_THUMB_SIZE below, not just whatever was left
# over once everything else was sized; a too-narrow panel here clips
# the last column of thumbnails rather than shrinking them to fit.
LEFT_PANEL_WIDTH = 480
RIGHT_PANEL_WIDTH = 460
# The fleet grid's own baseline piece size at scale 1.0 — bigger than
# fleet_panel.THUMB_SIZE's own default (90), since this screen has the
# room for it and the fit_height/freeze_height machinery around
# _build_left_panel already shrinks scale (and so this) back down on a
# shorter window rather than letting the panel overflow it.
BASE_THUMB_SIZE = 108
PANEL_PADDING = 16
# The left panel's own inset, left edge only — smaller than
# PANEL_PADDING (still used for its right edge, and for the whole of
# the right/terminal panel) so the Main Menu button and everything
# below it (the turn status, the fleet lists) start close to the
# panel's own left edge instead of sitting back of a wide inset that
# reads as more margin than SIDE_MARGIN (see _rebuild) already gives
# the panel as a whole.
LEFT_PANEL_INSET = 8
BASE_PADY = 10
# Clearance reserved above the right column only, so the terminal's
# own top-right corner stops short of add_gear's settings button
# rather than running underneath it — the gear sits at y=16 in its
# own compact button's height, so this leaves a clean gap below it.
RIGHT_PANEL_TOP_CLEARANCE = 50
# fit_height guarantees its own result fits whatever target it's given
# — but the target itself still has to be the real cavity, not
# max_height on its own: this column's pady (RIGHT_PANEL_TOP_CLEARANCE
# above, 10 below) comes out of that same budget as far as pack's own
# cavity for it is concerned, fill=tk.NONE or not. Leaving that out
# meant fit_height correctly hit max_height while still overshooting
# the real (pady-reduced) cavity — starving the one non-expanding
# widget in the column, New Game, down toward nothing once it
# reappeared, squeezed against the terminal's own expanding bezel.
RIGHT_PANEL_HEIGHT_MARGIN = RIGHT_PANEL_TOP_CLEARANCE + 10
# Same reasoning, for the left column's own pady=6 top and bottom —
# without it, that same mismatch between fit_height's target and the
# real (pady-reduced) cavity let the left panel overshoot the window's
# own bottom edge, cutting off Blue Fleet's own last row instead of
# shrinking to keep it on screen. Deliberately tighter than the right
# column's own pady — freeing every spare pixel here goes straight to
# the fleet grid's own real, honest size below, not just a wider
# breathing room against the window's own edge.
LEFT_PANEL_HEIGHT_MARGIN = 6 + 6
# The real, fixed distance from the window's own edge to each side
# panel — the same small margin on both sides, so each one starts as
# far toward its own edge as still reads as a deliberate margin rather
# than the panel being pinned flush to the glass. Whatever's left
# between the two panels, past this margin, all goes to the board's
# own frame (see _rebuild) — the board itself is usually capped by
# this window's *height*, not its width, so that frame is normally
# handed more width than the board alone needs, which is what shows up
# as real starry sky either side of it (see create_window_board)
# rather than being left as flat, unused panel colour outside the
# frame entirely.
SIDE_MARGIN = 24
# Pause before the AI places a piece (deployment) or plays its move
# (actual play), so its turns still read as turns instead of
# snapping down all at once. Hard search can itself take up to a
# couple of seconds on top of its own delay.
AI_PLACE_DELAY_MS = 300
AI_MOVE_DELAY_MS = 400
# How often to check for a message from a network opponent — frequent
# enough that their placement or move shows up practically the moment
# it arrives, without polling so often it's wasted work.
NETWORK_POLL_MS = 100


class DeployScreen(tk.Frame):
    """Lets both players alternate placing their built fleet, then
    runs the game itself once both fleets are down — one continuous
    screen throughout (see the module docstring).

    During deployment: both Captains are already on the board, fixed
    to the centre column behind each side's sanctuary. Orange places
    first, matching who moves first once play begins. Click any
    highlighted square in your own 2 sanctuary rows to place your next
    piece there.

    Once play begins: click one of your pieces to see its moves, then
    click a highlighted square to move. You can't leave your own
    Captain attacked, so a move that doesn't get you out of check
    isn't offered. Bounty captures and reaching the far row fill the
    Piece Upgrade card beside the teams with bonus points to spend on
    the moving piece (unless it's the Captain, which is fixed); click
    **Done** to end your turn.
    """

    def __init__(self, parent: tk.Misc, orange_fleet: list[Piece],
                 white_fleet: list[Piece],
                 on_new_game: Callable[[], None],
                 on_main_menu: Callable[[], None],
                 ai_player: Player | None = None,
                 ai_difficulty: int | None = None,
                 session: NetworkSession | None = None,
                 remote_player: Player | None = None) -> None:
        """``session``/``remote_player`` mirror ``ai_player``: instead
        of scheduling a computer placement/move, the remote side's own
        actions arrive as messages on ``session``, polled for on the
        same kind of timer :meth:`_maybe_ai_place`/:meth:`_maybe_ai_move`
        already use. Mutually exclusive with ``ai_player`` in practice
        — a match is local, vs AI, or networked, never more than one at
        once — but nothing here enforces that; it's just never done.
        ``ai_difficulty`` sets how much this deploys like the
        fully-evolved model (see spokebound.ai.levels.Level.pregame_skill)
        — meaningless, and ignored, without an ``ai_player``.
        ``on_new_game`` is only ever actually called once play ends."""
        super().__init__(parent, bg=theme.PANEL)
        self._deployment = Deployment(orange_fleet, white_fleet)
        # None throughout deployment; set once by _begin_game, the
        # moment the last piece goes down, and never unset again —
        # every phase-dependent method below checks this, not some
        # separate flag, to decide which of the two it's doing.
        self._game: Game | None = None
        self._on_new_game = on_new_game
        self._on_main_menu = on_main_menu
        self._ai_player = ai_player
        self._ai_difficulty = ai_difficulty
        self._ai_pending = False
        self._session = session
        self._remote_player = remote_player
        self._selected: Square | None = None
        # Set once the game's win/loss sound has played, so a rebuild
        # (e.g. a window resize after the game's already over) doesn't
        # replay it.
        self._outcome_announced = False
        self._poller = (NetworkPoller(self, session, NETWORK_POLL_MS,
                                      self._handle_network_message,
                                      self._on_disconnected)
                        if session is not None else None)
        self._rebuild()
        # Keeps this screen fitted to the window as it's resized —
        # un-maximizing, dragging an edge — rather than only at the
        # moment it was first shown.
        watch_resize(self, self._rebuild)
        if self._poller is not None:
            self.bind("<Destroy>", self._on_destroy)
            # Deferred rather than called straight from __init__ — a
            # queued message here can be a placement or move that
            # arrives before this constructor has even returned, which
            # would otherwise be applied to a screen that isn't fully
            # set up yet.
            self._poller.start(delay_ms=0)

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        self._poller.cancel()

    def _on_disconnected(self) -> None:
        messagebox.showwarning("Connection Lost",
                               "Your opponent disconnected.", parent=self)
        self._on_main_menu()

    def _rebuild(self) -> None:
        """(Re)build the whole three-column screen — status/fleets, the
        framed board, the upgrade terminal — to fill the window's
        current size, then bring it all up to date. Only ever called
        for the very first build and after an actual window resize —
        deployment handing off to actual play (see _begin_game) never
        calls this at all, since nothing it would rebuild has actually
        changed shape."""
        for child in self.winfo_children():
            child.destroy()
        # No starfield background on this screen at all — self's own
        # bg (theme.PANEL, same as the side panels — see __init__) is
        # the whole ship's interior; the only actual starry sky shown
        # anywhere here is inside the board's own viewport
        # (create_window_board draws that into whatever slack the
        # board's own, usually height-bound, size leaves inside the
        # frame — see below).
        _, max_height = available_board_size(
            self, LEFT_PANEL_WIDTH + RIGHT_PANEL_WIDTH)

        # Each side column is fit to the board's own height budget
        # independently (its content can outgrow the board's height on
        # a short window, so it's fit rather than left to overflow),
        # not sized against each other.
        left_panel = fit_height(self, self._build_left_panel,
                                max_height - LEFT_PANEL_HEIGHT_MARGIN)
        right_panel = fit_height(self, self._build_right_panel,
                                 max_height - RIGHT_PANEL_HEIGHT_MARGIN)
        # Frozen only now, on the one, final, kept build of each — never
        # inside _build_left_panel/_build_right_panel themselves, which
        # fit_height also calls on throwaway probe builds purely to
        # measure their *honest*, content-driven height; freezing one of
        # those would mean every measurement after it reads back the
        # frozen value instead, not the real one, which is exactly what
        # silently broke this the first time (see freeze_height's own
        # docstring). self._editor's own parent is the card itself.
        freeze_height(left_panel)
        freeze_height(self._editor.master)
        # fit_height's own internal pack call is each one's *first* ever
        # pack into self, which is what fixes its slot in self's own
        # packing order — re-packing it further down with new options
        # only ever updates those options in place, it doesn't move the
        # slot. Forgetting both here, before the board is packed at all,
        # means the three real pack calls below are each one's first
        # real slot, in the order those calls actually happen in —
        # left panel, then the board, then the right one — rather than
        # both panels staying stuck in front of a board that didn't
        # exist yet the first time either of them was packed.
        left_panel.pack_forget()
        right_panel.pack_forget()

        # The board's frame claims whatever's actually left once both
        # real, measured panels and SIDE_MARGIN on each outer edge are
        # set aside — not a fixed width budget (LEFT_PANEL_WIDTH +
        # RIGHT_PANEL_WIDTH only ever used above for the panels' own
        # height fit). The board itself is normally capped by this
        # window's *height*, not its width, so this frame is usually
        # handed more width than the board alone needs — see
        # create_window_board, which centres the board within that and
        # fills the rest with real starry sky, rather than shrinking
        # the frame to hug the board and leaving the spare width as
        # flat, unused panel colour outside it.
        root = self.winfo_toplevel()
        root.update_idletasks()
        window_width = root.winfo_width()
        left_w = left_panel.winfo_reqwidth()
        right_w = right_panel.winfo_reqwidth()
        board_max_width = max(1, round(
            window_width - left_w - right_w - 2 * SIDE_MARGIN))

        board = self._game.board if self._game is not None else self._deployment.board
        self._frame_canvas, self._board_view = create_window_board(
            self, board, self._on_square, board_max_width, max_height,
            flipped=self._board_flipped())

        left_panel.pack(side=tk.LEFT, anchor=tk.N, pady=6,
                        padx=(SIDE_MARGIN, 0),
                        fill=tk.NONE, expand=False)
        self._frame_canvas.pack(side=tk.LEFT, pady=10)
        # anchor=tk.CENTER, fill/expand explicitly cancelled: the
        # terminal sits at its own natural content height (casing
        # hugging the card, buttons and keyboard snugly) instead of
        # being stretched to match the board's own height, and that
        # natural-height block then centres vertically in the space
        # below the gear (reserved by RIGHT_PANEL_TOP_CLEARANCE's own
        # pady floor) rather than sitting pinned to the top of it.
        right_panel.pack(
            side=tk.LEFT, anchor=tk.CENTER,
            padx=(0, SIDE_MARGIN),
            pady=(RIGHT_PANEL_TOP_CLEARANCE, 10),
            fill=tk.NONE, expand=False)

        add_gear(self)
        self._refresh()

    def _build_left_panel(self, scale: float) -> tk.Frame:
        """Build the turn/status display, the score cards, and both
        fleets at ``scale`` — built the same way regardless of phase
        (see the module docstring); only ``_refresh`` and
        ``_begin_game`` ever change what they show."""
        pad = max(8, round(PANEL_PADDING * scale))
        pad_x = max(4, round(LEFT_PANEL_INSET * scale))
        gap = self._gap = max(3, round(BASE_PADY * scale))
        thumb_size = max(24, round(BASE_THUMB_SIZE * scale))
        full_width = LEFT_PANEL_WIDTH - 2 * pad_x

        # No pack_propagate(False) here: fit_height calls this same
        # method several times, at different scales, purely to measure
        # each one's honest, content-driven height before picking a
        # final one — freezing it in here (rather than in _rebuild,
        # once, on whichever build fit_height actually keeps) would
        # mean every one of those measurements reads back whatever got
        # frozen into some earlier, discarded probe instead of this
        # build's own real height, which is exactly how this broke the
        # first time (see freeze_height's own docstring).
        # padx uses the panel's own, tighter inset — only pady keeps
        # PANEL_PADDING's wider spacing, since starting close to the
        # left edge is the actual ask here, not also squeezing the
        # vertical gap above the Main Menu button.
        panel = tk.Frame(self, bg=theme.PANEL, width=LEFT_PANEL_WIDTH,
                         padx=pad_x, pady=pad)
        theme.make_button(panel, "Main Menu", self._on_main_menu,
                          secondary=True).pack(anchor=tk.W, pady=(0, gap))

        # wraplength on both: game-mode's own status text ("Orange's
        # Turn", a check warning) never wraps, but deployment's own
        # ("Orange: Place Piece 16 of 16") can genuinely run onto a
        # second line at this width — which is exactly why both need
        # measuring against that worst case below, not left to wrap
        # for the first time only once _refresh sets the real text,
        # after fit_height/freeze_height have already measured and
        # locked this panel's height against whatever was here before.
        self._turn = theme.make_label(panel, font=theme.FONT_TITLE,
                                      bg=theme.PANEL, wraplength=full_width)
        self._turn.pack(anchor=tk.W)
        self._check_label = theme.make_label(panel, bg=theme.PANEL,
                                             fg=theme.ACCENT_DARK,
                                             wraplength=full_width)
        self._check_label.pack(anchor=tk.W, pady=(0, gap))
        # The longest status text either phase ever shows: deployment's
        # own counter at its own longest (whichever side's label is
        # longer, placing its very last piece) genuinely wraps to two
        # lines here, unlike anything game-mode ever shows ("Orange's
        # Turn", a result, a check warning are all one line) — so this
        # is the real worst case fit_height/freeze_height need to see,
        # not empty text (all either one has at this point, otherwise —
        # _refresh sets the real text immediately after this whole
        # screen finishes building, before anything is ever shown).
        worst_player = max(Player, key=lambda p: len(p.label))
        worst_count = self._deployment.fleet_size(worst_player)
        self._turn.config(
            text=f"{worst_player.label}: Place Piece {worst_count} of "
                 f"{worst_count}")
        self._check_label.config(text=f"{worst_player.label} Is in Check!")

        # Built from the very first deploy-phase rebuild on, against a
        # placeholder Game that wraps this same (shared, never-copied)
        # board purely so there's a real move count and on-board score
        # to show from the start — _begin_game points it at the real
        # Game once there is one, rather than this card ever being
        # built fresh.
        card_width = max(150, round(BASE_CARD_WIDTH * scale))
        card_height = max(70, round(BASE_CARD_HEIGHT * scale))
        score_game = (self._game if self._game is not None
                     else Game(self._deployment.board))
        self._score_panel = ScorePanel(panel, score_game,
                                       card_width=card_width,
                                       card_height=card_height)
        self._score_panel.pack(anchor=tk.W, pady=(0, gap))
        # Drawn once, right here, rather than left for _refresh to draw
        # for the first time afterwards: ScorePanel's own redraw() can
        # grow its canvas taller than card_height to fit its own text
        # (see its own module), and fit_height/freeze_height need to
        # see that real, final height — not the blank canvas's smaller
        # one — to size and lock this whole panel correctly around it.
        self._score_panel.redraw()

        rosters = {p: self._deployment.roster(p) for p in Player}
        board = self._game.board if self._game is not None else self._deployment.board
        # track_losses/next_index start in whichever state matches the
        # current phase (relevant on a resize mid-game, which rebuilds
        # this from scratch) — _begin_game flips both, on this same
        # instance, the moment play actually begins.
        next_index = (None if self._game is not None else
                     {p: self._deployment.placed_count(p) for p in Player})
        self._fleet_panel = FleetPanel(panel, rosters, board,
                                      track_losses=self._game is not None,
                                      thumb_size=thumb_size,
                                      next_index=next_index)
        self._fleet_panel.pack(anchor=tk.W, fill=tk.X)
        return panel

    def _build_right_panel(self, scale: float) -> tk.Frame:
        """Build the Piece Upgrade terminal at ``scale`` — the same
        terminal throughout, idle (no piece, no spend prompt) whenever
        there's nothing pending to upgrade, which is deployment's own
        permanent state as much as it's play's between turns; New Game
        and Done are built once too, simply hidden until the moment
        either is actually relevant (see _refresh)."""
        pad = max(8, round(PANEL_PADDING * scale))
        gap = self._gap = max(3, round(BASE_PADY * scale))

        # No pack_propagate(False) here either, same reasoning as
        # _build_left_panel — fit_height needs this frame's real,
        # content-driven height to measure it honestly.
        outer = tk.Frame(self, bg=theme.PANEL, width=RIGHT_PANEL_WIDTH,
                         padx=pad, pady=pad)

        # Packed (then, below, measured) at the bottom first, so
        # fit_height's own scale accounts for its worst-case height —
        # visible or not, it's part of the same card either way, not
        # something a rebuild adds later.
        self._new_game = theme.make_button(outer, "New Game",
                                           self._on_new_game)
        self._new_game.pack(side=tk.BOTTOM, anchor=tk.W, pady=(gap, 0))

        # The card stays on screen permanently (not just while a piece
        # is being upgraded), with its own heading, so it reads as a
        # fixture of the terminal rather than something that pops in
        # and out.
        bezel, card, self._editor, self._upgrade_label, \
            self._upgrade_label_holder, card_width = upgrade_terminal.build(
                outer, scale, width=RIGHT_PANEL_WIDTH - 2 * pad,
                on_adjust=self._adjust_upgrade)
        bezel.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._upgrade_done = theme.make_button(card, "Done",
                                               self._finish_upgrade)
        # Measured against the worst case — the spend prompt and Done
        # both showing — so fixing the prompt holder's own height to
        # match doesn't itself need a second, idle-state build.
        self._upgrade_label.config(
            text="Spend 88 pts of bonus on this piece. Unspent points "
                 "are lost.")
        self._upgrade_label.pack(anchor=tk.W)
        card.update_idletasks()
        label_h = self._upgrade_label.winfo_reqheight()
        self._upgrade_label.config(text="")
        # Both dimensions explicitly fixed, not just height: once
        # pack_propagate is off below, this frame's own reported width
        # to the card stops coming from the label inside it at all —
        # leave width unset here and the card itself can shrink below
        # card_width to whatever its other children (the title, the
        # editor) actually need, which then leaves the label too
        # little room for the wraplength its text was actually measured
        # against, clipping it.
        self._upgrade_label_holder.configure(height=label_h,
                                             width=card_width)
        self._upgrade_label_holder.pack_propagate(False)
        self._upgrade_done.pack(pady=(gap, 0), fill=tk.X)
        # The card's own height gets frozen too — but only once,
        # in _rebuild, on whichever one of these builds fit_height
        # actually keeps (same reasoning as panel in
        # _build_left_panel: freezing it in here would corrupt every
        # one of fit_height's own measurements of *this* build with
        # whatever got baked in on a previous, possibly-discarded one).
        # This method still packs Done unconditionally above so that
        # whichever build does get kept already reflects the worst
        # case — spend prompt showing, Done showing — when that
        # freeze happens.
        return outer

    def _on_square(self, square: Square) -> None:
        """Place a piece during deployment, or select/move one once
        play has begun — whichever ``self._game`` says this is."""
        if self._game is not None:
            self._on_game_square(square)
        else:
            self._on_deploy_square(square)

    def _on_deploy_square(self, square: Square) -> None:
        """Deploy the current player's next piece to ``square`` if legal."""
        if self._deployment.current in (self._ai_player, self._remote_player):
            return
        if square not in self._deployment.legal_squares():
            sound.play_reject()
            return
        self._place(square, broadcast=True)

    def _place(self, square: Square, broadcast: bool = False) -> None:
        """Deploy the current player's next piece to ``square``.
        ``broadcast`` sends it to a network opponent — only true for a
        placement that just happened locally; one already received over
        the network is applied the same way but never echoed back."""
        self._deployment.place(square)
        sound.play_button_click()
        if broadcast and self._session is not None:
            self._session.send(protocol.place(square))
        if self._deployment.is_done:
            self._begin_game()
            return
        self._refresh()

    def _begin_game(self) -> None:
        """Hand off from deployment to actual play, in place — every
        widget on screen (see the module docstring) already exists and
        stays exactly where it is; this only swaps the data they show.
        Orange always moves first, matching who deploys first."""
        self._game = Game(self._deployment.board)
        self._score_panel.set_game(self._game)
        self._fleet_panel.track_losses = True
        self._fleet_panel.next_index = None
        self._refresh()

    def _on_game_square(self, square: Square) -> None:
        """Select a piece, or move the selected piece to ``square``."""
        game = self._game
        if game.is_over or game.upgrade:
            return
        if game.current is self._remote_player:
            return
        if self._selected and square in game.legal_moves(self._selected):
            self._play_move_sound(square)
            src = self._selected
            game.move(src, square)
            self._selected = None
            if self._session is not None:
                self._session.send(protocol.move(src, square))
        else:
            piece = game.board.get(square)
            owns = piece is not None and piece.owner is game.current
            self._selected = square if owns else None
        self._refresh()

    def _apply_remote_move(self, src: Square, dst: Square) -> None:
        """Apply a move a network opponent just made."""
        self._play_move_sound(dst)
        self._game.move(src, dst)
        self._selected = None
        self._refresh()

    def _play_move_sound(self, dst: Square) -> None:
        """Play the right sound for a move about to land on ``dst``.

        Has to be called before the move is actually applied: once
        :meth:`~spokebound.model.game.Game.move` runs, any piece that
        was captured there is already gone from the board.
        """
        if self._game.board.get(dst) is not None:
            sound.play_capture()
        else:
            sound.play_move()

    def _adjust_upgrade(self, spoke: int, step: int) -> bool:
        """Spend or refund bonus points on the upgrading piece. Only
        ever actually invoked while a real piece is shown on the chart
        (see SpokeEditor._click), which is only ever true once there's
        a real upgrade pending — i.e. never during deployment, even
        though this is wired up from the very first build."""
        if self._game.current is self._remote_player:
            return False
        accepted = self._game.upgrade.adjust(spoke, step)
        if accepted:
            if self._session is not None:
                self._session.send(protocol.upgrade_adjust(spoke, step))
            self._refresh()
        return accepted

    def _finish_upgrade(self) -> None:
        """Close the upgrade and end the turn."""
        if self._game.current is self._remote_player:
            return
        if self._session is not None:
            self._session.send(protocol.upgrade_finish())
        self._game.finish_turn()
        self._refresh()

    def _apply_remote_upgrade_adjust(self, spoke: int, step: int) -> None:
        """Apply a network opponent's own upgrade spend."""
        self._game.upgrade.adjust(spoke, step)
        self._refresh()

    def _apply_remote_upgrade_finish(self) -> None:
        """Apply a network opponent finishing their upgrade and turn."""
        self._game.finish_turn()
        self._refresh()

    def _handle_network_message(self, data: dict) -> None:
        """Apply a placement, move, or upgrade a network opponent just
        made — whichever ``self._game`` says this match currently is."""
        if self._game is None:
            self._place(protocol.place_from(data))
            return
        kind = data.get("type")
        if kind == protocol.MOVE:
            src, dst = protocol.move_from(data)
            self._apply_remote_move(src, dst)
        elif kind == protocol.UPGRADE_ADJUST:
            spoke, step = protocol.upgrade_adjust_from(data)
            self._apply_remote_upgrade_adjust(spoke, step)
        elif kind == protocol.UPGRADE_FINISH:
            self._apply_remote_upgrade_finish()

    def _board_flipped(self) -> bool:
        """Return True if the board is drawn mirrored, with Blue at the
        bottom. Online, the joiner always sees their own side at the
        bottom — fixed for the whole match. Local two-player deployment
        turns the board to face whoever is placing (and, once play
        begins, whoever is moving), and an AI match keeps the fixed
        Orange-at-bottom view throughout either way."""
        if self._remote_player is not None:
            return self._remote_player is Player.ORANGE
        if self._ai_player is None:
            current = (self._game.current if self._game is not None
                      else self._deployment.current)
            return current is Player.WHITE
        return False

    def _refresh(self) -> None:
        """Bring every part of the screen up to date — whichever of
        deployment or actual play ``self._game`` says this currently
        is. New Game and the score cards are common to both: New Game
        only ever actually shows once a finished game says so, and the
        score cards track the real board's own state either way (a
        placeholder Game during deployment, see _build_left_panel)."""
        if self._game is not None and self._game.is_over:
            self._new_game.pack(side=tk.BOTTOM, anchor=tk.W,
                               pady=(self._gap, 0))
        else:
            self._new_game.pack_forget()

        if self._game is None:
            self._board_view.set_flipped(self._board_flipped())
            self._board_view.redraw(targets=self._deployment.legal_squares())
            self._fleet_panel.next_index = {
                p: self._deployment.placed_count(p) for p in Player}
            self._fleet_panel.redraw()
            player = self._deployment.current
            placed = self._deployment.placed_count(player)
            total = self._deployment.fleet_size(player)
            self._turn.config(
                text=f"{player.label}: Place Piece {placed + 1} of {total}",
                fg=theme.PLAYER_TEXT[player])
            # There's no check concept during deployment — only
            # _build_left_panel's own worst-case placeholder text ever
            # sets this label otherwise, to measure the panel's real
            # height before anything's shown; this is what actually
            # clears it again once deployment is genuinely on screen.
            self._check_label.config(text="")
            self._maybe_ai_place()
        else:
            targets = (self._game.legal_moves(self._selected)
                      if self._selected else [])
            self._board_view.set_flipped(self._board_flipped())
            self._board_view.redraw(self._selected, targets)
            self._fleet_panel.redraw()
            self._refresh_status()
            self._maybe_ai_move()
        # Common to both phases: the chart has nothing to show during
        # deployment (there's no upgrade concept yet) in exactly the
        # same way it has nothing to show between turns once play
        # begins — one idle state, not two.
        self._refresh_upgrade()
        self._score_panel.redraw()

    def _maybe_ai_place(self) -> None:
        """Schedule the AI's next placement, if it's the AI's turn and
        one isn't already pending — guarded so a window-resize rebuild
        mid-delay can't end up scheduling a second one on top of it."""
        if self._ai_pending or self._deployment.current is not self._ai_player:
            return
        self._ai_pending = True
        self.after(AI_PLACE_DELAY_MS, self._ai_place)

    def _ai_place(self) -> None:
        """Place the AI's next piece, chosen by
        :func:`spokebound.ai.deploy.choose_deploy_square`."""
        self._ai_pending = False
        if self._deployment.current is not self._ai_player:
            return
        level = LEVELS.get(self._ai_difficulty)
        skill = level.pregame_skill if level is not None else 1.0
        square = choose_deploy_square(self._deployment, self._ai_player,
                                      skill=skill)
        self._place(square)

    def _maybe_ai_move(self) -> None:
        """Schedule the AI's next move, if it's the AI's turn and one
        isn't already pending — guarded so a window-resize rebuild
        mid-delay can't end up scheduling a second one on top of it."""
        game = self._game
        if self._ai_pending or game.is_over or game.current is not self._ai_player:
            return
        self._ai_pending = True
        self.after(AI_MOVE_DELAY_MS, self._ai_move)

    def _ai_move(self) -> None:
        """Play the AI's move, chosen by
        :func:`spokebound.ai.search.choose_move`. The higher levels can
        themselves take a couple of seconds to search, which blocks the
        window while they think — acceptable for a move the AI only
        makes once per turn."""
        self._ai_pending = False
        game = self._game
        if game.is_over or game.current is not self._ai_player:
            return
        ply = ai_choose_turn(game, self._ai_difficulty)
        self._play_move_sound(ply[1])
        ai_play_ply(game, ply)
        self._selected = None
        self._refresh()

    def _refresh_status(self) -> None:
        """Show whose turn it is (or the result) and any check warning
        — New Game's own visibility is handled once, up in _refresh,
        not here."""
        game = self._game
        check_text = ""
        if game.outcome is not None:
            winner = game.outcome.winner
            title = f"{winner.label} Wins!" if winner is not None else "Draw"
            colour = (theme.PLAYER_TEXT[winner] if winner is not None
                      else theme.TEXT)
            if not self._outcome_announced:
                self._outcome_announced = True
                # Framed around the human side of an AI game; a local
                # 2-player match has no fixed "you", so any win gets the
                # same little fanfare and a draw stays quiet either way.
                if winner is not None:
                    if winner is self._ai_player:
                        sound.play_loss()
                    else:
                        sound.play_win()
        else:
            title = f"{game.current.label}'s Turn"
            colour = theme.PLAYER_TEXT[game.current]
            if game.in_check(game.current):
                check_text = f"{game.current.label} Is in Check!"
        self._turn.config(text=title, fg=colour)
        self._check_label.config(text=check_text)

    def _refresh_upgrade(self) -> None:
        """Update the (always-visible, fixed-size) upgrade card. The
        prompt holder and editor stay in the same spot the whole time —
        the editor blank, guides only, while idle — with the spend prompt
        text and Done button only appearing while bonus points are
        actually pending, which is never the case during deployment
        (there's no ``self._game`` yet to have a pending upgrade at all)."""
        upgrade = self._game.upgrade if self._game is not None else None
        if upgrade is None:
            self._upgrade_label.config(text="")
            self._upgrade_done.pack_forget()
            self._editor.show(None)
            return
        self._upgrade_label.config(
            text=f"Spend {theme.points_text(upgrade.points)} of bonus on this "
                 "piece. Unspent points are lost.")
        self._editor.show(upgrade.piece)
        self._upgrade_done.pack(pady=(self._gap, 0), fill=tk.X)
