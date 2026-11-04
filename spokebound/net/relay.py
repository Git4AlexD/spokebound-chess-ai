"""Client side of the cross-network relay (see relay_server.py at the
project root for the server this talks to, and its own docstring for
the exact wire protocol — registration line, then "paired" or
"error", then raw game bytes both ways).

Kept as its own module, same reasoning as directory.py: this is
another piece a future Steam integration would replace outright
(Steam's own lobby/relay networking takes over this exact job), while
NetworkSession's host/join stay untouched either way — see
session.py's host_via_relay/join_via_relay, the only callers.
"""

import json
import socket
import time
from collections.abc import Callable

from spokebound import secret_config

# The relay server's address (see relay_server.py for what has to
# actually be running there on this same port), read from the
# git-ignored spokebound/secrets.json — see spokebound.secret_config.
# None disables the relay path entirely: hosting/joining then only
# ever uses LAN broadcast or a manually-typed address.
RELAY_ADDRESS: tuple[str, int] | None = secret_config.relay_address()

# Bounds the initial TCP connect, and (for a joiner only) the wait for
# a "paired"/"error" reply — a host's own wait for a joiner has no
# such bound, since however long a friend takes to actually connect is
# entirely normal, not a stuck connection (see await_pairing).
_CONNECT_TIMEOUT = 8.0


class RelayError(Exception):
    """The relay connection didn't work — none configured, it's
    unreachable, or (when joining) nobody's hosting that code there."""


def address() -> tuple[str, int] | None:
    """Return the configured relay's own address — used only as the
    CONNECTED event's ``data`` (see session.py), never shown to a
    person; a relay connection already never involves either player
    typing or seeing an address at all."""
    return RELAY_ADDRESS


def register(role: str, room_code: str) -> socket.socket:
    """Connect to the relay and send the registration line — fast,
    bounded by _CONNECT_TIMEOUT regardless of ``role``. Returns the
    socket right after, *before* waiting to be paired (see
    await_pairing): split out so a caller can hold onto this socket
    (and close it to cancel) while that wait — potentially a long one,
    for a host — is still happening, the same reason
    NetworkSession._accept exposes its own listener socket early.
    """
    if RELAY_ADDRESS is None:
        raise RelayError("No relay server is configured.")
    try:
        sock = socket.create_connection(RELAY_ADDRESS, timeout=_CONNECT_TIMEOUT)
        sock.sendall((json.dumps({"role": role, "room_code": room_code}) + "\n").encode("utf-8"))
    except OSError as exc:
        raise RelayError(str(exc)) from exc
    return sock


def await_pairing(sock: socket.socket, role: str, should_continue: Callable[[], bool] = lambda: True) -> None:
    """Block until the relay pairs ``sock`` with the other side of the
    room code just registered on it — raises RelayError if the relay
    says no one's there (only ever reachable for a joiner; a host just
    waits, with no timeout of its own — see the module docstring), the
    connection breaks, or ``should_continue()`` turns false (checked
    periodically, not continuously — see the note on the 0.5s
    timeout below on why polling it beats trusting close() from
    another thread to unblock this on its own).
    """
    deadline = None if role == "host" else time.monotonic() + _CONNECT_TIMEOUT
    # A short timeout so this wakes up on its own to check
    # should_continue and the deadline, rather than depending on the
    # socket being closed from another thread to unblock a pending
    # recv() — not reliable on every platform (Windows in particular),
    # same reasoning as NetworkSession._accept/_recv_loop.
    sock.settimeout(0.5)
    buffer = bytearray()
    while True:
        if not should_continue():
            raise RelayError("closed")
        if deadline is not None and time.monotonic() >= deadline:
            raise RelayError("No one is hosting that room code right now.")
        try:
            byte = sock.recv(1)
        except TimeoutError:
            continue
        except OSError as exc:
            raise RelayError(str(exc)) from exc
        if not byte:
            raise RelayError("The relay closed the connection.")
        if byte == b"\n":
            break
        buffer += byte
    try:
        message = json.loads(buffer.decode("utf-8"))
    except ValueError as exc:
        raise RelayError("The relay sent something unexpected.") from exc
    if message.get("type") != "paired":
        raise RelayError(message.get("message", "The relay couldn't connect you."))
