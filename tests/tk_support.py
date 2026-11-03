"""Shared test support for anything that constructs a Tk interpreter.

Creating a fresh ``tk.Tk()`` root once per test — this suite does it a
few dozen times, one per UI test's own ``setUp`` — occasionally hits a
transient Tcl interpreter init failure ("TclError: ... tk wasn't
installed properly", "invalid command name 'tcl_findLibrary'") that
never reproduces when the exact same test is re-run alone. It lands on
a different, unrelated test every time the full suite runs, and every
test's own ``addCleanup(root.destroy)`` already rules out a leak
accumulating across tests — this is Tcl's own init occasionally
tripping over itself under rapid repeated interpreter creation in one
process, not anything wrong with the test or the code it's exercising.

:func:`retry_tcl_init` absorbs that without masking a real,
reproducible failure: a genuinely broken Tcl install fails every
attempt just the same, only slower.
"""

import time
import tkinter as tk
from collections.abc import Callable
from typing import TypeVar

_RETRIES = 3
_RETRY_DELAY_SECONDS = 0.2

_T = TypeVar("_T")


def retry_tcl_init(factory: Callable[[], _T]) -> _T:
    """Call ``factory()``, retrying a transient TclError from Tcl
    interpreter init a couple of times before giving up."""
    last_error: tk.TclError | None = None
    for attempt in range(_RETRIES):
        try:
            return factory()
        except tk.TclError as exc:
            last_error = exc
            if attempt < _RETRIES - 1:
                time.sleep(_RETRY_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


def new_tk_root() -> tk.Tk:
    """Return a fresh Tk() root, retrying a transient init failure."""
    return retry_tcl_init(tk.Tk)
