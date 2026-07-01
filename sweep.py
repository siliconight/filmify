#!/usr/bin/env python3
"""
sweep.py — render one clip across a parameter's range so you can SEE what a
default does relative to off and heavy. The visual artifact for judging whether
a starting point is "close enough", and for showing testers.

Usage:
  python3 sweep.py yourclip.mp4                 # sweep the key parameters
  python3 sweep.py yourclip.mp4 --param halation # just one parameter
  python3 sweep.py yourclip.mp4 --frames         # also dump still frames (PNG)
  python3 sweep.py --check [clip]                 # is the DEFAULT look too strong?
  python3 sweep.py --validate [clip]             # full reference validation:
                                                 #   synthetic test set + before/
                                                 #   after contact sheet + a
                                                 #   version-tagged stats JSON

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


def _clip_frac(fm, path, high=True, center=False):
    """Fraction (0-1) of luma pixels pinned at the tv-range extreme — >=234 for
    blown highlights, <=17 for crushed shadows. Threshold the luma to an on/off
    mask, then the mask's average / 255 is the fraction. tv-range matters: film
    output tops out near 235 / 16, not 255 / 0. `center` crops to the middle 50%
    first, so the intentional vignette's corner falloff isn't misread as tonal
    clipping — it isolates what the CURVE does to the subject region."""
    cmp = "gte(val\\,234)" if high else "lte(val\\,17)"
    expr = f"if({cmp}\\,255\\,0)"
    pre = "crop=iw/2:ih/2," if center else ""
    chain = f"movie={fm.fpath(path)},{pre}lutyuv=y='{expr}',signalstats"
    out = fm.run([fm.FFPROBE, "-v", "error", "-f", "lavfi", "-i", chain,
                  "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
                  "-of", "csv=p=0"], capture_output=True, text=True)
    vals = []
    for s in out.stdout.splitlines():
        s = s.strip().strip(",")
        if s:
            try:
                vals.append(float(s))
            except ValueError:
                pass
    return (sum(vals) / len(vals) / 255.0) if vals else 0.0


def _find_font():
    """A usable TTF for contact-sheet labels across Win / mac / Linux. Returns a
    path or None — with None the sheet still renders, just without burnt-in
    labels (the console legend and row order still identify each reference)."""
    import platform
    sysname = platform.system()
    if sysname == "Windows":
        base = Path("C:/Windows/Fonts")
        cands = [base / "segoeui.ttf", base / "arial.ttf", base / "consola.ttf"]
    elif sysname == "Darwin":
        cands = [Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
                 Path("/Library/Fonts/Arial.ttf"),
                 Path("/System/Library/Fonts/Helvetica.ttc")]
    else:
        cands = [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                 Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")]
    for c in cands:
        if c.exists():
            return str(c)
    return None


def _dt_font(font):
    """Escape a font path for a drawtext fontfile= (the Windows drive colon must
    be backslash-escaped inside a filtergraph)."""
    return font.replace("\\", "/").replace(":", "\\:")


# Controlled references. Each isolates ONE property so a number means something:
# a gray card can't hide a colour cast, a skin swatch can't hide hue drift. These
# are measurement targets, not "realistic footage" — real clips are still the
# final word (pass one in to fold it into the sheet + stats).
# name -> (lavfi source, headline metric)
REFERENCES = {
    "gray_card":   ("color=0x808080", "cast"),
    "skin_light":  ("color=0xF0C8AF", "skin"),
    "skin_medium": ("color=0xC68664", "skin"),
    "skin_deep":   ("color=0x6E4A38", "skin"),
    "highlights":  ("color=0xffffff", "high"),
    "shadows":     ("color=0x141414", "low"),
    "night":       ("color=0x0e0e16,drawbox=x=112:y=56:w=32:h=32:color=0xfff2d8:t=fill", "low"),
}
_REF_SIZE = "s=256x144:r=24:d=1"


def _gen_reference(fm, src, dst):
    """Render a synthetic reference clip from a lavfi source string."""
    # size/rate/duration belong on the FIRST lavfi source; a trailing drawbox
    # (night) inherits them, so splice them in after the leading 'name=' head.
    head, _, tail = src.partition(",")
    joiner = ":" if "=" in head else ""
    full = f"{head}{joiner}{_REF_SIZE}" + (f",{tail}" if tail else "")
    subprocess.run([fm.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", full,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)],
                   check=True, timeout=60)


def _first_frame(fm, mp4, png):
    subprocess.run([fm.FFMPEG, "-y", "-v", "error", "-i", str(mp4),
                    "-frames:v", "1", str(png)], check=True, timeout=30)


def _contact_row(fm, name, before, after, dst, font):
    """One before|after row (scaled uniform), labelled if a font is available."""
    def side(idx, text):
        base = f"[{idx}]scale=240:-1"
        if font:
            base += (f",drawtext=fontfile='{_dt_font(font)}':text='{text}':"
                     "x=5:y=5:fontsize=13:fontcolor=white:box=1:boxcolor=black@0.5")
        return base
    fc = (f"{side(0, name + '  before')}[b];{side(1, 'after')}[a];"
          "[b][a]hstack=2[r]")
    try:
        subprocess.run([fm.FFMPEG, "-y", "-v", "error", "-i", str(before),
                        "-i", str(after), "-filter_complex", fc,
                        "-map", "[r]", str(dst)], check=True, timeout=30)
    except subprocess.CalledProcessError:
        # font/drawtext trouble -> plain unlabelled row
        fc2 = "[0]scale=240:-1[b];[1]scale=240:-1[a];[b][a]hstack=2[r]"
        subprocess.run([fm.FFMPEG, "-y", "-v", "error", "-i", str(before),
                        "-i", str(after), "-filter_complex", fc2,
                        "-map", "[r]", str(dst)], check=True, timeout=30)


def validate(fm, clip):
    """Reference validation for the clean default: render a controlled synthetic
    set (plus your clip if given), measure the properties that matter, print a
    PASS/WARN table, and leave two artifacts behind — a before/after contact
    sheet and a version-tagged stats JSON you can diff between releases."""
    import json
    import time
    outdir = ROOT / "references"
    outdir.mkdir(exist_ok=True)
    font = _find_font()
    a = base_args(fm, look="clean", grain=None, preview=1)

    items = list(REFERENCES.items())
    if clip and clip.exists():
        items.append(("your_clip", (None, "clip")))

    print("\nfilmify reference validation \u2014 clean default"
          f"  (filmify {fm.__version__})\n")
    warns = []

    def mark(cond):
        warns.append(not cond)
        return "PASS" if cond else "WARN"

    stats = {}
    rows = []
    for name, (src, kind) in items:
        srcpath = clip if src is None else outdir / f"{name}_src.mp4"
        if src is not None:
            _gen_reference(fm, src, srcpath)
        outpath = outdir / f"{name}_film.mp4"
        if not fm.render(srcpath, outpath, a).get("ok"):
            print(f"  {name:12s} render failed"); warns.append(True); continue
        mi = fm.measure_clip(srcpath) or (0, 128, 128)
        mo = fm.measure_clip(outpath) or (0, 128, 128)
        yi, ui, vi = mi
        yo, uo, vo = mo
        si, so = _satavg(fm, srcpath), _satavg(fm, outpath)
        hue = math.degrees(math.atan2(vo - 128, uo - 128) -
                           math.atan2(vi - 128, ui - 128))
        hue = (hue + 180) % 360 - 180
        chi, cho = _clip_frac(fm, srcpath, True, center=True) * 100, _clip_frac(fm, outpath, True, center=True) * 100
        cli, clo = _clip_frac(fm, srcpath, False, center=True) * 100, _clip_frac(fm, outpath, False, center=True) * 100
        ld = round(yo - yi, 1)
        cast = round(math.hypot(uo - 128, vo - 128), 1)
        sat_pct = round((so / si * 100) if si > 1e-6 else 100.0)
        # Store only the metrics that MEAN something for this reference kind, so
        # the stats file diffs cleanly between releases. (A skin swatch's
        # distance-from-neutral isn't a "cast"; a gray card's hue angle is noise.)
        stats[name] = {
            "luma_drift": ld,
            "cast": cast if kind in ("cast", "clip") else None,
            "hue_drift_deg": round(hue, 1) if kind == "skin" else None,
            "sat_kept_pct": sat_pct if kind in ("skin", "clip") else None,
            "clip_high_in_pct": round(chi, 1), "clip_high_out_pct": round(cho, 1),
            "clip_low_in_pct": round(cli, 1), "clip_low_out_pct": round(clo, 1),
        }

        # Headline metric by reference kind. Luma drift is only a PASS/WARN gate
        # where it's meaningful (a neutral card, a real clip); on a flat bright
        # patch or the highlight ref, large drift is the curve compressing on
        # purpose, so it's shown as context only.
        cells = []
        if kind == "cast":
            cells.append(f"cast {cast:.1f} [{mark(cast <= 6)}]")
            cells.append(f"luma {ld:+.0f} [{mark(abs(ld) <= 12)}]")
        elif kind == "skin":
            cells.append(f"hue {hue:+.1f}\u00b0 [{mark(abs(hue) <= 10)}]")
            cells.append(f"sat {sat_pct:.0f}% [{mark(78 <= sat_pct <= 110)}]")
            cells.append(f"luma {ld:+.0f}")
        elif kind == "high":
            cells.append(f"clip_hi {chi:.0f}%->{cho:.0f}% [{mark(cho - chi <= 1.0)}]")
            cells.append(f"luma {ld:+.0f}")
        elif kind == "low":
            cells.append(f"clip_lo {cli:.0f}%->{clo:.0f}% [{mark(clo - cli <= 2.0)}]")
            cells.append(f"luma {ld:+.0f}")
        else:  # user clip: general gentleness
            cells.append(f"cast {cast:.1f} [{mark(cast <= 8)}]")
            cells.append(f"sat {sat_pct:.0f}% [{mark(72 <= sat_pct <= 110)}]")
            cells.append(f"luma {ld:+.0f} [{mark(abs(ld) <= 12)}]")
        print(f"  {name:12s} " + "   ".join(cells))

        in_png, out_png = outdir / f"{name}_a.png", outdir / f"{name}_b.png"
        _first_frame(fm, srcpath, in_png)
        _first_frame(fm, outpath, out_png)
        row = outdir / f"row_{len(rows):02d}.png"
        _contact_row(fm, name, in_png, out_png, row, font)
        rows.append(row)
        for junk in (in_png, out_png):
            junk.unlink(missing_ok=True)
        if src is not None:
            srcpath.unlink(missing_ok=True)
        outpath.unlink(missing_ok=True)

    sheet = outdir / f"filmify_references_{fm.__version__}.png"
    if rows:
        inputs = []
        for r in rows:
            inputs += ["-i", str(r)]
        fc = "".join(f"[{i}]" for i in range(len(rows))) + f"vstack={len(rows)}[s]"
        subprocess.run([fm.FFMPEG, "-y", "-v", "error", *inputs,
                        "-filter_complex", fc, "-map", "[s]", str(sheet)],
                       check=True, timeout=60)
        for r in rows:
            r.unlink(missing_ok=True)

    statfile = outdir / f"filmify_reference_stats_{fm.__version__}.json"
    statfile.write_text(json.dumps(
        {"filmify_version": fm.__version__, "generated": time.strftime("%Y-%m-%d"),
         "look": "clean (default)", "references": stats}, indent=2) + "\n",
        encoding="utf-8")

    print(f"\n  contact sheet : {sheet.relative_to(ROOT)}")
    print(f"  release stats : {statfile.relative_to(ROOT)}  (diff this between versions)")
    if not font:
        print("  (no system font found — sheet rows are unlabelled; order matches the table above)")
    if any(warns):
        print("\nsome metrics WARN — inspect the sheet before shipping.")
        return 1
    print("\nall references pass \u2713  — the clean default holds up across the set.")
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
    ap.add_argument("--validate", action="store_true",
                    help="full reference validation of the clean default: "
                         "synthetic test set + before/after contact sheet + "
                         "version-tagged stats JSON (add a clip to include it)")
    a = ap.parse_args()

    fm = load()

    if a.validate:
        return validate(fm, a.clip)
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
