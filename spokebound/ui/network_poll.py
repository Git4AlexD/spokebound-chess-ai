"""Shared glue between a NetworkSession and Tk's own event loop: watch
for messages and disconnection on a repeating ``after()`` timer, so
NetworkWaitScreen and DeployScreen don't each hand-roll the same
drain-and-reschedule loop (they used to, before this).
"""

import tkinter as tk
from collections.abc import Callable

from spokebound.net.protocol import Message
from spokebound.net.session import DISCONNECTED, ERROR, MESSAGE, NetworkSession


class NetworkPoller:
    """Drains ``session.poll()`` on a repeating ``widget.after()`` timer
    until it's cancelled or the connection ends.

    ``on_message(data)`` is called for every MESSAGE event, in arrival
    order; if it returns a true value, polling stops right there rather
    than rescheduling (for a screen watching for one specific message and
    nothing beyond it — see NetworkWaitScreen). ``on_disconnected()`` is
    called at most once, the moment a DISCONNECTED or ERROR event
    arrives, which also ends the loop.
    """

    def __init__(
        self,
        widget: tk.Misc,
        session: NetworkSession,
        interval_ms: int,
        on_message: Callable[[Message], object],
        on_disconnected: Callable[[], None],
    ) -> None:
        self._widget = widget
        self._session = session
        self._interval_ms = interval_ms
        self._on_message = on_message
        self._on_disconnected = on_disconnected
        self._job: str | None = None

    def start(self, delay_ms: int = 0) -> None:
        """Begin polling, first after ``delay_ms`` (immediately, by
        default)."""
        self._job = self._widget.after(delay_ms, self._tick)

    def cancel(self) -> None:
        """Stop polling — call from the widget's own ``<Destroy>``."""
        if self._job is not None:
            self._widget.after_cancel(self._job)
            self._job = None

    def _tick(self) -> None:
        for event in self._session.poll():
            if event.kind == MESSAGE:
                if self._on_message(event.data):
                    return
            elif event.kind in (DISCONNECTED, ERROR):
                self._on_disconnected()
                return
        self._job = self._widget.after(self._interval_ms, self._tick)
