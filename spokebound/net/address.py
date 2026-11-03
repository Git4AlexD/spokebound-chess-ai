"""What port to host a game on, and this machine's own address on it.

Normal play never needs either of these shown to a person — see
:mod:`spokebound.net.directory` for how a room code resolves to one
automatically. :func:`local_ip` and :func:`public_ip` exist for the
manual fallback instead (see :mod:`spokebound.ui.network_lobby_screen`'s
host screen and its direct-IP Join path): two players not on the same
LAN can still connect if the host forwards the game port by hand and
passes on the right address — public_ip if the joiner is elsewhere,
local_ip if they're actually on the same network but LAN discovery
itself isn't reaching them (a broadcast blocked, say) — typed into the
Join box instead of a room code.
"""

import re
import socket
import urllib.request

# Spokebound's own default — arbitrary, but fixed, so both sides of a
# room-code lookup (see spokebound.net.directory) agree on it without
# having to exchange a port too.
DEFAULT_PORT = 51820

# Plain, well-known "what's my address" endpoints — queried in order,
# first one to answer wins. Several rather than one: any single one of
# these being down, or blocked on some particular network, shouldn't
# be the difference between this working or not.
_PUBLIC_IP_SERVICES = (
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
    "https://icanhazip.com",
)
_IPV4_PATTERN = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def local_ip() -> str:
    """Return this machine's own address on whatever network it's
    routed through — the one a friend already able to reach it
    directly (see the module docstring) would connect to. Best-effort:
    falls back to "127.0.0.1" if nothing routable is found (no active
    network connection at all).

    Doesn't actually send anything: connect() on a UDP socket only
    asks the OS which local address *would* be used to reach
    8.8.8.8 — a well-known, always-on address chosen just to force a
    real route lookup, not because anything is sent to it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def public_ip(timeout: float = 3.0) -> str | None:
    """Return this machine's address as seen from the internet — the
    one a friend anywhere can actually be given, unlike local_ip's
    (only reachable on the same network or through it). There's no way
    to learn this purely from local network configuration the way
    local_ip does; it only exists by asking something outside the
    network, so — unlike everything else in this package — this does
    make an ordinary, one-line outbound HTTP request to a plain public
    "what's my address" service, one of a short, short-circuiting list
    (see _PUBLIC_IP_SERVICES) so one being down or blocked isn't fatal.
    Nothing about this machine or the person using it is sent beyond
    the request itself, the same as visiting one of these sites in a
    browser would send. Best-effort: returns None if every service is
    unreachable, blocked, or returns something that isn't a plain
    IPv4 address.
    """
    for service in _PUBLIC_IP_SERVICES:
        try:
            with urllib.request.urlopen(service, timeout=timeout) as resp:
                candidate = resp.read().decode("ascii", "replace").strip()
        except OSError:
            continue
        if _IPV4_PATTERN.match(candidate):
            return candidate
    return None
