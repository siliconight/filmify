#!/usr/bin/env python3
"""
sweep.py — render one clip across a parameter's range so you can SEE what a
default does relative to off and heavy. The visual artifact for judging whether
a starting point is "close enough", and for showing testers.

Usage:
  python3 sweep.py yourclip.mp4                 # sweep the key parameters
  python3 sweep.py yourclip.mp4 --param halation # just one parameter
  python3 sweep.py yourclip.mp4 --frames         # also dump still frames (PNG)

Outputs a folder sweep_<param>/ with one short clip per value, named so they
sort in order (e.g. halation_00_off.mp4, halation_01_0.33_DEFAULT.mp4, ...).
Each filename marks where the current default sits, so a tester can say
"the one below default looks right".

This renders SHORT previews (a few seconds) for speed. It changes ONLY the
swept parameter; everything else stays at the standard look, so you're seeing
that one knob in isolation.
"""
import argparse
import importlib.util
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load():
    spec = importlib.util.spec_from_file_location("filmify", ROOT / "filmify.py")
    fm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fm)
    fm.FFMPEG = fm.find_tool("ffmpeg") or "ffmpeg"
    fm.FFPROBE = fm.find_tool("ffprobe") or "ffprobe"
    return fm


# Each entry: the values to sweep, and which one is the current default.
# Values chosen as off / low / DEFAULT / high / max so the default is framed
# by its neighbours — that's what makes a sweep substantiating rather than
# just a gallery.
SWEEPS = {
    "halation":      ([0.0, 0.18, 0.33, 0.55, 0.8], 0.33),
    "grain":         ([0, 3, 7, 12, 18], 7),
    "soften":        ([0.0, 0.3, 0.55, 0.9, 1.3], 0.55),
    "saturation":    ([1.0, 0.95, 0.88, 0.78, 0.65], 0.88),
    "chroma_soften": ([0.0, 0.6, 1.2, 2.0, 3.0], 1.2),
    "presence":      ([0.0, 0.15, 0.3, 0.5, 0.8], 0.3),
    "weave":         ([0.0, 0.5, 1.0, 1.5, 2.5], 0.0),
    "flicker":       ([0.0, 0.25, 0.5, 0.75, 1.0], 0.0),
    "corner_soften": ([0.0, 0.5, 1.0, 2.0, 3.0], 0.0),
}


def base_args(fm, **over):
    import argparse as _a
    d = dict(look="standard", gauge="35mm", ratio=None, grain=7,
             halation=None, soften=None, saturation=None, chroma_soften=None,
             plate_opacity=None, weave=0, leak=0, flare=0, bw=False,
             conform=False, no_curve=False, no_vignette=False, lut=None,
             grain_plate=None, input_log=None, depth=8, codec="h264", crf=18,
             preview=4, dry_run=False, compare=False, presence=None,
             flicker=0, corner_soften=0, age=0, no_protect_skin=False,
             print_stock=None, no_tonemap=False, no_hwaccel=True,
             _loglut=None, _match=None, look_file=None, save_look=None,
             match=False, style=None)
    d.update(over)
    return _a.Namespace(**d)


def _satavg(fm, path):
    """Mean per-pixel saturation (ffmpeg signalstats SATAVG). Unlike the average
    of U/V — which measures net colour CAST and cancels out on a balanced but
    colourful frame — this measures how colourful the pixels actually are, which
    is what 'did the look desaturate' needs."""
    cmd = [fm.FFPROBE, "-v", "error", "-f", "lavfi",
           "-i", f"movie={fm.fpath(path)},fps=1,signalstats",
           "-show_entries", "frame_tags=lavfi.signalstats.SATAVG",
           "-of", "csv=p=0"]
    out = fm.run(cmd, capture_output=True, text=True)
    vals = []
    for line in out.stdout.splitlines():
        s = line.strip().strip(",")
        if s:
            try:
                vals.append(float(s))
            except ValueError:
                pass
    return sum(vals) / len(vals) if vals else 0.0


def _measure_effect(fm, clip):
    """Render `clip` at the DEFAULT (clean) look with NO slider overrides — pure
    preset — then return input vs output (Y, U, V, SATAVG) so we can quantify how
    far the default moved the image."""
    args = base_args(fm, look="clean", grain=None)  # grain=None -> use look's own
    out = ROOT / "_check_out.mp4"
    res = fm.render(clip, out, args)
    if not res.get("ok"):
        return None
    a = fm.measure_clip(clip)
    b = fm.measure_clip(out)
    if not a or not b:
        out.unlink(missing_ok=True)
        return None
    sa = _satavg(fm, clip)
    sb = _satavg(fm, out)
    out.unlink(missing_ok=True)
    return (a[0], a[1], a[2], sa), (b[0], b[1], b[2], sb)


def check_default(fm, clip):
    """'Too much film effect' guard for the clean default. A premium default
    barely moves the image: little luma drift, no global colour wash, and it
    keeps almost all of the original saturation. Runs on a supplied clip, or on
    synthetic references (neutral gray + colour bars) when none is given, so it
    works with no footage on hand. Returns non-zero if any metric warns."""
    targets = []
    if clip and clip.exists():
        targets.append(("your clip", clip))
    else:
        gray = ROOT / "_check_gray.mp4"
        bars = ROOT / "_check_bars.mp4"
        subprocess.run([fm.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                        "color=0x808080:s=320x180:r=24:d=1", "-c:v", "libx264",
                        "-preset", "veryfast", str(gray)], check=True, timeout=60)
        subprocess.run([fm.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                        "smptebars=s=320x180:r=24:d=1", "-c:v", "libx264",
                        "-preset", "veryfast", str(bars)], check=True, timeout=60)
        targets += [("neutral gray", gray), ("colour bars", bars)]

    print("\nclean-default gentleness check  (a good default barely moves the image)\n")
    warns = []

    def mark(cond):
        warns.append(not cond)
        return "PASS" if cond else "WARN"

    for name, path in targets:
        m = _measure_effect(fm, path)
        if not m:
            print(f"  [{name}] render/measure failed"); warns.append(True); continue
        (yi, ui, vi, sati), (yo, uo, vo, sato) = m
        dY = yo - yi
        cast = math.hypot(uo - ui, vo - vi)
        sat_ratio = (sato / sati) if sati > 1e-6 else 1.0
        print(f"  [{name}]")
        print(f"    [{mark(abs(dY) <= 12)}] luma drift          dY = {dY:+.1f} / 255   (want |dY| <= 12)")
        print(f"    [{mark(cast <= 6)}] global colour wash   {cast:4.1f}          (want <= 6)")
        if sati > 8:  # retention is only meaningful on a genuinely coloured source
            print(f"    [{mark(0.78 <= sat_ratio <= 1.10)}] saturation kept     {sat_ratio * 100:3.0f}%          (want 78-110%)")
        else:
            print(f"    [ -- ] saturation kept     n/a (near-neutral source)")
        print()
        if path.name.startswith("_check_"):
            path.unlink(missing_ok=True)

    if any(warns):
        print("some metrics WARN — the clean default may be too strong; dial it back.")
        return 1
    print("all gentle \u2713  — the clean default reads as finishing polish, not a filter.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", type=Path, nargs="?")
    ap.add_argument("--param", help="sweep just one parameter")
    ap.add_argument("--frames", action="store_true",
                    help="also export a still PNG per value")
    ap.add_argument("--check", action="store_true",
                    help="measure whether the DEFAULT (clean) look stays gentle "
                         "on a clip (or synthetic refs if no clip is given)")
    a = ap.parse_args()

    fm = load()

    if a.check:
        return check_default(fm, a.clip)

    if a.clip is None:
        print("give a clip to sweep, or use --check")
        return 1
    if not a.clip.exists():
        print(f"clip not found: {a.clip}")
        return 1

    params = [a.param] if a.param else list(SWEEPS)
    for p in params:
        if p not in SWEEPS:
            print(f"unknown parameter '{p}'. Options: {', '.join(SWEEPS)}")
            continue
        values, default = SWEEPS[p]
        outdir = ROOT / f"sweep_{p}"
        outdir.mkdir(exist_ok=True)
        print(f"\nsweeping {p}  (default = {default})  ->  {outdir.name}/")
        for i, v in enumerate(values):
            tag = "off" if v in (0, 0.0) else str(v)
            mark = "_DEFAULT" if v == default else ""
            stem = f"{p}_{i:02d}_{tag}{mark}"
            out = outdir / (stem + ".mp4")
            args = base_args(fm, **{p: v})
            try:
                res = fm.render(a.clip, out, args)
                ok = res.get("ok")
            except Exception as exc:  # noqa: BLE001
                ok = False
                print(f"  [err] {stem}: {exc}")
            if ok:
                print(f"  [ok ] {stem}")
                if a.frames:
                    png = outdir / (stem + ".png")
                    subprocess.run([fm.FFMPEG, "-y", "-v", "error", "-i",
                                    str(out), "-frames:v", "1", str(png)])
        print(f"  open {outdir.name}/ and scrub through in order; the file "
              f"marked _DEFAULT is the current starting point.")
    print("\nTip: put the off / DEFAULT / heavy versions side by side in front "
          "of a tester and ask which reads as film. That's the real test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
