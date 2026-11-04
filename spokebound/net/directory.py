"""Resolving a short, shareable room code to a host's actual address
on the LAN.

Kept as its own module, separate from :mod:`spokebound.net.session`,
on purpose: this is the one piece a future Steam integration would
need to replace — swapping this file's broadcast-and-listen lookup for
a Steamworks lobby join, keyed by a friend's Steam profile instead of a
typed code — while :class:`~spokebound.net.session.NetworkSession`'s
own :meth:`~spokebound.net.session.NetworkSession.host`/
:meth:`~spokebound.net.session.NetworkSession.join` (the actual game
connection once two players have found each other) stay exactly as
they are either way. Both directions hand back the same shape — an
``(host, port)`` address, or nothing — regardless of how it was found.

A room code (see generate_room_code) never carries an address — a
joiner's own broadcast request is answered directly by whichever
machine on the LAN is hosting that code, and the reply's own source
address (read straight off the socket, never typed or displayed by a
person) is what gets connected to. encode_address/decode_address are
a different, deliberately-shaped-the-same code for when an address
*is* already known (see spokebound.net.address.public_ip) and openly
being shared instead of hidden — see
:mod:`spokebound.ui.network_lobby_screen` for where each is used.
"""

import contextlib
import json
import secrets
import socket
import struct
import threading
import time

DISCOVERY_PORT = 51821

# No 0/O/1/I/L — each looks like another character read aloud or typed
# in a hurry.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 5
# An IPv4 address + port packs into 6 bytes (48 bits); each character
# below is one base-32 digit (5 bits, since len(_CODE_ALPHABET) == 32),
# so 10 of them (50 bits) comfortably cover it. Deliberately a
# different length from CODE_LENGTH — see decode_address — so the two
# are never ambiguous.
ADDRESS_CODE_LENGTH = 10

_DISCOVER = "discover"
_HERE = "here"


def generate_room_code() -> str:
    """Return a short, random, easy-to-read-aloud room code."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))


def encode_address(host: str, port: int) -> str:
    """Return a short code, in the same read-aloud alphabet as a room
    code, that decodes straight back to ``(host, port)`` — see
    :func:`decode_address`.

    Used when a host's own public address is already known (see
    :func:`spokebound.net.address.public_ip`) so a friend outside the
    LAN can be given one thing to type, shaped the same as a LAN
    friend's room code, rather than a raw, more error-prone
    "203.0.113.10:51820" string. This is *encoding*, not security —
    anyone who can read the code can read the address it carries
    straight back out; the published bytes are the only thing being
    disguised as text, not hidden from anyone who bothers to decode
    it.
    """
    packed = socket.inet_aton(host) + struct.pack(">H", port)
    value = int.from_bytes(packed, "big")
    digits = []
    for _ in range(ADDRESS_CODE_LENGTH):
        value, remainder = divmod(value, len(_CODE_ALPHABET))
        digits.append(_CODE_ALPHABET[remainder])
    return "".join(reversed(digits))


def decode_address(code: str) -> tuple[str, int] | None:
    """Reverse of :func:`encode_address`, or None if ``code`` isn't a
    valid one — the wrong length, a character outside the alphabet, or
    (astronomically unlikely for a real typo, but checked all the
    same) a value too large to be 6 packed bytes."""
    if len(code) != ADDRESS_CODE_LENGTH:
        return None
    value = 0
    for char in code:
        index = _CODE_ALPHABET.find(char)
        if index == -1:
            return None
        value = value * len(_CODE_ALPHABET) + index
    try:
        packed = value.to_bytes(6, "big")
    except OverflowError:
        return None
    host = socket.inet_ntoa(packed[:4])
    port = struct.unpack(">H", packed[4:])[0]
    return host, port


def _local_broadcast_addresses() -> list[str]:
    """Return one guessed subnet broadcast address per local IPv4
    address this machine has — e.g. 192.168.1.42 -> 192.168.1.255.

    The global 255.255.255.255 broadcast :func:`find_room` also always
    sends to is routed by whichever interface the OS picks for its
    default route, which on a multi-homed machine (Wi-Fi and a VPN both
    up, say — common enough on a laptop) can silently be the wrong one,
    never reaching the LAN a friend is actually on. A directed subnet
    broadcast is instead routed by matching its own destination
    address, which reliably picks the interface actually on that
    subnet regardless of which one is "default". The stdlib has no
    portable way to read a real netmask without a third-party
    dependency, so this guesses a /24 — wrong for a differently-sized
    subnet, but harmless either way: nothing on the right subnet is
    reached by a guess that doesn't match it, it's just one more send.
    """
    try:
        _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        return []
    broadcasts = []
    for address in addresses:
        if address.startswith("127."):
            continue
        broadcasts.append(f"{address.rsplit('.', 1)[0]}.255")
    return broadcasts


class RoomHost:
    """Answers "who's hosting room X" broadcasts on the LAN for as
    long as a game is being hosted under ``room_code`` — runs
    *alongside* :meth:`NetworkSession.host
    <spokebound.net.session.NetworkSession.host>`, not instead of it:
    the actual game connection still goes entirely over that session's
    own TCP socket, this only ever hands a joiner the address to
    connect it to.
    """

    def __init__(self, room_code: str, game_port: int, discovery_port: int = DISCOVERY_PORT) -> None:
        """Raises OSError if ``discovery_port`` can't be bound. On
        Windows that includes a port inside a range Hyper-V, WSL or
        Docker has reserved (WinError 10013), which varies from machine
        to machine. Pass 0 to let the OS pick a free port, then read
        the one it chose from :attr:`discovery_port`."""
        self._room_code = room_code
        self._game_port = game_port
        self._closing = False
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind(("0.0.0.0", discovery_port))
        except OSError:
            self._socket.close()
            raise
        self.discovery_port: int = self._socket.getsockname()[1]
        # A short timeout so the listener thread wakes up on its own to
        # check ``_closing`` — closing a socket from another thread
        # doesn't reliably unblock a pending recvfrom() on every
        # platform (Windows in particular), so close() alone can't be
        # trusted to make this thread exit promptly.
        self._socket.settimeout(0.5)
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self) -> None:
        while not self._closing:
            try:
                data, addr = self._socket.recvfrom(1024)
            except TimeoutError:
                continue
            except OSError:
                return  # closed — see close()
            try:
                message = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if message.get("type") == _DISCOVER and message.get("room_code") == self._room_code:
                reply = json.dumps(
                    {
                        "type": _HERE,
                        "room_code": self._room_code,
                        "port": self._game_port,
                    }
                ).encode("utf-8")
                with contextlib.suppress(OSError):
                    self._socket.sendto(reply, addr)

    def close(self) -> None:
        """Stop answering — the room code's done its job once a friend
        has actually connected, or the host gave up waiting."""
        self._closing = True
        with contextlib.suppress(OSError):
            self._socket.close()


def find_room(
    room_code: str, timeout: float = 4.0, discovery_port: int = DISCOVERY_PORT
) -> tuple[str, int] | None:
    """Broadcast a discovery request for ``room_code`` on the LAN and
    wait up to ``timeout`` seconds for its host to answer on
    ``discovery_port``, the port its :class:`RoomHost` listens on.

    Returns the ``(host, port)`` to connect to — meant to be handed
    straight to :meth:`NetworkSession.join
    <spokebound.net.session.NetworkSession.join>` (see
    :meth:`NetworkSession.join_by_room_code
    <spokebound.net.session.NetworkSession.join_by_room_code>`, the
    usual way in) — or ``None`` if nobody answered in time. Blocks the
    calling thread for up to ``timeout`` seconds, so only ever call
    this from a background one, never Tk's own.
    """
    request = json.dumps({"type": _DISCOVER, "room_code": room_code}).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        destinations = [
            "255.255.255.255",
            *_local_broadcast_addresses(),
            # A broadcast doesn't reliably reach the sender's
            # own machine on every OS/network stack — worth
            # also trying loopback directly, both for local
            # testing and for two instances genuinely on the
            # same machine.
            "127.0.0.1",
        ]
        sent = False
        for destination in destinations:
            try:
                probe.sendto(request, (destination, discovery_port))
                sent = True
            except OSError:
                continue
        if not sent:
            return None

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            probe.settimeout(remaining)
            try:
                data, addr = probe.recvfrom(1024)
            except OSError:
                return None
            try:
                message = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if message.get("type") == _HERE and message.get("room_code") == room_code:
                return addr[0], message["port"]
