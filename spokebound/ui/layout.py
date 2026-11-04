"""Helpers for scaling a screen's content to fit the real window, instead
of letting it overflow or scroll."""

import contextlib
import tkinter as tk
from collections.abc import Callable


def window_size(widget: tk.Misc) -> tuple[int, int]:
    """Return the real, already-resolved size of the window ``widget``
    is shown in."""
    root = widget.winfo_toplevel()
    root.update_idletasks()
    return root.winfo_width(), root.winfo_height()


def freeze_height(widget: tk.Misc) -> None:
    """Fix ``widget``'s current natural height as its permanent size.

    Call this once, after everything that's ever going to be inside
    ``widget`` has already been built and packed (worst case included
    — a Done button shown, a spend prompt's text filled in — so the
    frozen height is the largest it'll ever need). Without it, a frame
    left to size itself from its children (needed up to that point, so
    something measuring it mid-build — fit_height's own scale solve —
    sees its honest, content-driven height) stays exposed to exactly
    that for the rest of its life: any later, perfectly ordinary
    change to a child already inside it — a button's own visibility
    toggling, a canvas that grows to fit new text — quietly resizes
    the whole frame right along with it, long after the scale meant to
    account for all of that was already chosen.
    """
    widget.update_idletasks()
    widget.configure(height=widget.winfo_reqheight())
    widget.pack_propagate(False)


def fit_height(
    container: tk.Misc,
    build: Callable[[float], tk.Widget],
    available_height: int,
    min_scale: float = 0.55,
    probe_scale: float = 0.7,
) -> tk.Widget:
    """Build content sized to fit ``available_height``, given a
    ``build(scale)`` that returns a freshly built, not-yet-packed widget
    (1.0 = full size).

    Required height isn't simply proportional to scale — only some parts
    (piece sizes, spacing) shrink, while text stays a legible fixed size
    — so a single guess tends to undershoot. This measures two builds (at
    1.0 and at ``probe_scale``) and solves for the scale that exactly
    hits ``available_height`` on that line, rather than iterating blind.

    That line is only ever exact when every part of the build truly
    scales in proportion, though — a component that barely moves with
    scale at all (a ttk button's own natural size, a clamped minimum
    somewhere) bends the real height-vs-scale curve just enough that
    the solved scale can still land a little past ``available_height``.
    Rather than let that overshoot reach the caller, this always
    measures whatever it's about to return and shrinks further, in
    small steps, until it actually fits (or ``min_scale`` is reached) —
    the one guarantee this function exists to make.
    """
    content = build(1.0)
    content.pack(fill=tk.BOTH, expand=True)
    container.update_idletasks()
    height_at_full = content.winfo_reqheight()
    if height_at_full <= available_height:
        return content
    content.destroy()

    probe = build(probe_scale)
    probe.pack(fill=tk.BOTH, expand=True)
    container.update_idletasks()
    height_at_probe = probe.winfo_reqheight()

    span = 1.0 - probe_scale
    slope = (height_at_full - height_at_probe) / span if span else 0
    if slope <= 0:
        scale = min_scale
    else:
        fixed = height_at_full - slope
        scale = (available_height - fixed) / slope
    scale = max(min_scale, min(1.0, scale))

    if abs(scale - probe_scale) < 0.03 and height_at_probe <= available_height:
        content, height = probe, height_at_probe
    else:
        probe.destroy()
        content = build(scale)
        content.pack(fill=tk.BOTH, expand=True)
        container.update_idletasks()
        height = content.winfo_reqheight()

    while height > available_height and scale > min_scale:
        scale = max(min_scale, scale - 0.03)
        content.destroy()
        content = build(scale)
        content.pack(fill=tk.BOTH, expand=True)
        container.update_idletasks()
        height = content.winfo_reqheight()
    return content


def fit_to_window(
    container: tk.Misc,
    build: Callable[[float], tk.Widget],
    available_width: int,
    available_height: int,
    min_scale: float = 0.55,
    max_scale: float = 1.0,
    probe_scale: float = 0.7,
) -> tk.Widget:
    """Like :func:`fit_height`, but sized against both dimensions of an
    ``available_width`` x ``available_height`` box, and — when
    ``max_scale`` allows it — free to grow past 1.0 to fill extra room
    on a big window, not just shrink to fit a small one. Screens whose
    content is otherwise a fixed size regardless of the window (see the
    note on BuildScreen/CustomFleetScreen) end up a small island in a
    lot of empty background on a large one without this.

    Solves each dimension the same way ``fit_height`` solves height —
    two measured builds (1.0 and ``probe_scale``), a scale that exactly
    hits the budget on that line — then uses whichever of the two
    scales is more constraining, so growing to fill height can never
    overflow width or vice versa.
    """

    def measure(scale: float) -> tuple[int, int]:
        content = build(scale)
        content.pack(fill=tk.BOTH, expand=True)
        container.update_idletasks()
        size = (content.winfo_reqwidth(), content.winfo_reqheight())
        content.destroy()
        return size

    def solve(full: int, probe: int, budget: int) -> float:
        span = 1.0 - probe_scale
        slope = (full - probe) / span if span else 0
        if slope <= 0:
            return max_scale if full <= budget else min_scale
        fixed = full - slope
        return (budget - fixed) / slope

    width_at_full, height_at_full = measure(1.0)
    if max_scale <= 1.0 and width_at_full <= available_width and height_at_full <= available_height:
        content = build(1.0)
        content.pack(fill=tk.BOTH, expand=True)
        return content

    width_at_probe, height_at_probe = measure(probe_scale)
    scale_w = solve(width_at_full, width_at_probe, available_width)
    scale_h = solve(height_at_full, height_at_probe, available_height)
    scale = max(min_scale, min(max_scale, scale_w, scale_h))

    content = build(scale)
    content.pack(fill=tk.BOTH, expand=True)
    return content


def window_scale(
    widget: tk.Misc,
    base_width: int = 1280,
    base_height: int = 720,
    min_scale: float = 1.0,
    max_scale: float = 2.2,
) -> float:
    """Return how far past its own designed-at-``base_width`` x
    ``base_height`` size a screen's content should grow to suit the
    real window it's actually in — 1.0 (never smaller; these screens
    are already sized to work at that baseline) up to ``max_scale`` on
    a bigger one. For a small, mostly-static screen (a single centred
    dialog, a handover prompt) where measuring real content the way
    :func:`fit_to_window` does would be overkill — there's nothing here
    that can overflow, just a fixed design that would otherwise sit
    tiny and lost on a big window.
    """
    width, height = window_size(widget)
    if width <= 1 or height <= 1:
        return min_scale
    return max(min_scale, min(max_scale, min(width / base_width, height / base_height)))


def watch_resize(widget: tk.Misc, on_resize: Callable[[], None], debounce_ms: int = 150) -> None:
    """Call ``on_resize`` whenever the window ``widget`` lives in actually
    changes size, so a fit-to-window screen stays fitted after the user
    resizes or un-maximizes the window, not just at the moment it was
    first built.

    Debounced: a drag-resize fires ``<Configure>`` on every intermediate
    pixel, so this waits for the size to sit still for ``debounce_ms``
    before rebuilding, and skips rebuilding if the settled size turns out
    unchanged (``<Configure>`` also fires for reasons other than an
    actual resize). Stops watching on its own, the next time the window
    configures, once ``widget`` has been destroyed — a screen that's been
    replaced doesn't need to unbind this itself.
    """
    root = widget.winfo_toplevel()
    state = {"job": None, "id": None, "size": (root.winfo_width(), root.winfo_height())}

    def fire() -> None:
        state["job"] = None
        if not widget.winfo_exists():
            return
        size = (root.winfo_width(), root.winfo_height())
        if size == state["size"]:
            return
        state["size"] = size
        on_resize()

    def handle(event: tk.Event) -> None:
        if event.widget is not root:
            return
        if not widget.winfo_exists():
            if state["id"] is not None:
                with contextlib.suppress(tk.TclError):
                    root.unbind("<Configure>", state["id"])
            return
        if state["job"] is not None:
            root.after_cancel(state["job"])
        state["job"] = root.after(debounce_ms, fire)

    state["id"] = root.bind("<Configure>", handle, add="+")
