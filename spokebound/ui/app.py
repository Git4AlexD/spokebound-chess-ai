"""Top-level window and the flow between screens."""

import contextlib
import ctypes
import sys
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()

from spokebound.ai.build import build_fleet
from spokebound.model.pieces import Piece, Player
from spokebound.net import protocol
from spokebound.net.session import NetworkSession
from spokebound.ui import sound, starfield, theme
from spokebound.ui.ai_menu_screen import AIMenuScreen
from spokebound.ui.build_screen import BuildScreen
from spokebound.ui.custom_fleet_screen import CustomFleetScreen
from spokebound.ui.deploy_screen import DeployScreen
from spokebound.ui.layout import watch_resize, window_scale
from spokebound.ui.network_lobby_screen import NetworkLobbyScreen
from spokebound.ui.network_wait_screen import NetworkWaitScreen
from spokebound.ui.online_menu_screen import OnlineMenuScreen
from spokebound.ui.settings_gear import add_gear
from spokebound.ui.tutorial_screen import TutorialScreen
from spokebound.ui.welcome_screen import WelcomeScreen

# Which side the human plays against the computer; the AI always takes
# the other one.
HUMAN_PLAYER = Player.ORANGE

TITLE = "Spokebound"


class HandoverScreen(tk.Frame):
    """A blank screen shown while the device is passed between players."""

    def __init__(self, parent: tk.Misc, message: str, button_text: str,
                 on_ready: Callable[[], None],
                 on_main_menu: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._message = message
        self._button_text = button_text
        self._on_ready = on_ready
        self._on_main_menu = on_main_menu
        self._rebuild()
        # Keeps this screen's scale matched to the window as it's
        # resized (see the same note on AIMenuScreen) — otherwise a
        # fixed size regardless of the window, left small and lost on
        # a big one.
        watch_resize(self, self._rebuild)

    def _rebuild(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        starfield.add_starfield(self)
        scale = window_scale(self)
        theme.make_button(self, "Main Menu", self._on_main_menu,
                          secondary=True).pack(anchor=tk.NW, padx=16,
                                               pady=16)
        theme.make_label(self, "Spokebound",
                         theme.scaled_font(theme.FONT_TITLE, scale),
                         fg=theme.ACCENT).pack(pady=(round(100 * scale), 4))
        theme.make_label(self, self._message,
                         theme.scaled_font(theme.FONT_HEADING, scale)
                         ).pack(pady=16)
        theme.make_button(self, self._button_text, self._on_ready).pack()
        add_gear(self)


class SpokeboundApp(tk.Tk):
    """Moves through: welcome, Orange builds, White builds, deploy, play."""

    def __init__(self) -> None:
        super().__init__()
        self.title(TITLE)
        # A fully transparent window icon in place of Tk's default
        # feather, matching the blank assets/icon.ico a packaged .exe
        # carries. Kept on self: Tk drops a PhotoImage nothing else holds.
        self._blank_icon = tk.PhotoImage(width=16, height=16)
        self.iconphoto(True, self._blank_icon)
        sound.keep_output_awake()
        self.configure(bg=theme.BACKGROUND)
        self._maximize()
        # A modest floor, not a target: screens themselves are sized to
        # fit the window, so this just stops later manual resizes from
        # going unreasonably small.
        self.minsize(640, 480)
        theme.apply_styles(self)
        self._screen: tk.Frame | None = None
        self._fleets: dict[Player, list[Piece]] = {}
        self._ai_player: Player | None = None
        self._ai_difficulty: int | None = None
        # Only set for a network match — see _network_connected.
        self._session: NetworkSession | None = None
        self._local_player: Player | None = None
        self._remote_player: Player | None = None
        self.show_welcome()

    def show_welcome(self) -> None:
        """Show the welcome menu. 2-Player Local, Play vs AI and Online
        Match are wired up; Tutorial is too. Story Mode is laid out and
        styled, ready for a callback to be added here once it exists."""
        # Starts the menu music fresh — it then plays on undisturbed
        # through every pre-game screen (difficulty, build, deploy),
        # since none of those touch it; only _start_deploy stops it.
        sound.play_menu_music()
        self._show(WelcomeScreen(self, {
            "local": self.start_new_game,
            "ai": self.start_ai_game,
            "tutorial": self.show_tutorial,
            "custom_fleets": self.show_custom_fleets,
            "online": self.show_online_menu,
        }))

    def show_tutorial(self) -> None:
        """Show the rules reference screen. Nothing's in progress to
        lose getting here from the welcome menu, so its Main Menu button
        goes straight back rather than through the discard confirmation
        every in-game screen uses."""
        self._show(TutorialScreen(self, self.show_welcome))

    def show_custom_fleets(self) -> None:
        """Show the custom-fleet builder. Same reasoning as the
        tutorial: nothing in progress to lose, so straight back to the
        welcome menu rather than the discard confirmation."""
        self._show(CustomFleetScreen(self, self.show_welcome))

    def show_online_menu(self) -> None:
        """Show the Online Match sub-menu: invite a friend directly, or
        (once it exists) a matched competitive game."""
        self._show(OnlineMenuScreen(
            self, {"invite": self.show_network_lobby}, self.show_welcome))

    def show_network_lobby(self) -> None:
        """Show the host-or-join screen for inviting a friend."""
        self._show(NetworkLobbyScreen(
            self, self._network_connected, self.show_welcome))

    def _network_connected(self, session: NetworkSession,
                           is_host: bool) -> None:
        """A friend just connected — the host always plays Orange (and
        so moves first), matching who's "in charge" of the match.
        Everything from here on is the same build/deploy/play flow as
        any other game, just relayed over ``session`` instead of taken
        from local turns or the AI (see DeployScreen's own
        ``session``/``remote_player``)."""
        self._session = session
        self._local_player = Player.ORANGE if is_host else Player.WHITE
        self._remote_player = self._local_player.opponent
        self._fleets = {}
        self._ai_player = None
        self._ai_difficulty = None
        self._show(BuildScreen(
            self, self._local_player, self._network_fleet_done,
            self._network_main_menu))

    def _network_fleet_done(self, fleet: list[Piece]) -> None:
        """Send the local fleet to the opponent, then wait for theirs
        — Deployment needs both fleets up front, unlike local play,
        where White simply builds after Orange on the same device."""
        self._fleets[self._local_player] = fleet
        self._session.send(protocol.fleet(fleet))
        self._show(NetworkWaitScreen(
            self, self._session,
            "Waiting for your friend to finish building their fleet…",
            protocol.FLEET, self._network_fleet_received,
            self._network_disconnected))

    def _network_fleet_received(self, message: dict) -> None:
        """The opponent's fleet arrived — both are locked in, so reveal
        and deploy, same as a local match once White finishes building."""
        self._fleets[self._remote_player] = protocol.fleet_from(message)
        self._start_deploy()

    def _network_disconnected(self) -> None:
        """The opponent left before a network match properly began —
        while still building, or waiting on their fleet."""
        messagebox.showwarning(
            "Connection Lost", "Your opponent disconnected.", parent=self)
        self._network_main_menu()

    def _network_main_menu(self) -> None:
        """Leave a network match before real play is under way (still
        picking a side, building, or waiting on the opponent's fleet)
        — no discard confirmation, since there's no board or moves yet
        to lose, unlike _confirm_main_menu's use from deployment on."""
        self._end_network_session()
        self.show_welcome()

    def _end_network_session(self) -> None:
        """Close any active network connection and clear its state, so
        it never leaks into a later local or AI game."""
        if self._session is not None:
            self._session.close()
        self._session = None
        self._remote_player = None

    def _confirm_main_menu(self) -> None:
        """Ask before discarding the build/game in progress and
        returning to the main menu — every screen's "Main menu" button
        goes through here rather than calling show_welcome directly."""
        if messagebox.askyesno(
                "Return to Main Menu?",
                "This will discard the current game. Are you sure?",
                parent=self):
            self._end_network_session()
            self.show_welcome()

    def _maximize(self) -> None:
        """Start maximized, so the board isn't packed into a small corner.

        Board sizing (see :mod:`board_view`) reads the window's real,
        already-maximized client area, so this has to happen — and be
        applied via ``update`` — before any screen is built.
        """
        try:
            self.state("zoomed")  # Windows, and some Linux window managers
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)  # other Linux managers
            except tk.TclError:
                width = self.winfo_screenwidth()
                height = self.winfo_screenheight()
                self.geometry(f"{width}x{height}+0+0")
        self.update()

    def start_new_game(self) -> None:
        """Discard any current game and start a 2-player local build
        phase — the "2-Player Local" welcome-menu entry, always local
        regardless of what was last played."""
        self._fleets = {}
        self._ai_player = None
        self._ai_difficulty = None
        self._end_network_session()
        self._handover_to_builder(Player.ORANGE)

    def _play_again(self) -> None:
        """Start a new game in whichever mode — and, for an AI game, the
        same difficulty — was just played. What every "New Game" button
        actually goes through, instead of always dropping back to a
        fresh local game."""
        if self._session is not None:
            # A network match's fleets and connection are one-shot —
            # playing again would mean a whole new host/join handshake,
            # so this returns to the menu rather than trying to reuse
            # the same session for a second match.
            self._end_network_session()
            self.show_welcome()
            return
        self._fleets = {}
        # This skips the welcome screen entirely, so the music has to
        # be restarted here explicitly rather than relying on
        # show_welcome — it was stopped when the finished game began.
        sound.play_menu_music()
        if self._ai_player is not None:
            self._ai_difficulty_chosen(self._ai_difficulty)
        else:
            self._handover_to_builder(Player.ORANGE)

    def start_ai_game(self) -> None:
        """Discard any current game and ask which difficulty to play."""
        self._fleets = {}
        self._end_network_session()
        self._show(AIMenuScreen(self, self._ai_difficulty_chosen,
                                self._confirm_main_menu))

    def _ai_difficulty_chosen(self, difficulty: int) -> None:
        """Start building the human's fleet now that a difficulty is
        picked; the AI's own fleet is generated once that's locked in.
        No handover screen first — there's only one device in play."""
        self._ai_difficulty = difficulty
        self._ai_player = HUMAN_PLAYER.opponent
        self._show(BuildScreen(
            self, HUMAN_PLAYER,
            lambda fleet: self._fleet_done(HUMAN_PLAYER, fleet),
            self._confirm_main_menu))

    def _show(self, screen: tk.Frame) -> None:
        """Replace the current screen with ``screen``.

        Packs ``screen`` in (on top, since a newly packed widget is
        raised above its existing siblings) before destroying the old
        one, not after — the two briefly overlap rather than leaving a
        gap where neither is shown. ``screen`` itself was already
        fully built by its own ``__init__`` before this ever runs, so
        by the time it's actually on screen there's nothing left to
        fill in after the fact.

        The one transition this doesn't cover is deployment handing
        off to actual play — those never go through here at all, since
        they're the same DeployScreen instance throughout (see its own
        module docstring); this is for transitions between genuinely
        different screens, like one handover screen to the next."""
        screen.pack(fill=tk.BOTH, expand=True)
        if self._screen is not None:
            self._screen.destroy()
        self._screen = screen

    def _handover_to_builder(self, player: Player) -> None:
        """Ask for the device to be passed to ``player`` before they build."""
        def open_builder() -> None:
            self._show(BuildScreen(
                self, player, lambda fleet: self._fleet_done(player, fleet),
                self._confirm_main_menu))

        self._show(HandoverScreen(
            self, f"Pass the Device to {player.label}",
            "Start Building", open_builder, self._confirm_main_menu))

    def _fleet_done(self, player: Player, fleet: list[Piece]) -> None:
        """Store a finished fleet and move to the next step."""
        self._fleets[player] = fleet
        if self._ai_player is not None:
            # An AI game: only the human builds; the computer's fleet is
            # generated on the spot, entirely blind to what the human
            # just built — see spokebound.ai.build.
            self._fleets[self._ai_player] = build_fleet(
                self._ai_difficulty, self._ai_player)
            self._start_deploy()
            return
        if player is Player.ORANGE:
            self._handover_to_builder(Player.WHITE)
            return
        self._show(HandoverScreen(
            self, "Both Fleets Are Locked In.", "Reveal and Deploy",
            self._start_deploy, self._confirm_main_menu))

    def _start_deploy(self) -> None:
        """Reveal both fleets and let them alternate placing pieces —
        the same screen then plays the game itself straight through
        once both fleets are down (see deploy_screen's own module
        docstring), rather than handing off to a separate screen at
        that boundary."""
        # The menu loop's last moment — fleets are secret no more and
        # the board's about to matter, so the music stops here rather
        # than waiting for the first move.
        sound.stop()
        self._show(DeployScreen(
            self, self._fleets[Player.ORANGE], self._fleets[Player.WHITE],
            self._play_again, self._confirm_main_menu,
            ai_player=self._ai_player, ai_difficulty=self._ai_difficulty,
            session=self._session, remote_player=self._remote_player))


def main() -> None:
    """Launch the Spokebound window."""
    SpokeboundApp().mainloop()
