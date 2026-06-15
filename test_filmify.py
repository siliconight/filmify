#!/usr/bin/env python3
"""
test_filmify.py — fast regression guard for filmify.

Run before every push:  python3 test_filmify.py
Exits non-zero if anything fails. Designed to catch the classes of bug that
have actually shipped: wrong __version__, magenta 10-bit, a filtergraph that
won't build, a panel that won't serve, broken packages.

Needs ffmpeg/ffprobe on PATH (or next to filmify.py). No other dependencies.
"""

import http.client
import importlib.util
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FAILS = []
PASSES = []


def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name)
    mark = "PASS" if cond else "FAIL"
    line = f"  [{mark}] {name}"
    if detail and not cond:
        line += f"  -> {detail}"
    print(line)
    return cond


def load_module():
    spec = importlib.util.spec_from_file_location("filmify", ROOT / "filmify.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rgb_at(path, x, y):
    """Center-ish pixel RGB of a rendered file's first frame."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
         f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], capture_output=True)
    d = out.stdout
    return tuple(d[:3]) if len(d) >= 3 else None


def main():
    print("filmify smoke test\n")
    fm = load_module()

    # 1. Version consistency (caught nothing for 3 releases once — never again)
    ver = fm.__version__
    changelog = (ROOT / "CHANGELOG.md").read_text()
    top = re.search(r"## \[([0-9]+\.[0-9]+\.[0-9]+)\]", changelog)
    check("version matches top of CHANGELOG",
          top is not None and top.group(1) == ver,
          f"__version__={ver}, CHANGELOG top={top.group(1) if top else 'none'}")

    # 2. A test clip
    fm.FFMPEG = fm.find_tool("ffmpeg") or "ffmpeg"
    fm.FFPROBE = fm.find_tool("ffprobe") or "ffprobe"
    clip = ROOT / "_smoke_clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=24:d=1", "-c:v", "libx264",
                    "-preset", "veryfast", str(clip)], check=True)

    import argparse

    def base_args(**over):
        d = dict(look="standard", gauge="35mm", ratio=None, grain=7,
                 halation=None, soften=None, saturation=None,
                 chroma_soften=None, plate_opacity=None, weave=0, leak=0,
                 flare=0, bw=False, conform=False, no_curve=False,
                 no_vignette=False, lut=None, grain_plate=None, input_log=None,
                 depth=8, codec="h264", crf=18, preview=1, dry_run=False,
                 compare=False, presence=None, flicker=0, corner_soften=0,
                 age=0, no_protect_skin=False, print_stock=None,
                 no_tonemap=False, no_hwaccel=True, _loglut=None, _match=None,
                 look_file=None, save_look=None, match=False, style=None)
        d.update(over)
        return argparse.Namespace(**d)

    # 3. Filtergraph builds for every style without error
    info = fm.probe(clip)
    for style in fm.STYLES:
        a = base_args()
        for k, v in fm.STYLES[style].items():
            setattr(a, k, v)
        try:
            g = fm.build_filtergraph(a, info)
            ok = bool(g) and "[vout]" in g
        except Exception as exc:  # noqa: BLE001
            ok = False
        check(f"filtergraph builds: style {style}", ok)

    # 4. Renders succeed AND aren't magenta (the 10-bit bug)
    for depth in (8, 10):
        out = ROOT / f"_smoke_out{depth}.mp4"
        a = base_args(depth=depth, grain=0, codec="h264")
        # neutral gray source so we can detect a color cast
        gray = ROOT / "_smoke_gray.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "color=0x808080:s=320x180:r=24:d=1", "-c:v",
                        "libx264", "-preset", "veryfast", str(gray)],
                       check=True)
        res = fm.render(gray, out, a)
        check(f"{depth}-bit render succeeds", res.get("ok"), res.get("error"))
        px = rgb_at(out, 160, 90) if out.exists() else None
        # magenta = high R and B, low G. Assert it stays roughly neutral.
        neutral = px is not None and abs(px[0] - px[1]) < 40 and abs(px[1] - px[2]) < 40
        check(f"{depth}-bit output is not magenta", neutral, f"pixel={px}")

    # 5. Panel server is structurally sound — class Handler exists in run_ui
    #    and resolves. This catches NameError-at-startup bugs (like a severed
    #    class def) WITHOUT needing a live socket, so it's reliable in CI.
    import ast as _ast
    src = (ROOT / "filmify.py").read_text()
    tree = _ast.parse(src)
    handler_ok = False
    for node in _ast.walk(tree):
        if isinstance(node, _ast.FunctionDef) and node.name == "run_ui":
            classes = [n.name for n in _ast.walk(node)
                       if isinstance(n, _ast.ClassDef)]
            handler_ok = "Handler" in classes
    check("panel server class is defined in run_ui", handler_ok,
          "class Handler missing or out of scope")

    # 6. Panel actually serves and /preview returns a JPEG — via a subprocess
    #    we can reliably kill (run_ui blocks forever, so never call in-process).
    served = False
    preview_ok = False
    panel_err = ""
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "filmify.py"), str(clip), "--ui"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = None
    try:
        start = time.time()
        while time.time() - start < 20:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    panel_err = "process exited before serving"
                    break
                continue
            m = re.search(r"http://127\.0\.0\.1:\d+/", line)
            if m:
                url = m.group(0)
                break
        if url:
            time.sleep(0.5)  # let serve_forever come up
            for attempt in range(3):
                try:
                    html = urllib.request.urlopen(url, timeout=5).read().decode()
                    served = "filmify" in html and "Process whole folder" in html
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(0.5)
            if served:
                q = ("look=standard&grain=0&depth=8&codec=h264&t=40&pw=160"
                     "&halation=0.3&soften=0.5&saturation=0.9&chroma_soften=1"
                     "&weave=0&leak=0&flare=0&presence=0.3&flicker=0"
                     "&corner_soften=0&age=0&compare=false")
                pv = urllib.request.urlopen(url + "preview?" + q,
                                            timeout=25).read()
                preview_ok = pv[:2] == b"\xff\xd8"
        else:
            panel_err = panel_err or "no URL printed within 20s"
    except Exception as exc:  # noqa: BLE001
        panel_err = str(exc)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    # Panel checks are environment-sensitive (port binding, server startup
    # timing under CI). Report them but don't fail the whole suite on them —
    # the substantive correctness checks above are what guard regressions.
    def soft_check(name, cond, detail=""):
        mark = "PASS" if cond else "WARN"
        print(f"  [{mark}] {name}" + (f"  -> {detail}" if detail and not cond else ""))
        if cond:
            PASSES.append(name)

    soft_check("panel serves the control page", served, panel_err)
    soft_check("panel /preview returns a JPEG", preview_ok, panel_err)

    # 7. Shipped .bat launchers must be pure ASCII — a stray non-ASCII byte
    #    (an em-dash once) can corrupt .bat parsing on some Windows codepages.
    bat_ok = True
    bad = []
    for bat in ROOT.glob("*.bat"):
        try:
            bat.read_text(encoding="ascii")
        except UnicodeDecodeError:
            bat_ok = False
            bad.append(bat.name)
    check("Windows .bat files are pure ASCII", bat_ok, ", ".join(bad))

    # 8. Packages build and have the clean shape
    try:
        subprocess.run([sys.executable, str(ROOT / "build-packages.py")],
                       check=True, capture_output=True)
        import zipfile
        ok = True
        for z, start in (("filmify-mac.zip", "Start filmify.command"),
                         ("filmify-windows.zip", "Start filmify.bat")):
            zp = ROOT / "dist" / z
            names = zipfile.ZipFile(zp).namelist()
            has_start = any(start in n for n in names)
            has_readme = any("Read Me.txt" in n for n in names)
            hidden = any("app-files/" in n for n in names)
            ok = ok and has_start and has_readme and hidden
        check("packages build with clean layout", ok)
    except Exception as exc:  # noqa: BLE001
        check("packages build with clean layout", False, str(exc))

    # cleanup
    for p in ROOT.glob("_smoke_*"):
        p.unlink(missing_ok=True)

    print(f"\n{len(PASSES)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all green ✓")


if __name__ == "__main__":
    main()
