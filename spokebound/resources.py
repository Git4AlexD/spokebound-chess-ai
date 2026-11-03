"""Where to find files bundled with the app — sound effects, tutorial
screenshots — whether running from source or packaged as a single
PyInstaller executable.

A plain source run resolves these relative to the ``spokebound/``
package itself, as always. A packaged (frozen) build is different:
PyInstaller zips pure-Python modules into an archive at build time, so
a bundled module's own ``__file__`` doesn't reliably support ``.parent``
navigation to a real file on disk — this instead resolves relative to
``sys._MEIPASS``, the real directory PyInstaller actually extracts
bundled data files into at runtime (matching how the build places them
there — see ``spokebound.spec``).
"""

import sys
from pathlib import Path


def package_dir() -> Path:
    """Return the directory that holds ``assets/`` and friends — the
    ``spokebound/`` package's own directory, whether that's really on
    disk (a source run) or inside a packaged build's extraction
    directory."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "spokebound"
    return Path(__file__).resolve().parent
