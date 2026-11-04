"""One peer-to-peer connection for a network match.

Hosting (accept one incoming connection) and joining (connect out) are
just two ways to get a :class:`NetworkSession` — once connected, both
sides are symmetric: either can :meth:`~NetworkSession.send` a message
and both receive one another's.

All socket I/O — accepting, connecting, reading — happens on a
background thread. Nothing here ever calls into Tk: Tkinter isn't
thread-safe, so every notable thing that happens is instead wrapped as
an :class:`Event` and pushed onto a plain, thread-safe ``queue.Queue``.
The Tk side drains it from its own ``after()``-scheduled poll (see
:meth:`~NetworkSession.poll`) — the same pattern the rest of the UI
already uses for the AI's own delayed moves, just fed by a queue
instead of a timer.
"""

import contextlib
import json
import queue
import socket
import threading
from dataclasses import dataclass
from typing import Any

from spokebound.net import relay
from spokebound.net.directory import find_room

CONNECTED = "connected"
MESSAGE = "message"
DISCONNECTED = "disconnected"
ERROR = "error"

_RECV_BUFFER = 4096
# A closed (rather than actively refusing) port can otherwise leave
# connect() hanging far longer than anyone waiting on a Join screen
# would ever want to — bounded here so a bad address fails within a
# reasonable, predictable time instead of however long the OS feels
# like waiting.
_CONNECT_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class Event:
    """One thing that happened on the connection, queued for the Tk
    side to react to. ``data`` is the peer's address for CONNECTED, a
    decoded message dict for MESSAGE, or an error string for ERROR —
    ``None`` for DISCONNECTED."""

    kind: str
    data: Any = None


class NetworkSession:
    """Own one side of a connection — construct via :meth:`host` or
    :meth:`join`, never directly."""

    def __init__(self) -> None:
        self._socket: socket.socket | None = None
        self._listener: socket.socket | None = None
        self._events: queue.Queue[Event] = queue.Queue()
        self._closing = False

    @classmethod
    def host(cls, port: int) -> "NetworkSession":
        """Start listening on ``port`` on every local interface, and
        accept the first connection in the background. A CONNECTED (or
        ERROR) event follows via :meth:`poll` once a friend joins."""
        session = cls()
        threading.Thread(target=session._accept, args=(port,),
                         daemon=True).start()
        return session

    @classmethod
    def join(cls, host: str, port: int) -> "NetworkSession":
        """Connect out to a host already listening on ``host``:``port``.
        A CONNECTED (or ERROR) event follows via :meth:`poll`."""
        session = cls()
        threading.Thread(target=session._connect, args=(host, port),
                         daemon=True).start()
        return session

    @classmethod
    def join_by_room_code(cls, room_code: str,
                          discovery_timeout: float = 4.0) -> "NetworkSession":
        """Look up ``room_code`` on the LAN (see
        :func:`spokebound.net.directory.find_room`), then connect to
        whatever address answers. A CONNECTED (or ERROR — including
        nobody answering the room code at all) event follows via
        :meth:`poll`, same as :meth:`join`; unlike :meth:`join`, the
        address itself is never exposed to the caller, only ever seen
        inside this module."""
        session = cls()
        threading.Thread(target=session._connect_by_room_code,
                         args=(room_code, discovery_timeout),
                         daemon=True).start()
        return session

    @classmethod
    def host_via_relay(cls, room_code: str) -> "NetworkSession":
        """Register ``room_code`` with the configured relay server
        (see :mod:`spokebound.net.relay`) and wait there for a joiner
        to claim it. A CONNECTED (or ERROR) event follows via
        :meth:`poll`, same as :meth:`host` — meant to be started
        *alongside* :meth:`host`, not instead of it, so a LAN friend
        still connects the fast, direct way while one elsewhere
        connects through the relay; whichever gets a CONNECTED event
        first is the one to actually keep (see
        network_lobby_screen._start_waiting)."""
        session = cls()
        threading.Thread(target=session._relay_connect,
                         args=("host", room_code), daemon=True).start()
        return session

    @classmethod
    def join_via_relay(cls, room_code: str) -> "NetworkSession":
        """The other half of :meth:`host_via_relay` — claims
        ``room_code`` at the relay server if a host is waiting there
        under it. A CONNECTED (or ERROR) event follows via
        :meth:`poll`."""
        session = cls()
        threading.Thread(target=session._relay_connect,
                         args=("join", room_code), daemon=True).start()
        return session

    def send(self, message: dict) -> None:
        """Send ``message`` to the peer. Silently dropped if there's no
        connection yet or it's already gone — callers only ever send in
        response to a CONNECTED event or their own local input, both of
        which imply the connection was live a moment ago; a message
        lost to a connection that dies in that instant is no different
        from any other disconnect, caught the same way on the next
        poll()."""
        if self._socket is None:
            return
        with contextlib.suppress(OSError):
            self._socket.sendall((json.dumps(message) + "\n").encode("utf-8"))

    def poll(self) -> list[Event]:
        """Drain and return every event queued since the last call.
        Call this from a Tk ``after()`` loop — never from a background
        thread, and never rely on events arriving one at a time."""
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def close(self) -> None:
        """Tear down the connection — leaving mid-lobby, or the game
        ending. Safe to call more than once, and safe to call while a
        background accept()/connect()/recv() is still in progress: that
        call unblocks with an OSError, which the background thread
        recognises (via ``_closing``) as an intentional shutdown rather
        than a real error, so no ERROR event follows a deliberate close.
        """
        self._closing = True
        for sock in (self._listener, self._socket):
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.close()

    def _accept(self, port: int) -> None:
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", port))
            listener.listen(1)
            self._listener = listener
            # A short timeout so this thread wakes up on its own to
            # check ``_closing`` instead of relying on close() (from
            # another thread) to unblock a pending accept() — that
            # isn't reliable on every platform (Windows in particular).
            listener.settimeout(0.5)
            while True:
                try:
                    sock, addr = listener.accept()
                    break
                except TimeoutError:
                    if self._closing:
                        return
        except OSError as exc:
            if not self._closing:
                self._events.put(Event(ERROR, str(exc)))
            return
        finally:
            if self._listener is not None:
                self._listener.close()
                self._listener = None
        sock.settimeout(None)  # back to blocking for the recv loop
        self._socket = sock
        self._events.put(Event(CONNECTED, addr))
        self._recv_loop()

    def _connect(self, host: str, port: int) -> None:
        try:
            sock = socket.create_connection(
                (host, port), timeout=_CONNECT_TIMEOUT_SECONDS)
        except OSError as exc:
            if not self._closing:
                self._events.put(Event(ERROR, str(exc)))
            return
        sock.settimeout(None)  # back to blocking for the recv loop
        self._socket = sock
        self._events.put(Event(CONNECTED, (host, port)))
        self._recv_loop()

    def _connect_by_room_code(self, room_code: str,
                              discovery_timeout: float) -> None:
        found = find_room(room_code, discovery_timeout)
        if found is None:
            if not self._closing:
                self._events.put(Event(
                    ERROR, "No one is hosting that room code right now."))
            return
        host, port = found
        self._connect(host, port)

    def _relay_connect(self, role: str, room_code: str) -> None:
        try:
            sock = relay.register(role, room_code)
        except relay.RelayError as exc:
            if not self._closing:
                self._events.put(Event(ERROR, str(exc)))
            return
        # Reused the same way _accept reuses it for its own listener:
        # a socket that exists during the connecting phase, before
        # self._socket is set, that close() needs to be able to reach
        # and interrupt — see await_pairing's own note on why a host's
        # wait here can genuinely run long (however long a friend
        # takes to join), not just briefly.
        self._listener = sock
        try:
            relay.await_pairing(sock, role,
                               should_continue=lambda: not self._closing)
        except relay.RelayError as exc:
            self._listener = None
            with contextlib.suppress(OSError):
                sock.close()
            if not self._closing:
                self._events.put(Event(ERROR, str(exc)))
            return
        self._listener = None
        sock.settimeout(None)  # back to blocking for the recv loop
        self._socket = sock
        self._events.put(Event(CONNECTED, relay.address()))
        self._recv_loop()

    def _recv_loop(self) -> None:
        """Read newline-delimited JSON messages until the peer
        disconnects or this session is closed."""
        buffer = b""
        # Same reasoning as _accept()'s timeout: closing the socket
        # from another thread doesn't reliably unblock a pending recv()
        # on every platform, so this thread wakes up on its own to
        # check ``_closing`` instead of depending on that.
        self._socket.settimeout(0.5)
        while True:
            try:
                chunk = self._socket.recv(_RECV_BUFFER)
            except TimeoutError:
                if self._closing:
                    break
                continue
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line:
                    self._events.put(
                        Event(MESSAGE, json.loads(line.decode("utf-8"))))
        if not self._closing:
            self._events.put(Event(DISCONNECTED))
