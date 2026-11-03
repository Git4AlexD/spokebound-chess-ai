"""Player-made fleets, saved to disk so they outlive a single session.

Same shape as :data:`spokebound.model.presets.PRESETS` — ``FLEET_SIZE``
spoke-level lists per fleet — so a custom fleet loads through
:meth:`~spokebound.model.spending.FleetBuilder.load_preset` exactly like
a built-in one does.
"""

import json
import os
import sys
from pathlib import Path


def _default_store() -> Path:
    if getattr(sys, "frozen", False):
        # Packaged (e.g. by PyInstaller): __file__ lives inside a
        # temporary extraction folder that's deleted when the app
        # closes, so anything saved there would vanish before the next
        # launch. %APPDATA% is the conventional, always-writable place
        # for a Windows app's own persistent data.
        base = Path(os.getenv("APPDATA", Path.home())) / "Spokebound"
    else:
        base = Path(__file__).resolve().parent.parent / "data"
    return base / "custom_fleets.json"


_STORE = _default_store()


def load_all() -> dict[str, list[list[int]]]:
    """Return every saved custom fleet, name -> spoke levels.

    A missing or unreadable store just means "no custom fleets yet"
    rather than an error — nothing has necessarily gone wrong the first
    time this runs, before anyone has saved one.
    """
    if not _STORE.is_file():
        return {}
    try:
        return json.loads(_STORE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(name: str, fleet: list[list[int]]) -> None:
    """Save (or overwrite) one named custom fleet."""
    fleets = load_all()
    fleets[name] = fleet
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(fleets, indent=2))


def delete(name: str) -> None:
    """Remove a saved custom fleet. Does nothing if it isn't there."""
    fleets = load_all()
    if name not in fleets:
        return
    del fleets[name]
    _STORE.write_text(json.dumps(fleets, indent=2))
