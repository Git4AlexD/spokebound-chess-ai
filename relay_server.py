"""Standalone relay server for cross-network play — run this on a
small always-on server with a public IP (see the project README for
how this fits into the room-code system), never on either player's
own machine: the whole point is a third machine neither player's
router has any say over, so nobody has to forward a port.

Usage (on the server):

    python relay_server.py [port]

Defaults to port 51822 if not given. Needs nothing beyond the
standard library.

Protocol: a client connects and sends one line of JSON immediately —
``{"role": "host", "room_code": "ABCDE"}`` or
``{"role": "join", "room_code": "ABCDE"}``. A host is held open,
waiting; when a joiner registers the same code, both get a
``{"type": "paired"}`` line back and the server then just pipes raw
bytes between the two sockets, in both directions, until either side
disconnects — it never looks at the game traffic itself past that
point, so a protocol change on the game's side never needs a matching
change here. A joiner whose code has no waiting host gets
``{"type": "error", "message": "..."}`` and the connection is closed.

Deliberately not the same process as the game — it's meant to run
once, unattended, on a server, serving any number of matches over
time, restarted only if the machine itself reboots.
"""

import json
import socket
import sys
import threading

DEFAULT_PORT = 51822
_BUFFER = 4096


def _read_line(conn: socket.socket) -> str:
    """Read up to and including the first newline, byte at a time —
    simple and a little slow, but this only ever reads one short
    registration line per connection, so it doesn't matter, and it
    guarantees nothing past the newline is consumed (which a
    buffered/chunked read could accidentally swallow some of the game
    traffic that follows right after)."""
    chars = bytearray()
    while True:
        byte = conn.recv(1)
        if not byte:
            raise ConnectionError("closed before sending a full line")
        if byte == b"\n":
            break
        chars += byte
    return chars.decode("utf-8")


def _relay(a: socket.socket, b: socket.socket) -> None:
    """Copy bytes from ``a`` to ``b`` until either end closes — run as
    two of these, one in each direction, per paired connection."""
    try:
        while True:
            chunk = a.recv(_BUFFER)
            if not chunk:
                break
            b.sendall(chunk)
    except OSError:
        pass
    finally:
        for sock in (a, b):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class _Rooms:
    """Room codes currently waiting for a joiner — a plain dict
    guarded by a lock, since connection-handling threads touch it
    concurrently."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiting: dict[str, socket.socket] = {}

    def wait(self, room_code: str, conn: socket.socket) -> None:
        with self._lock:
            # A second host registering the same code (a restart, or a
            # genuine — vanishingly unlikely — collision) replaces
            # whoever was waiting before; that older connection is
            # simply never paired and will sit idle until the host's
            # own side times out or closes it.
            self._waiting[room_code] = conn

    def claim(self, room_code: str) -> socket.socket | None:
        with self._lock:
            return self._waiting.pop(room_code, None)


def _handle(conn: socket.socket, rooms: _Rooms) -> None:
    try:
        message = json.loads(_read_line(conn))
        role = message.get("role")
        room_code = message.get("room_code")
        if not isinstance(room_code, str) or role not in ("host", "join"):
            conn.close()
            return

        if role == "host":
            rooms.wait(room_code, conn)
            return  # the joiner's own thread does the pairing below

        host_conn = rooms.claim(room_code)
        if host_conn is None:
            conn.sendall(json.dumps(
                {"type": "error",
                 "message": "No one is hosting that room code right now."}
            ).encode("utf-8") + b"\n")
            conn.close()
            return

        paired = json.dumps({"type": "paired"}).encode("utf-8") + b"\n"
        try:
            host_conn.sendall(paired)
            conn.sendall(paired)
        except OSError:
            for sock in (host_conn, conn):
                try:
                    sock.close()
                except OSError:
                    pass
            return

        threading.Thread(target=_relay, args=(host_conn, conn),
                         daemon=True).start()
        _relay(conn, host_conn)
    except (OSError, ValueError, ConnectionError):
        try:
            conn.close()
        except OSError:
            pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    rooms = _Rooms()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", port))
    listener.listen(64)
    print(f"Relay listening on 0.0.0.0:{port}")

    try:
        while True:
            conn, addr = listener.accept()
            threading.Thread(target=_handle, args=(conn, rooms),
                             daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        listener.close()


if __name__ == "__main__":
    main()
