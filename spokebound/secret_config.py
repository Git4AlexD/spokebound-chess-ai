"""Per-install private settings that must never be committed: the relay
server's address, and an optional fixed public IP for the manual
direct-connect fallback.

They live in ``spokebound/secrets.json``, which is git-ignored — copy
``secrets.example.json`` beside it to start one. A missing file, or a
missing key in it, just switches that feature off rather than failing:
no relay means hosting and joining use LAN discovery or a typed address
only (see spokebound.net.relay), and no known IP means the host screen
looks its public address up live (see spokebound.ui.network_lobby_screen).
"""

import json
from pathlib import Path

from spokebound.resources import package_dir

SECRETS_PATH = package_dir() / "secrets.json"
DEFAULT_RELAY_PORT = 51822


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_SECRETS = _load(SECRETS_PATH)


def relay_address() -> tuple[str, int] | None:
    """Return the relay server's ``(host, port)``, or None if unset."""
    host = _SECRETS.get("relay_host")
    if not host:
        return None
    return host, int(_SECRETS.get("relay_port") or DEFAULT_RELAY_PORT)


def known_public_ip() -> str | None:
    """Return a fixed public IP to advertise when hosting without a
    relay, or None to look it up live."""
    return _SECRETS.get("known_public_ip") or None
