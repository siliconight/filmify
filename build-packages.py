#!/usr/bin/env python3
"""
build-packages.py -- assemble the clean, user-facing filmify downloads.

Produces two zips in dist/:
  filmify-mac.zip      → unzips to a folder showing just "Start filmify"
  filmify-windows.zip  → unzips to a folder showing just "Start filmify"

Each hides all the machinery in an "app-files" subfolder, so a non-technical
person sees one obvious thing to double-click. Run this after every release;
it reads the current version from filmify.py.

    python3 build-packages.py
"""

import re
import shutil
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

VERSION = re.search(r'__version__ = "([^"]+)"',
                    (ROOT / "filmify.py").read_text())[1]

# Files the engine needs, hidden inside app-files/
SHARED = ["filmify.py"]
MAC_HIDDEN = ["filmify-launch.sh", "make-mac-app.command",
              "filmify_icon_1024.png"]
WIN_HIDDEN = ["filmify-quiet.vbs", "Make filmify app.bat",
              "filmify.ico", "filmify_icon_1024.png"]

MAC_README = """filmify -- the feel of film, without the film camera.

TO START:
  Double-click  "Start filmify"

  The very first time, macOS may say it's from an unidentified developer.
  If so: right-click "Start filmify" -> Open -> Open. (Just once -- after
  that a normal double-click works.)

That's it. filmify opens in your web browser. Drop in a video, pick a look,
and render. Your finished file has a "Show in folder" button so you always
know where it went.

Everything else lives in the "app-files" folder -- you can ignore it.
Keep this whole folder together; don't move "Start filmify" out on its own.
"""

WIN_README = """filmify -- the feel of film, without the film camera.

TO START:
  Double-click  "Start filmify"

  The very first time, Windows may show "Windows protected your PC".
  If so: click "More info" -> "Run anyway". (Just once.)

That's it. filmify opens in your web browser. Drop in a video, pick a look,
and render. Your finished file has a "Show in folder" button so you always
know where it went.

Everything else lives in the "app-files" folder -- you can ignore it.
Keep this whole folder together; don't move "Start filmify" out on its own.
"""

# The one visible launcher. It just calls into app-files/, so the top level
# stays clean. Mac version:
MAC_START = """#!/bin/bash
# Start filmify -- double-click me.
cd "$(dirname "$0")/app-files" || exit 1
exec /bin/bash ./filmify-launch.sh
"""

# Windows version (CRLF). Uses 'call' so START-HERE runs in this same console
# window (which stays open as the panel's signal). Pure ASCII -- a stray
# non-ASCII byte in a .bat can break parsing on some Windows codepages.
WIN_START = """@echo off
rem Start filmify -- double-click me.
cd /d "%~dp0app-files"
call "START-HERE-WINDOWS.bat" --quiet
"""


def reset_dist():
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()


def build_mac():
    stage = DIST / "filmify-mac"
    app = stage / "app-files"
    app.mkdir(parents=True)
    for f in SHARED + MAC_HIDDEN:
        shutil.copy2(ROOT / f, app / f)
    # the visible launcher
    start = stage / "Start filmify.command"
    start.write_text(MAC_START)
    start.chmod(start.stat().st_mode | stat.S_IEXEC | 0o755)
    # the launch script inside needs +x too
    (app / "filmify-launch.sh").chmod(0o755)
    (app / "make-mac-app.command").chmod(0o755)
    (stage / "Read Me.txt").write_text(MAC_README)
    _zip(stage, DIST / "filmify-mac.zip")


def build_windows():
    stage = DIST / "filmify-windows"
    app = stage / "app-files"
    app.mkdir(parents=True)
    for f in SHARED + WIN_HIDDEN:
        shutil.copy2(ROOT / f, app / f)
    # the Windows launcher engine lives in app-files too
    shutil.copy2(ROOT / "START-HERE-WINDOWS.bat",
                 app / "START-HERE-WINDOWS.bat")
    # visible launcher (CRLF)
    (stage / "Start filmify.bat").write_bytes(
        WIN_START.replace("\n", "\r\n").encode("utf-8"))
    (stage / "Read Me.txt").write_bytes(
        WIN_README.replace("\n", "\r\n").encode("utf-8"))
    _zip(stage, DIST / "filmify-windows.zip")


def _zip(folder: Path, out: Path):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                # preserve the executable bit for .command / .sh on Mac
                zi = zipfile.ZipInfo(str(p.relative_to(folder.parent)))
                zi.compress_type = zipfile.ZIP_DEFLATED
                mode = p.stat().st_mode
                zi.external_attr = (mode & 0xFFFF) << 16
                z.writestr(zi, p.read_bytes())
    print(f"  {out.name}")


def main():
    reset_dist()
    print(f"building filmify {VERSION} packages:")
    build_mac()
    build_windows()
    print(f"done -> {DIST}")


def clean():
    """Remove generated artifacts from the working tree, leaving source and
    any test footage untouched. Targets exactly the things .gitignore already
    declares disposable (plus the two stale root release zips), so a dev tree
    goes back to a clean, shippable state without touching your clips."""
    removed = []
    # directories
    for d in [DIST, ROOT / "__pycache__", ROOT / "references"] + list(ROOT.glob("sweep_*")):
        if d.is_dir():
            shutil.rmtree(d)
            removed.append(d.name + "/")
    # files: stale root release zips, logs, reports, smoke temp files
    patterns = ["filmify-mac.zip", "filmify-windows.zip",
                "*.log", "*_report.html", "_smoke_*", "filmify_logo.png"]
    for pat in patterns:
        for p in ROOT.glob(pat):
            if p.is_file():
                p.unlink()
                removed.append(p.name)
    if removed:
        print("cleaned:", ", ".join(sorted(removed)))
    else:
        print("already clean")
    print("(test footage — *.mp4/*.mov — left untouched)")


if __name__ == "__main__":
    import sys
    if "--clean" in sys.argv[1:]:
        clean()
    else:
        main()
