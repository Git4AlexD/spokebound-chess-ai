"""Build a standalone Spokebound .exe under a fresh, timestamped
name, so every run leaves its own saved version behind instead of
overwriting whatever was built last.

    python package.py

Each run produces dist/Spokebound_<YYYYMMDD_HHMMSS>.exe — a
complete, self-contained build (Python and every asset included), built
the same way regardless of when or how many times it's run.

Nothing here ever deletes an older build: dist/ is meant to accumulate
one file per run as a standing archive of every version that's been
packaged, not just the latest.

If spokebound/secrets.json exists it's bundled too, so the build can
reach your relay server for online play. Anything bundled into an .exe
can be extracted from it — move secrets.json aside first if you're
building a copy to share and don't want your relay address inside it.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "spokebound" / "assets"
ICON = ASSETS / "icon.ico"
SECRETS = ROOT / "spokebound" / "secrets.json"
ENTRY = ROOT / "spokebound" / "__main__.py"
DIST = ROOT / "dist"
# Intermediate PyInstaller work files and the generated .spec both go
# here instead of the project root, so a run doesn't leave a stray
# Spokebound_<timestamp>.spec behind for every build.
WORK = ROOT / "build"


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller isn't installed — run: pip install pyinstaller")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"Spokebound_{timestamp}"
    sep = ";" if sys.platform == "win32" else ":"

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        name,
        "--onefile",
        "--windowed",
        "--icon",
        str(ICON),
        "--add-data",
        f"{ASSETS}{sep}spokebound/assets",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
        str(ENTRY),
    ]
    if SECRETS.is_file():
        command[-1:-1] = ["--add-data", f"{SECRETS}{sep}spokebound"]
        print("Including spokebound/secrets.json (online relay enabled).")
    else:
        print("No spokebound/secrets.json - building without a relay.")

    print(f"Building {name}.exe ...")
    subprocess.run(command, check=True, cwd=ROOT)
    print(f"Done: {DIST / (name + '.exe')}")


if __name__ == "__main__":
    main()
