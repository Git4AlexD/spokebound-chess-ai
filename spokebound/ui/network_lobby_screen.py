"""Host or join a friend's game over the network.

There's no matchmaking server — the game itself still connects
directly, host to joiner, on the host's own device. On the same LAN,
neither side has to know an address at all: hosting shows a short room
code to read or type to a friend out of band (chat, a call); joining
means typing that code back in, and the two find each other with a LAN
broadcast (see :mod:`spokebound.net.directory`) — nothing about that
broadcast, or anything else here, can ever cross a router onto the
open internet, no matter what either side's own network allows out.

Reaching a friend who isn't on the same LAN needs a real address —
unless a relay server is configured (see :mod:`spokebound.net.relay`:
a small always-on third machine, on neither player's own network, that
both sides connect *out* to — never blocked by a router, the same way
visiting a website never is). When one is, hosting registers the same
room code with it as the LAN broadcast, and joining tries both at
once (see _start_waiting) — whichever answers first wins, so the one
room code just works whether a friend's on the LAN or across the
world, with no router settings touched on either end.

Without a relay configured (relay.RELAY_ADDRESS is None), hosting
falls back to looking up this machine's own public IP instead (see
address.public_ip — a plain outbound lookup, no router cooperation
needed) and building a code from it directly (see
directory.encode_address). A friend anywhere can type that into the
same Join box — but it only actually connects once the host has
forwarded the game port by hand, which _render_host says outright
rather than implying the code alone is enough (an earlier version
tried UPnP, asking a router to forward the port itself with no login
needed — pulled after turning out to not work reliably enough to
trust). If even the public IP lookup fails, this falls back once
more, to the Join box also accepting a raw typed address directly
(see _looks_like_address) for whoever can be reached some other way
(a shared VPN, say). Nothing here hides an address or pretends any of
this is secure — encoding one into a short code is about it being easy
to read aloud, not about anyone reading it back out.

Swapping all of this for a Steam friend/lobby join later wouldn't need
to change anything below — the "Join" card is already keyed on the
same idea (a person to connect to, resolved one way or another) rather
than an address typed by hand every time.
"""

import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable

from spokebound import secret_config
from spokebound.net import relay
from spokebound.net.address import DEFAULT_PORT, local_ip, public_ip
from spokebound.net.directory import (
    RoomHost, decode_address, encode_address, generate_room_code)
from spokebound.net.session import CONNECTED, ERROR, NetworkSession
from spokebound.ui import sound, starfield, theme
from spokebound.ui.layout import watch_resize, window_scale
from spokebound.ui.mode_card import ModeCard
from spokebound.ui.settings_gear import add_gear

CARD_WIDTH = 260
CARD_HEIGHT = 130
# Wide enough for either a 5-character room code or a typed address
# like "203.0.113.10:51820".
ENTRY_WIDTH = 22
# How often to check whether a connection has come through yet.
POLL_MS = 100
# public_ip() has its own per-service timeout, but tries several
# services in turn (see its own docstring) — a genuinely stuck one
# would otherwise leave "checking" on screen well past what that alone
# suggests; this is the hard ceiling that can't happen past, checked
# independently on the UI side rather than trusted to the background
# thread ever coming back at all.
PUBLIC_IP_OVERALL_TIMEOUT = 10.0
# How far this screen's content may grow past its base size to fill a
# big window — see layout.window_scale.
MAX_SCALE = 2.2

# address.public_ip() hangs indefinitely on at least one real network
# rather than failing cleanly or within its own timeout — root cause
# not yet found (both a plain `python -m spokebound` run and a
# packaged .exe do it, which rules out PyInstaller packaging as the
# cause). Where that bites, a known-correct value can be set as
# "known_public_ip" in the git-ignored spokebound/secrets.json (see
# spokebound.secret_config) so hosting works immediately rather than
# sitting on "Looking up..." — see _show_host. Unset, the real lookup
# runs. Only ever consulted when no relay is configured.
_KNOWN_PUBLIC_IP: str | None = secret_config.known_public_ip()

OnConnected = Callable[[NetworkSession, bool], None]


def _looks_like_address(text: str) -> bool:
    """Return whether ``text`` looks like a host address rather than a
    room code — a room code is always exactly CODE_LENGTH characters
    from its own fixed alphabet (see directory.generate_room_code),
    which never includes '.' or ':'."""
    return "." in text or ":" in text


def _parse_address(text: str) -> tuple[str, int]:
    """Split ``text`` into ``(host, port)``, defaulting to
    DEFAULT_PORT when no ``:port`` was typed."""
    host, _, port = text.partition(":")
    return host, int(port) if port else DEFAULT_PORT


class NetworkLobbyScreen(tk.Frame):
    """Choose to host or join, then wait for the connection to
    complete. Calls ``on_connected(session, is_host)`` once it has —
    the caller takes it from there (building a fleet, then play)."""

    def __init__(self, parent: tk.Misc, on_connected: OnConnected,
                 on_main_menu: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._on_connected = on_connected
        self._on_main_menu = on_main_menu
        self._session: NetworkSession | None = None
        # The relay attempt racing alongside self._session — see
        # _show_host/_start_join/_start_waiting. Only ever set
        # alongside self._session, never instead of it.
        self._relay_session: NetworkSession | None = None
        # Only set while hosting — see _show_host/_stop_room_host.
        self._room_host: RoomHost | None = None
        self._room_code: str | None = None
        self._local_address: str | None = None
        # Public-IP lookup state, only meaningful while hosting — see
        # _show_host/_poll_public_ip. _public_ip_status starts
        # "unavailable" (rather than a separate "not hosting" state)
        # since that's exactly how _render_host should treat it before
        # hosting has ever kicked the lookup off.
        self._public_ip_status = "unavailable"
        self._public_ip: str | None = None
        self._address_code: str | None = None
        self._public_ip_results: queue.Queue = queue.Queue()
        self._public_ip_poll_job: str | None = None
        self._public_ip_deadline = 0.0
        self._poll_job: str | None = None
        # Whichever _render_* draws the screen's current view — kept so
        # a resize (see _redraw) can redraw it at the new scale without
        # repeating the one-time side effects (starting a session,
        # generating a room code) its _show_* only belongs to.
        self._render: Callable[[], None] = self._render_choice
        self.bind("<Destroy>", self._on_destroy)
        self._show_choice()
        # Keeps this screen's scale matched to the window as it's
        # resized (see the same note on AIMenuScreen).
        watch_resize(self, self._redraw)

    def _redraw(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        starfield.add_starfield(self)
        self._render()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        self._cancel_poll()
        self._stop_room_host()
        self._cancel_public_ip_poll()
        for session in (self._session, self._relay_session):
            if session is not None:
                session.close()

    # ------------------------------------------------------------------
    # Shared plumbing.
    # ------------------------------------------------------------------

    def _clear(self) -> None:
        self._cancel_poll()
        for child in self.winfo_children():
            child.destroy()
        starfield.add_starfield(self)

    def _cancel_poll(self) -> None:
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None

    def _stop_room_host(self) -> None:
        """Stop answering room-code broadcasts — its job is done once
        a friend has actually connected, or hosting is abandoned."""
        if self._room_host is not None:
            self._room_host.close()
            self._room_host = None

    def _cancel_public_ip_poll(self) -> None:
        """Stop waiting on the background public-IP lookup, if one's
        still running — same lifecycle as _stop_room_host, called
        alongside it everywhere hosting ends. The lookup thread itself
        just finishes and discards its result into an unread queue."""
        if self._public_ip_poll_job is not None:
            self.after_cancel(self._public_ip_poll_job)
            self._public_ip_poll_job = None

    def _cancel_connection(self) -> None:
        """Abandon a host/join in progress and go back to the choice —
        the "Cancel" button on both the host and join screens."""
        self._stop_room_host()
        self._cancel_public_ip_poll()
        for session in (self._session, self._relay_session):
            if session is not None:
                session.close()
        self._session = None
        self._relay_session = None
        self._show_choice()

    def _start_waiting(self, is_host: bool) -> None:
        """Begin polling every active session (``self._session`` and,
        when a relay's configured, ``self._relay_session`` racing
        alongside it — see _show_host/_start_join) for the first
        CONNECTED event; whichever gets there first is the one kept,
        any other still-pending attempt is closed."""
        def poll() -> None:
            sessions = [s for s in (self._session, self._relay_session)
                       if s is not None]
            for session in sessions:
                for event in session.poll():
                    if event.kind == CONNECTED:
                        sound.play_button_click()
                        self._cancel_poll()
                        self._stop_room_host()
                        self._cancel_public_ip_poll()
                        for other in sessions:
                            if other is not session:
                                other.close()
                        # Cleared before handing off, not after — this
                        # screen is about to be destroyed (the caller
                        # replaces it with the build screen), and
                        # _on_destroy closes self._session/
                        # self._relay_session if still set. Without
                        # this, that close() lands on the exact
                        # connection just handed off, which silently
                        # kills it: nothing touches the session again
                        # until a fleet is actually sent, so it
                        # surfaces as a "disconnect" right on submit
                        # instead of here.
                        self._session = None
                        self._relay_session = None
                        self._on_connected(session, is_host)
                        return
                    if event.kind == ERROR:
                        self._status.config(
                            text=f"Couldn't connect: {event.data}")
            self._poll_job = self.after(POLL_MS, poll)
        poll()

    # ------------------------------------------------------------------
    # The initial host-or-join choice.
    # ------------------------------------------------------------------

    def _show_choice(self) -> None:
        self._clear()
        self._render = self._render_choice
        self._render_choice()

    def _render_choice(self) -> None:
        scale = window_scale(self, max_scale=MAX_SCALE)
        theme.make_button(self, "Main Menu", self._on_main_menu,
                          secondary=True).pack(anchor=tk.NW, padx=16,
                                               pady=16)
        centre = tk.Frame(self, bg=theme.BACKGROUND)
        centre.place(relx=0.5, rely=0.5, anchor="center")
        theme.make_label(centre, "Invite a Friend",
                         theme.scaled_font(theme.FONT_TITLE, scale),
                         fg=theme.ACCENT).pack(pady=(0, round(24 * scale)))

        row = tk.Frame(centre, bg=theme.BACKGROUND)
        row.pack()
        card_w, card_h = round(CARD_WIDTH * scale), round(CARD_HEIGHT * scale)
        ModeCard(row, "Host", "Start a game on this device for a friend "
                              "to join.", self._show_host,
                 card_w, card_h).pack(side=tk.LEFT, padx=round(10 * scale))
        ModeCard(row, "Join", "Connect to a friend who's already "
                              "hosting.", self._show_join,
                 card_w, card_h).pack(side=tk.LEFT, padx=round(10 * scale))
        add_gear(self)

    # ------------------------------------------------------------------
    # Hosting.
    # ------------------------------------------------------------------

    def _show_host(self) -> None:
        self._clear()
        self._room_code = generate_room_code()
        self._local_address = f"{local_ip()}:{DEFAULT_PORT}"
        self._session = NetworkSession.host(DEFAULT_PORT)
        # Answers "who's hosting room_code" broadcasts on the LAN so a
        # friend's Join screen can find this device without either of
        # us ever having to read out an address — the actual game
        # connection above is untouched by any of this.
        try:
            self._room_host = RoomHost(self._room_code, DEFAULT_PORT)
        except OSError:
            # The discovery port is taken or reserved on this machine
            # (see RoomHost). Host anyway: the relay and address-code
            # paths below don't need it, only a LAN friend typing the
            # room code does.
            self._room_host = None
        # Races alongside the LAN session above when a relay's
        # configured — a friend on the LAN still connects the fast,
        # direct way, one elsewhere connects through the relay, and
        # _start_waiting keeps whichever gets there first. When no
        # relay's configured this is just None, and hosting falls back
        # to the address-code/manual-forwarding path below entirely.
        self._relay_session = (NetworkSession.host_via_relay(self._room_code)
                               if relay.address() is not None else None)
        if relay.address() is not None:
            # The relay makes the room code itself enough on its own —
            # skip the public-IP/manual-forwarding path below.
            self._public_ip_status = "found"
            self._public_ip = None
            self._address_code = None
        elif _KNOWN_PUBLIC_IP is not None:
            # See the note on _KNOWN_PUBLIC_IP — skips the lookup
            # (and its "Looking up..." wait) entirely.
            self._public_ip_status = "found"
            self._public_ip = _KNOWN_PUBLIC_IP
            self._address_code = encode_address(_KNOWN_PUBLIC_IP,
                                                DEFAULT_PORT)
        else:
            self._public_ip_status = "checking"
            # Only set once the lookup resolves — see _poll_public_ip
            # and _display_code/_public_ip_note.
            self._public_ip = None
            self._address_code = None
            self._public_ip_deadline = (time.monotonic()
                                        + PUBLIC_IP_OVERALL_TIMEOUT)
            threading.Thread(target=self._lookup_public_ip,
                             daemon=True).start()
            self._poll_public_ip()
        self._render = self._render_host
        self._render_host()
        self._start_waiting(is_host=True)

    def _lookup_public_ip(self) -> None:
        """Find this machine's own public IP — runs on a background
        thread (see the note on NetworkSession for why nothing here
        ever touches Tk), its result handed back through a queue for
        _poll_public_ip to pick up."""
        self._public_ip_results.put(public_ip())

    def _poll_public_ip(self) -> None:
        try:
            address = self._public_ip_results.get_nowait()
        except queue.Empty:
            if time.monotonic() >= self._public_ip_deadline:
                # The background thread hasn't come back at all — a
                # service whose own timeout didn't actually bound it (a
                # slow DNS lookup is the usual culprit; a socket
                # timeout doesn't reliably cover that phase). Treated
                # the same as a normal "didn't work this time" rather
                # than left showing "checking" forever; the thread
                # itself is still out there and will just discard its
                # result into an unread queue whenever it does return.
                address = None
            else:
                self._public_ip_poll_job = self.after(
                    200, self._poll_public_ip)
                return
        self._public_ip_poll_job = None
        self._public_ip = address
        self._public_ip_status = "found" if address is not None else "unavailable"
        self._address_code = (encode_address(address, DEFAULT_PORT)
                              if address is not None else None)
        # Only the host screen ever cares — if hosting was already
        # cancelled (or a friend already connected) by the time this
        # arrives, there's nothing left that needs redrawing for it.
        if self._render is self._render_host:
            self._redraw()

    def _display_code(self) -> str:
        """Return whichever code is currently the best thing to give a
        friend — the address-carrying one once this machine's public
        IP is known (works for anyone, LAN or not, once the port's
        actually forwarded — see _public_ip_note), the plain room code
        until then."""
        return (self._address_code if self._address_code is not None
               else self._room_code)

    def _code_caption(self) -> str:
        if self._address_code is not None:
            return "Once port forwarding's set up, this code works from anywhere:"
        return "Give your friend this room code:"

    def _public_ip_note(self) -> str:
        """Return the small status line under the code, reflecting how
        far _lookup_public_ip has gotten (or, with a relay configured,
        that none of that applies — see _show_host)."""
        if relay.address() is not None:
            return "Works for a friend on your network or anywhere else."
        if self._public_ip_status == "checking":
            return "Looking up your public address…"
        if self._address_code is not None:
            return ("To let a friend elsewhere in, forward TCP port "
                   f"{DEFAULT_PORT} to this PC in your router's "
                   "settings, then give them the code above.")
        return ("This machine's own public address couldn't be found. "
               "Not on your network? Have them enter this address "
               f"instead: {self._local_address}")

    def _render_host(self) -> None:
        scale = window_scale(self, max_scale=MAX_SCALE)
        theme.make_button(self, "Main Menu", self._on_main_menu,
                          secondary=True).pack(anchor=tk.NW, padx=16,
                                               pady=16)
        centre = tk.Frame(self, bg=theme.BACKGROUND)
        centre.place(relx=0.5, rely=0.5, anchor="center")
        theme.make_label(centre, "Hosting a Game",
                         theme.scaled_font(theme.FONT_TITLE, scale),
                         fg=theme.ACCENT).pack(pady=(0, round(16 * scale)))
        theme.make_label(centre, self._code_caption(),
                         theme.scaled_font(theme.FONT_BODY, scale),
                         fg=theme.MUTED_TEXT).pack()

        theme.make_label(centre, self._display_code(),
                         theme.scaled_font(theme.FONT_HERO, scale),
                         fg=theme.TEXT).pack(pady=(round(4 * scale),
                                                    round(16 * scale)))
        theme.make_label(
            centre, self._public_ip_note(),
            theme.scaled_font(theme.FONT_SMALL, scale),
            fg=theme.MUTED_TEXT, wraplength=round(320 * scale),
            justify=tk.CENTER).pack(pady=(0, round(16 * scale)))
        self._status = theme.make_label(
            centre, "Waiting for your friend to join…",
            theme.scaled_font(theme.FONT_BODY, scale), fg=theme.MUTED_TEXT)
        self._status.pack(pady=(0, round(16 * scale)))
        theme.make_button(centre, "Cancel", self._cancel_connection,
                          secondary=True).pack()
        add_gear(self)

    # ------------------------------------------------------------------
    # Joining.
    # ------------------------------------------------------------------

    def _show_join(self) -> None:
        self._clear()
        self._code_var = tk.StringVar()
        self._render = self._render_join
        self._render_join()

    def _render_join(self) -> None:
        scale = window_scale(self, max_scale=MAX_SCALE)
        theme.make_button(self, "Main Menu", self._on_main_menu,
                          secondary=True).pack(anchor=tk.NW, padx=16,
                                               pady=16)
        centre = tk.Frame(self, bg=theme.BACKGROUND)
        centre.place(relx=0.5, rely=0.5, anchor="center")
        theme.make_label(centre, "Join a Friend's Game",
                         theme.scaled_font(theme.FONT_TITLE, scale),
                         fg=theme.ACCENT).pack(pady=(0, round(16 * scale)))
        theme.make_label(
            centre, "Enter the code your friend gave you, or their "
                   "address if they gave you one instead:",
            theme.scaled_font(theme.FONT_BODY, scale),
            fg=theme.MUTED_TEXT, wraplength=round(320 * scale),
            justify=tk.CENTER).pack(pady=(0, round(8 * scale)))

        entry = tk.Entry(
            centre, textvariable=self._code_var, width=ENTRY_WIDTH,
            font=theme.scaled_font(theme.FONT_HEADING, scale),
            bg=theme.PANEL, fg=theme.TEXT,
            justify=tk.CENTER, insertbackground=theme.TEXT,
            disabledbackground=theme.PANEL, relief=tk.SOLID, borderwidth=1,
            highlightthickness=1, highlightbackground=theme.DISABLED,
            highlightcolor=theme.ACCENT)
        entry.pack(pady=(0, round(4 * scale)))
        entry.focus_set()
        entry.bind("<Return>", lambda _e: self._start_join())

        self._status = theme.make_label(
            centre, "", theme.scaled_font(theme.FONT_SMALL, scale),
            fg=theme.ACCENT_DARK)
        self._status.pack(pady=(round(4 * scale), round(12 * scale)))
        theme.make_button(centre, "Connect", self._start_join).pack(
            pady=(0, round(8 * scale)))
        theme.make_button(centre, "Cancel", self._on_main_menu,
                          secondary=True).pack()
        add_gear(self)

    def _start_join(self) -> None:
        text = self._code_var.get().strip()
        if not text:
            self._status.config(
                text="Enter a code or an address to connect to.")
            return
        if _looks_like_address(text):
            host, port = _parse_address(text)
            self._status.config(text=f"Connecting to {text}…")
            self._session = NetworkSession.join(host, port)
            self._start_waiting(is_host=False)
            return
        code = text.upper()
        decoded = decode_address(code)
        if decoded is not None:
            # A code that carries its own address (see
            # directory.encode_address) — a friend anywhere can use
            # one of these, not just one on the same LAN, so this
            # connects to it directly rather than going through
            # LAN-broadcast discovery at all.
            host, port = decoded
            self._status.config(text="Connecting…")
            self._session = NetworkSession.join(host, port)
        else:
            self._status.config(
                text="Looking for that room…")
            self._session = NetworkSession.join_by_room_code(code)
            # Races alongside the LAN attempt above when a relay's
            # configured — see the same note in _show_host. A code
            # from a friend who hosted with no relay configured (or
            # one down on their end) simply never gets a relay-side
            # reply, same as the LAN attempt simply never getting one
            # from a friend who isn't actually on this network.
            self._relay_session = (NetworkSession.join_via_relay(code)
                                   if relay.address() is not None else None)
        self._start_waiting(is_host=False)
