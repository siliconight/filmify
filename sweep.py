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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", type=Path)
    ap.add_argument("--param", help="sweep just one parameter")
    ap.add_argument("--frames", action="store_true",
                    help="also export a still PNG per value")
    a = ap.parse_args()

    if not a.clip.exists():
        print(f"clip not found: {a.clip}")
        return 1

    fm = load()
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
