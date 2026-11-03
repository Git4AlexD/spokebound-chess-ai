"""A themed name-entry popup, in place of tkinter.simpledialog — that
renders as a plain, unstyled OS dialog box that clashes hard with the
rest of the app's own look, so nothing here uses it."""

import tkinter as tk

from spokebound.ui import theme

DIALOG_WIDTH = 320


class NameDialog(tk.Toplevel):
    """Blocks until closed, like ``tkinter.simpledialog.askstring`` —
    the whole point is to be a drop-in replacement for it — then leaves
    the entered name in ``.result``, or ``None`` if cancelled, closed,
    or left blank.
    """

    def __init__(self, parent: tk.Misc, title: str, prompt: str,
                initial: str = "") -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.result: str | None = None

        theme.make_label(self, prompt, theme.FONT_BODY, fg=theme.TEXT,
                         bg=theme.BACKGROUND, wraplength=DIALOG_WIDTH - 48,
                         justify=tk.LEFT).pack(padx=24, pady=(24, 12),
                                              anchor=tk.W)

        # Not "_name": tk.Widget already uses that internally for the
        # Tcl widget path, and overwriting it corrupts destroy().
        self._name_var = tk.StringVar(value=initial)
        entry = tk.Entry(
            self, textvariable=self._name_var, font=theme.FONT_BODY,
            width=28, bg=theme.PANEL, fg=theme.TEXT,
            insertbackground=theme.TEXT, disabledbackground=theme.PANEL,
            relief=tk.FLAT, highlightthickness=2,
            highlightbackground=theme.DISABLED, highlightcolor=theme.ACCENT)
        entry.pack(padx=24, pady=(0, 20), ipady=4)
        entry.focus_set()
        entry.select_range(0, tk.END)
        entry.bind("<Return>", lambda _e: self._confirm())
        entry.bind("<Escape>", lambda _e: self._cancel())

        buttons = tk.Frame(self, bg=theme.BACKGROUND)
        buttons.pack(padx=24, pady=(0, 24), fill=tk.X)
        theme.make_button(buttons, "Cancel", self._cancel,
                          secondary=True).pack(side=tk.LEFT, expand=True,
                                               fill=tk.X, padx=(0, 6))
        theme.make_button(buttons, "Save", self._confirm).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(6, 0))

        # A real popup: grabs input until closed (including via the
        # window's own close button), centred over the window that
        # opened it, and blocks the caller until it's done — the same
        # way simpledialog.askstring behaves, so callers read it the
        # same way: ``name = NameDialog(self, ...).result``.
        self.update_idletasks()
        root = parent.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - self.winfo_width()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.wait_window()

    def _confirm(self) -> None:
        self.result = self._name_var.get().strip() or None
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
