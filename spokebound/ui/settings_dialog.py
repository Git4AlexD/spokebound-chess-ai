"""The settings popup, opened from the gear icon every screen shows in
its own top-right corner (see spokebound.ui.settings_gear).

Two independent mute switches for now — sound.set_music_muted and
set_effects_muted already hold the actual muting logic, so this dialog
is only ever a thin face on top of them.
"""

import tkinter as tk

from spokebound.ui import sound, theme

BUTTON_WIDTH = 132
BUTTON_HEIGHT = 40


class SettingsDialog(tk.Toplevel):
    """A small modal popup over whatever screen opened it."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())

        theme.make_label(self, "Settings", theme.FONT_TITLE,
                         fg=theme.ACCENT, bg=theme.BACKGROUND).pack(
            padx=24, pady=(24, 16))

        # Rebuilt on every toggle rather than having its two buttons'
        # own text updated in place — each one is still pinned to the
        # same fixed width and height every time, so the dialog itself
        # never changes shape; only the label inside each button does,
        # and that label shrinks to fit rather than the button growing.
        self._buttons_row = tk.Frame(self, bg=theme.BACKGROUND)
        self._buttons_row.pack(padx=24, pady=(0, 16))
        self._refresh()

        theme.make_button(self, "Close", self.destroy,
                          secondary=True).pack(padx=24, pady=(0, 24),
                                               fill=tk.X)

        # A real popup, not just another screen: grabs input until
        # closed, and centred over the window that opened it.
        self.update_idletasks()
        root = parent.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - self.winfo_width()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.focus_set()

    def _toggle_music(self) -> None:
        sound.set_music_muted(not sound.is_music_muted())
        self._refresh()

    def _toggle_effects(self) -> None:
        sound.set_effects_muted(not sound.is_effects_muted())
        self._refresh()

    def _refresh(self) -> None:
        for child in self._buttons_row.winfo_children():
            child.destroy()
        music_text = "Unmute Music" if sound.is_music_muted() else "Mute Music"
        effects_text = ("Unmute Sound" if sound.is_effects_muted()
                        else "Mute Sound")
        theme.make_fixed_button(
            self._buttons_row, music_text, self._toggle_music,
            BUTTON_WIDTH, BUTTON_HEIGHT).pack(side=tk.LEFT, padx=(0, 8))
        theme.make_fixed_button(
            self._buttons_row, effects_text, self._toggle_effects,
            BUTTON_WIDTH, BUTTON_HEIGHT).pack(side=tk.LEFT)
