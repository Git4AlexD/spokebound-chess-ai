"""Short sound effects and menu music.

Every call site names *what happened* (``play_move``, ``play_capture``,
...), never a file path or a playback flag — this module owns the
mapping from a game event to a sound. On any platform without the
Windows APIs this uses, or if no audio device is available, every
function here is a silent no-op rather than a crash — sound is a
nice-to-have, never something gameplay should depend on.

Two separate playback paths, deliberately:

- One-shot effects go through :mod:`winsound`, which is simple but can
  only ever have one sound "in flight" through it at a time.
- The background music goes through the Windows MCI API instead (via
  ``ctypes``, still stdlib — no new dependency), as its own independent
  channel. It has to be a separate channel: with both on winsound, the
  next button click or piece move would silently cut the music off,
  since starting a new winsound playback kills whatever winsound was
  already playing. MCI has no such conflict with winsound or with
  itself, so the music keeps playing under every click, move and
  capture instead of getting interrupted by them.
- A silent track loops on a third channel (MCI again) for as long as
  the game is open — see :func:`keep_output_awake`.
"""

import contextlib

from spokebound.resources import package_dir

try:
    import winsound
except ImportError:  # not on Windows
    winsound = None

try:
    import ctypes

    _winmm = ctypes.windll.winmm
except (ImportError, AttributeError, OSError):  # not on Windows
    _winmm = None

ASSETS = package_dir() / "assets" / "sound"
_MUSIC_FILE = ASSETS / "menu_music.mp3"
_MUSIC_ALIAS = "spokebound_menu_music"
_KEEPALIVE_FILE = ASSETS / "silence.wav"
_KEEPALIVE_ALIAS = "spokebound_keepalive"

# Independent on purpose: the settings dialog offers two separate mute
# switches, so muting the music doesn't have to silence clicks too, and
# muting effects doesn't have to stop the music. Tests flip either off
# directly.
_effects_enabled = True
_music_enabled = True

# Whether the menu loop is (logically) running — lets play_menu_music be
# called on every return to a pre-game screen without restarting a loop
# that's already going. Only stop() clears it, so the loop only ever
# actually breaks where stop() is actually called: deployment starting.
_music_playing = False

_keepalive_playing = False


def _play(filename: str) -> None:
    if not _effects_enabled or winsound is None:
        return
    with contextlib.suppress(RuntimeError):  # no audio device, headless CI, etc.
        winsound.PlaySound(str(ASSETS / filename), winsound.SND_FILENAME | winsound.SND_ASYNC)


def _mci_command(command: str) -> None:
    """Issue an MCI command regardless of mute state — used for the
    handful of control commands (closing the channel, pausing it to
    mute) that have to work even while muted, since they're what makes
    muting actually silence something already playing."""
    if _winmm is None:
        return
    with contextlib.suppress(OSError):  # no audio device, headless CI, etc.
        _winmm.mciSendStringW(command, None, 0, None)


def play_move() -> None:
    """A piece moving to an empty square."""
    _play("move.wav")


def play_capture() -> None:
    """A piece moving onto and capturing an enemy piece."""
    _play("capture.wav")


def play_button_click() -> None:
    """A single mechanical-keyboard clack for a discrete UI action: a
    button (wired centrally in :func:`spokebound.ui.theme.make_button`),
    placing a piece during deployment, or dragging the AI difficulty
    slider to a new level."""
    _play("button_click.wav")


def play_unit_click() -> None:
    """A faster double clack — more clackety than an ordinary button —
    for accepting a spoke change on a piece, in the build screen or the
    in-game Piece Upgrade card."""
    _play("unit_click.wav")


def play_reject() -> None:
    """A gentle single-note buzz for a refused action — a spoke change
    with no points left to spend, a deploy click on the wrong square —
    in place of the raw, jarring system bell."""
    _play("reject.wav")


def play_win() -> None:
    """The game ending in a win (for the human side, in an AI game)."""
    _play("win.wav")


def play_loss() -> None:
    """The game ending in a loss (for the human side, in an AI game)."""
    _play("loss.wav")


def play_menu_music() -> None:
    """Start the pre-game loop, unless it's already running.

    Called every time a pre-game screen is (re)shown — the welcome
    menu, and starting a fresh game after one just finished — rather
    than just once, so nothing has to track "is the music already on".
    Idempotent because of that: with the loop already going, this is a
    no-op, so wandering into the tutorial and back, or any other
    pre-game navigation, never restarts or interrupts it. Only
    :func:`stop` (called once real play begins) ever breaks the loop.

    Opens and starts the MCI channel unconditionally — even while
    muted, immediately pausing it right after — rather than going
    through :func:`_mci`'s mute check: that would skip opening the
    channel at all while muted, leaving :func:`set_music_muted` trying
    to resume a channel that was never actually created once unmuted
    again (silently doing nothing — the bug this replaced).
    """
    global _music_playing
    if _music_playing:
        return
    _music_playing = True
    _mci_command(f'open "{_MUSIC_FILE}" type mpegvideo alias {_MUSIC_ALIAS}')
    _mci_command(f"play {_MUSIC_ALIAS} repeat")
    if not _music_enabled:
        _mci_command(f"pause {_MUSIC_ALIAS}")


def keep_output_awake() -> None:
    """Loop a silent track on its own MCI channel for as long as the
    game is open, so sound effects are never swallowed.

    Many audio chips power down after several seconds of silence and
    drop the first ~half a second of whatever plays next while they
    wake — longer than an entire click or move sound. The menu music
    keeps the output busy, but once a game starts (or the music is
    muted) nothing does, so every effect after a pause in play could
    vanish. A silent stream that never stops means the output never
    looks idle. Idempotent; never muted, since it's inaudible anyway.
    """
    global _keepalive_playing
    if _keepalive_playing:
        return
    _keepalive_playing = True
    _mci_command(f'open "{_KEEPALIVE_FILE}" type mpegvideo alias {_KEEPALIVE_ALIAS}')
    _mci_command(f"play {_KEEPALIVE_ALIAS} repeat")


def stop() -> None:
    """Stop whatever's currently playing — the menu music, once the
    placing-pieces phase begins."""
    global _music_playing
    _music_playing = False
    _mci_command(f"close {_MUSIC_ALIAS}")


def set_music_muted(muted: bool) -> None:
    """Mute or unmute the background music on its own.

    The music is already playing through its own MCI channel, so this
    also has to actively pause that channel (and unmuting resume it),
    not just stop *new* music from starting.
    """
    global _music_enabled
    _music_enabled = not muted
    if muted:
        _mci_command(f"pause {_MUSIC_ALIAS}")
    elif _music_playing:
        _mci_command(f"resume {_MUSIC_ALIAS}")


def is_music_muted() -> bool:
    """Return True if the background music is currently muted."""
    return not _music_enabled


def set_effects_muted(muted: bool) -> None:
    """Mute or unmute every one-shot sound effect on its own, leaving
    the music untouched. Effects are all short fire-and-forget clips,
    so there's nothing already "in flight" to silence — this is just
    the flag :func:`_play` checks before starting the next one."""
    global _effects_enabled
    _effects_enabled = not muted


def is_effects_muted() -> bool:
    """Return True if sound effects are currently muted."""
    return not _effects_enabled
