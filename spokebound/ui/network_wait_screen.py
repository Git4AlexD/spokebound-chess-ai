"""A blank screen shown while waiting for a network opponent to catch
up to the same point — building their fleet, right now the only gap
where both sides can't already be looking at the same live screen (see
DeployScreen's own ``session``/``remote_player`` for once play is
properly underway)."""

import tkinter as tk
from collections.abc import Callable

from spokebound.net.protocol import Message
from spokebound.net.session import NetworkSession
from spokebound.ui import starfield, theme
from spokebound.ui.layout import watch_resize, window_scale
from spokebound.ui.network_poll import NetworkPoller
from spokebound.ui.settings_gear import add_gear

POLL_MS = 100


class NetworkWaitScreen(tk.Frame):
    """Shows ``message`` and polls ``session`` until a message whose
    ``"type"`` is ``message_type`` arrives, then calls
    ``on_message(data)`` with the decoded message. Calls
    ``on_disconnected()`` instead if the peer disconnects or the
    connection errors out first."""

    def __init__(self, parent: tk.Misc, session: NetworkSession,
                 message: str, message_type: str,
                 on_message: Callable[[Message], None],
                 on_disconnected: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.BACKGROUND)
        self._session = session
        self._message_type = message_type
        self._on_message = on_message
        self._message = message
        self._poller = NetworkPoller(self, session, POLL_MS,
                                     self._handle_message, on_disconnected)

        self._rebuild()
        # Keeps this screen's scale matched to the window as it's
        # resized (see the same note on AIMenuScreen).
        watch_resize(self, self._rebuild)

        self.bind("<Destroy>", self._on_destroy)
        # Deferred, never called straight from __init__: on_message can
        # replace the app's current screen (see _start_deploy), and
        # this screen is still mid-construction here — still just an
        # argument to the *outer*, not-yet-run app._show(NetworkWait
        # Screen(...)) call that's about to make IT the current screen.
        # If the target message already happened to be queued (the
        # common case for whichever side submits second — the other
        # side's message is already sitting there), calling on_message
        # straight from here would recursively show the *next* screen
        # before that outer call ever runs — which then clobbers it
        # right back off screen, destroying it in favour of this one,
        # now stuck forever waiting on a message already consumed.
        # Scheduling this for the next tick instead lets __init__ (and
        # the outer _show call it's an argument to) finish first.
        self._poller.start(delay_ms=0)

    def _rebuild(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        starfield.add_starfield(self)
        scale = window_scale(self)
        theme.make_label(self, "Spokebound",
                         theme.scaled_font(theme.FONT_TITLE, scale),
                         fg=theme.ACCENT).pack(pady=(round(120 * scale), 4))
        theme.make_label(self, self._message,
                         theme.scaled_font(theme.FONT_HEADING, scale)).pack()
        add_gear(self)

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        self._poller.cancel()

    def _handle_message(self, data: Message) -> bool:
        """Return True (stopping the poller) once the one message this
        screen is waiting for arrives; ignore anything else and keep
        waiting."""
        if data.get("type") != self._message_type:
            return False
        self._on_message(data)
        return True
