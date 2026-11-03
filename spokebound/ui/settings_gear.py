"""The small (gear) settings button every screen shows in its own
top-right corner — factored out once so a screen only has to call
add_gear(self) rather than each re-placing (and, after every rebuild,
re-lifting) its own button.
"""

import tkinter as tk

from spokebound.ui import theme
from spokebound.ui.settings_dialog import SettingsDialog


def add_gear(widget: tk.Misc) -> tk.Widget:
    """Place a settings button in ``widget``'s own top-right corner,
    opening :class:`SettingsDialog` on click, and return it.

    Uses ``place()`` (not pack/grid), so it never competes for space
    with whatever layout manager the rest of the screen uses, and sits
    directly on ``widget`` — a screen that destroys and rebuilds its own
    content on resize should either call this again afterwards, or keep
    the widget this returns out of whatever it destroys and call
    ``.lift()`` on it once the new content is up, so it stays on top
    instead of behind whatever was just rebuilt.
    """
    gear = theme.make_button(widget, "⚙", lambda: SettingsDialog(widget),
                             secondary=True, compact=True)
    gear.place(relx=1.0, rely=0.0, x=-16, y=16, anchor=tk.NE)
    return gear
