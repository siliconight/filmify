#!/usr/bin/env python3
"""
filmify — make digital video look like physical film.

For indie filmmakers: the feel of cinema without owning a film camera.
A single-file FFmpeg pipeline. No dependencies beyond ffmpeg/ffprobe on PATH.

The processing chain (in order — order matters):

  1. Temporal conform   24 fps + simulated 180° shutter (frame blending),
                        so motion blur reads like a film camera, not a phone.
  2. Softening          Gentle de-sharpening. Digital is too crisp; film
                        lenses + the film plane itself are slightly soft.
  3. Gate weave         Optional slow frame drift, like film transport
                        through a projector gate.
  4. B&W mode           Optional panchromatic-weighted mono conversion.
  5. Filmic tone curve  Per-preset contrast CHARACTER: each preset puts its
                        contrast in a different tonal region, the way stocks
                        differ. All share the protected-highlight shoulder —
                        whites roll off and never reach 100%.
  6. Film-stock LUT     Optional .cube 3D LUT (Kodak/Fuji print emulations,
                        etc.). When a LUT is supplied it owns the color
                        character, so the built-in split tone is skipped.
  7. Color discipline   Mild desaturation, warm-highlight / cool-shadow
                        split tone, and chroma softening — film's color
                        layers resolve softer than its luminance.
  8. Halation           Bright areas isolated, blurred wide, tinted
                        red-orange (neutral in B&W), screened back over.
  9. Grain              Real scanned grain plate (--grain-plate) overlaid
                        and looped, or synthesized temporal luma-weighted
                        grain as the fallback. Heavier in B&W.
 10. Vignette           Very slight corner falloff, like a real lens.

Usage:
  python filmify.py input.mp4
  python filmify.py input.mp4 --look heavy --conform
  python filmify.py clip.mov --lut kodak_2383.cube --grain-plate 35mm_grain.mp4
  python filmify.py clip.mov --preview            # first 5 s, fast encode
  python filmify.py shoot_day1/                   # batch: whole folder
  python filmify.py clip.mov --dry-run            # print the ffmpeg command

This tool finishes the look; it can't recover clipped whites. Expose to
protect highlights (or shoot log/flat), light intentionally, and shoot
24fps/180° in camera when you can.
"""

import argparse
import base64
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

__version__ = "0.29.1"

# Named recipes: one word that expands to a flag set. Everything remains
# individually overridable — explicit CLI flags and look files win.
STYLES = {
    "documentary": {"look": "heavy", "gauge": "16mm"},
    "noir":        {"look": "heavy", "bw": True},
    "anamorphic":  {"look": "standard", "ratio": 2.39, "flare": 0.35, "depth": 10},
    "home-movie":  {"look": "heavy", "leak": 0.3, "weave": 2.0,
                    "flicker": 0.3, "corner_soften": 0.7},
    "epic":        {"look": "subtle", "gauge": "70mm", "ratio": 2.2,
                    "depth": 10, "codec": "prores"},
    "blockbuster": {"look": "standard", "print_stock": "neutral",
                    "ratio": 2.39, "depth": 10},
    "western":     {"look": "heavy", "print_stock": "warm", "ratio": 2.39},
    "horror":      {"look": "heavy", "print_stock": "cool",
                    "saturation": 0.78},
    "wedding":     {"look": "subtle", "print_stock": "warm", "soften": 0.7},
    "super8":      {"look": "heavy", "gauge": "16mm", "grain": 16,
                    "weave": 2.5, "leak": 0.4, "ratio": 1.33,
                    "flicker": 0.5, "age": 0.45, "corner_soften": 1.0},
    "newsreel":    {"look": "heavy", "bw": True, "gauge": "16mm",
                    "weave": 1.5, "ratio": 1.33,
                    "flicker": 0.5, "age": 0.55},
}


def apply_style(args, ap) -> None:
    """Expand a named style. Only fills settings still at their parser
    defaults, so explicit flags and look-file values keep precedence."""
    for k, v in STYLES[args.style].items():
        if getattr(args, k) == ap.get_default(k):
            setattr(args, k, v)

LOG_PRESETS = ("slog3", "vlog", "cineon")


def _slog3_to_linear(x: float) -> float:
    # Sony S-Log3 (published formula); 18% gray encodes at ~41% (cv 420)
    cv = x * 1023.0
    if cv >= 171.2102946929:
        return (10 ** ((cv - 420.0) / 261.5)) * (0.18 + 0.01) - 0.01
    return (cv - 95.0) * 0.01125 / (171.2102946929 - 95.0)


def _vlog_to_linear(x: float) -> float:
    # Panasonic V-Log (published formula); 18% gray encodes at 42.3%
    b, c, d = 0.00873, 0.241514, 0.598206
    if x < 0.181:
        return (x - 0.125) / 5.6
    return 10 ** ((x - d) / c) - b


def _cineon_to_linear(x: float) -> float:
    # Classic Cineon film-scan curve; a reasonable generic for unlisted logs
    cv = x * 1023.0
    blk = 10 ** ((95.0 - 685.0) / 300.0)
    return (10 ** ((cv - 685.0) / 300.0) - blk) / (1.0 - blk)


# ---------------------------------------------------------------------------
# Print stock: a subtractive color model. Real print film isn't an additive
# curve — it's dye densities with toe/shoulder S-curves in log-exposure
# space, plus interlayer crosstalk (channels contaminating each other
# slightly). That cross-channel bend is the "graded through film" signature
# prestige pipelines chase. We bake it into a generated 3D LUT.
# ---------------------------------------------------------------------------
PRINT_STOCKS = {
    # S midpoints live in log-exposure space where mid-gray lands (~0.83),
    # not at 0.5 — anchoring them there keeps mid-gray near mid output.
    "neutral": dict(mids=(0.850, 0.850, 0.853), gain=(1.00, 1.00, 1.00)),
    "warm":    dict(mids=(0.842, 0.850, 0.866), gain=(1.015, 1.00, 0.975)),
    "cool":    dict(mids=(0.862, 0.850, 0.842), gain=(0.98, 1.00, 1.015)),
}
_XTALK = ((0.88, 0.08, 0.04),
          (0.06, 0.88, 0.06),
          (0.04, 0.10, 0.86))


def _stock_transform(r, g, b, spec):
    import math
    # 1. display -> pseudo log exposure, normalized to [0,1]
    def to_log(v):
        return (math.log10(v * 0.9 + 0.01) + 2.0) / 1.959
    n = [to_log(r), to_log(g), to_log(b)]
    # 2. interlayer crosstalk in log-exposure space
    m = [sum(_XTALK[i][j] * n[j] for j in range(3)) for i in range(3)]
    # 3. per-channel density S-curve (toe + shoulder); midpoint offsets and
    #    gains are the stock's character. Shoulder lands < 1.0: highlights
    #    stay protected, and saturation compresses as channels converge.
    out = []
    k = 4.8
    for i, ch in enumerate(m):
        mid = spec["mids"][i]
        lo = math.tanh(k * (0.0 - mid))
        hi = math.tanh(k * (1.0 - mid))
        y = (math.tanh(k * (ch - mid)) - lo) / (hi - lo)
        y = 0.012 + y * (0.952 - 0.012)
        out.append(min(1.0, max(0.0, y * spec["gain"][i])))
    return out


def make_stock_lut(name: str) -> Path:
    """Generate the print-stock 3D .cube in the temp dir (cached per run)."""
    import tempfile
    spec = PRINT_STOCKS[name]
    n = 33
    lines = [f'TITLE "filmify print stock {name}"', f"LUT_3D_SIZE {n}"]
    for bi in range(n):
        for gi in range(n):
            for ri in range(n):
                r, g, b = (ri / (n - 1), gi / (n - 1), bi / (n - 1))
                ro, go, bo = _stock_transform(r, g, b, spec)
                lines.append(f"{ro:.6f} {go:.6f} {bo:.6f}")
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=f"_stock_{name}.cube", delete=False, encoding="utf-8")
    f.write("\n".join(lines) + "\n")
    f.close()
    return Path(f.name)


_STOCK_LUTS = {}


def stock_lut(name: str) -> Path:
    if name not in _STOCK_LUTS:
        _STOCK_LUTS[name] = make_stock_lut(name)
    return _STOCK_LUTS[name]


_LOG_DECODE = {"slog3": _slog3_to_linear, "vlog": _vlog_to_linear,
               "cineon": _cineon_to_linear}


def _linear_to_display(lin: float) -> float:
    """Scene linear -> BT.709 display, with a smooth highlight shoulder so
    the extended range log captured compresses instead of clipping —
    the protected-highlights philosophy, applied at development time."""
    lin = max(0.0, lin)
    k = 0.6  # shoulder knee: identity below, tanh rolloff above
    if lin > k:
        import math
        lin = k + (1.0 - k) * math.tanh((lin - k) / (1.0 - k))
    # BT.709 OETF
    if lin < 0.018:
        y = 4.5 * lin
    else:
        y = 1.099 * (lin ** 0.45) - 0.099
    return min(1.0, max(0.0, y))


def make_log_lut(curve: str) -> Path:
    """Generate a 1D .cube LUT (log -> display) in the temp dir."""
    import tempfile
    decode = _LOG_DECODE[curve]
    n = 4096
    lines = [f'TITLE "filmify {curve} to display"', f"LUT_1D_SIZE {n}"]
    for i in range(n):
        y = _linear_to_display(decode(i / (n - 1)))
        lines.append(f"{y:.6f} {y:.6f} {y:.6f}")
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=f"_{curve}.cube", delete=False, encoding="utf-8")
    f.write("\n".join(lines) + "\n")
    f.close()
    return Path(f.name)

QUICKSTART = f"""filmify {__version__} — make digital video look like physical film.

Try this first (15-second split-screen test of the look):

    python filmify.py yourclip.mp4 --compare --preview

Then the full workflow:

    1. Dial it in     --look subtle|standard|heavy, add --bw, --weave 1.5 ...
    2. Save the look  --save-look myfilm.json
    3. Run the shoot  python filmify.py shoot_folder/ --look-file myfilm.json --codec prores

Prefer knobs? The control panel works like an audio plugin:

    python filmify.py yourclip.mp4 --ui

A report with before/after thumbnails opens in your browser after each run.
Full options: python filmify.py --help
"""

# Settings persisted in a project look file (--save-look / --look-file)
LOOK_KEYS = [
    "look", "bw", "conform", "weave", "grain", "halation", "soften",
    "saturation", "chroma_soften", "plate_opacity", "no_curve",
    "no_vignette", "crf", "codec", "lut", "grain_plate",
    "input_log", "leak", "depth", "flare", "ratio", "gauge", "print_stock",
    "presence", "flicker", "corner_soften", "age", "no_protect_skin",
]

# Resolved at startup by find_tool(); plain names work as a fallback.
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
_TIP_SHOWN = False


def run(cmd, **kw):
    """subprocess.run, but never flashes a console window on Windows. Every
    ffmpeg/ffprobe/osascript/powershell call goes through here — without the
    flag, each one pops a visible cmd window, which on slider drags means a
    storm of windows opening and closing."""
    if os.name == "nt":
        kw.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
    return subprocess.run(cmd, **kw)


def reveal_in_file_manager(path: Path) -> None:
    """Open the OS file manager with the given file highlighted."""
    path = Path(path)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)])
        elif os.name == "nt":
            # explorer is picky: it must be one argument string with the path
            # quoted, it must NOT get CREATE_NO_WINDOW (that suppresses the
            # window we're trying to open), and it returns exit code 1 even on
            # success — so call it directly and ignore the code. Backslashes
            # and the comma matter: explorer /select,"C:\dir\file.ext"
            winpath = str(path).replace("/", "\\")
            subprocess.Popen(f'explorer /select,"{winpath}"')
        else:
            subprocess.run(["xdg-open", str(path.parent)])
    except OSError:
        pass


def find_tool(name: str):
    """Locate ffmpeg/ffprobe: PATH first, then beside this script, then the
    working directory. Windows users often drop ffmpeg.exe next to the
    script instead of editing PATH — support that."""
    hit = shutil.which(name)
    if hit:
        return hit
    exe = name + (".exe" if os.name == "nt" else "")
    for d in (Path(__file__).resolve().parent, Path.cwd()):
        cand = d / exe
        if cand.is_file():
            return str(cand)
    return None

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mts", ".mxf"}

# ----------------------------------------------------------------------------
# Look presets. Every value can be overridden from the CLI.
#
# `curve` gives each preset its own contrast CHARACTER, not just amount:
# film stocks all add global contrast, but differ in *which tonal region*
# the contrast lives in — those regional differences are the stock's
# personality. All curves share the protected-highlight shoulder (<1.0)
# and slight black lift.
# ----------------------------------------------------------------------------
LOOKS = {
    # near-neutral mids, soft shoulder — modern digital-cinema finish
    "subtle": dict(
        soften=0.35, saturation=0.93, halation=0.22, halation_thresh=0.82,
        grain=5, plate_opacity=0.30, vignette="PI/7", warmth=0.04, chroma=0.8,
        presence=0.22,
        curve="0/0.01 0.22/0.2 0.5/0.51 0.8/0.825 0.93/0.925 1/0.965",
    ),
    # contrast concentrated in the midtones — classic print-stock snap
    "standard": dict(
        soften=0.55, saturation=0.88, halation=0.33, halation_thresh=0.78,
        grain=7, plate_opacity=0.42, vignette="PI/6", warmth=0.06, chroma=1.2,
        presence=0.30,
        curve="0/0.015 0.15/0.12 0.35/0.33 0.5/0.52 0.72/0.78 0.92/0.915 1/0.955",
    ),
    # lifted faded blacks, contrast in the lower-mids, compressed top — vintage
    "heavy": dict(
        soften=0.85, saturation=0.82, halation=0.48, halation_thresh=0.72,
        grain=11, plate_opacity=0.55, vignette="PI/5", warmth=0.09, chroma=1.8,
        presence=0.34,
        curve="0/0.03 0.12/0.115 0.3/0.3 0.55/0.62 0.8/0.85 1/0.945",
    ),
    # Kodak VISION 500T (5279)-style tungsten negative — the early-Sopranos
    # base. Documented traits driving each value (Kodak/ASC data):
    #  - tungsten 3200K balance -> warm bias (warmth high)
    #  - "flesh-to-neutral reproduction" -> restrained saturation, skin kept
    #  - "clean white highlights", linear curve, wide latitude -> gentle
    #    shoulder, no hard clip
    #  - grain heaviest in the blue/yellow layer -> coarser grain, blue lean
    #    is applied in the grain stage; here we set overall grain a touch up
    #  - moderate halation around tungsten practicals
    "vision-500t": dict(
        soften=0.45, saturation=0.85, halation=0.30, halation_thresh=0.80,
        grain=9, plate_opacity=0.40, vignette="PI/7", warmth=0.10, chroma=1.0,
        presence=0.26,
        curve="0/0.015 0.15/0.13 0.35/0.34 0.5/0.52 0.72/0.77 0.92/0.915 1/0.95",
    ),
}

# Panchromatic-ish B&W channel weighting (red-favoring vs Rec.709 luma,
# the way classic B&W stocks render skin slightly bright and skies darker)
BW_MIX = (
    "colorchannelmixer="
    "rr=.35:rg=.45:rb=.20:"
    "gr=.35:gg=.45:gb=.20:"
    "br=.35:bg=.45:bb=.20"
)


def probe(path: Path) -> dict:
    """Return basic stream info for a file. Raises RuntimeError on failure
    so batch runs can record the error and continue."""
    cmd = [
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=avg_frame_rate,width,height,color_transfer:format=duration",
        "-of", "json", str(path),
    ]
    out = run(cmd, capture_output=True, text=True)
    data = json.loads(out.stdout) if out.returncode == 0 else {}
    if out.returncode != 0 or not data.get("streams"):
        detail = out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "no video stream"
        raise RuntimeError(f"ffprobe failed on {path.name}: {detail}")
    info = data["streams"][0]
    num, den = info["avg_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    dur = float(data.get("format", {}).get("duration", 0) or 0)
    trc = info.get("color_transfer") or ""
    return {"fps": fps, "width": info["width"], "height": info["height"],
            "duration": dur, "hdr": trc in ("smpte2084", "arib-std-b67")}


_FILTER_LIST = None


def has_filter(name: str) -> bool:
    """Whether this ffmpeg build provides a filter (cached)."""
    global _FILTER_LIST
    if _FILTER_LIST is None:
        out = run([FFMPEG, "-hide_banner", "-filters"],
                             capture_output=True, text=True)
        _FILTER_LIST = out.stdout if out.returncode == 0 else ""
    return f" {name} " in _FILTER_LIST


def measure_clip(path: Path):
    """Average luma and chroma (Y/U/V means, 0-255) sampled at 1 fps —
    the colorist's light meter for shot matching."""
    cmd = [
        FFPROBE, "-v", "error", "-f", "lavfi",
        "-i", f"movie={fpath(path)},fps=1,signalstats",
        "-show_entries",
        "frame_tags=lavfi.signalstats.YAVG,lavfi.signalstats.UAVG,"
        "lavfi.signalstats.VAVG",
        "-of", "csv=p=0",
    ]
    out = run(cmd, capture_output=True, text=True)
    ys, us, vs = [], [], []
    for line in out.stdout.splitlines():
        parts = [p for p in line.strip().split(",") if p]
        if len(parts) >= 3:
            try:
                y, u, v = (float(parts[0]), float(parts[1]), float(parts[2]))
                ys.append(y); us.append(u); vs.append(v)
            except ValueError:
                continue
    if not ys:
        return None
    n = len(ys)
    return (sum(ys) / n, sum(us) / n, sum(vs) / n)


def fpath(path: Path) -> str:
    """Escape a file path for use inside an ffmpeg filtergraph.

    Filtergraph syntax treats ':' specially, which breaks Windows drive
    letters like C:\\luts\\film.cube. Forward slashes work fine on Windows,
    and the colon needs a single backslash escape even inside quotes.
    """
    s = str(path.resolve())
    if "'" in s:
        sys.exit(f"error: path contains a quote character, please rename: {s}")
    s = s.replace("\\", "/").replace(":", "\\:")
    return f"'{s}'"


def apply_look_file(args, ap) -> None:
    """Fill settings from a project look file. Explicit CLI flags win:
    a value is only taken from the file where the arg is still at its
    parser default. Relative LUT/grain-plate paths resolve against the
    look file's own folder, so a project directory stays portable."""
    lf = Path(args.look_file)
    if not lf.exists():
        sys.exit(f"error: look file not found: {lf}")
    try:
        data = json.loads(lf.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"error: {lf} is not valid JSON: {e}")
    base = lf.resolve().parent
    for k in LOOK_KEYS:
        if k in data and getattr(args, k) == ap.get_default(k):
            v = data[k]
            if k in ("lut", "grain_plate") and v is not None:
                v = Path(v)
                if not v.is_absolute():
                    v = base / v
            setattr(args, k, v)


def save_look_file(args) -> None:
    """Write the effective settings to a JSON look file."""
    data = {"filmify_version": __version__}
    for k in LOOK_KEYS:
        v = getattr(args, k)
        data[k] = str(v) if isinstance(v, Path) else v
    Path(args.save_look).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    print(f"look saved: {args.save_look}")


def build_filtergraph(args, info: dict) -> str:
    p = dict(LOOKS[args.look])  # copy preset, then apply CLI overrides
    for key in ("grain", "halation", "soften", "saturation", "plate_opacity"):
        v = getattr(args, key, None)
        if v is not None:
            p[key] = v
    if args.chroma_soften is not None:
        p["chroma"] = args.chroma_soften

    # Film gauge character: 70mm's negative is ~3.5x the area of 35mm, so it
    # reads finer-grained and cleaner; 16mm goes the other way.
    if args.gauge == "16mm":
        p["grain"] = max(1, round(p["grain"] * 1.8))
        p["soften"] = min(1.5, p["soften"] + 0.25)
        p["chroma"] = p["chroma"] + 0.4
        p["plate_opacity"] = min(1.0, p["plate_opacity"] * 1.3)
    elif args.gauge == "70mm":
        p["grain"] = max(0, round(p["grain"] * 0.5))
        p["soften"] = max(0.0, p["soften"] * 0.6)

    chain = []
    pre = []   # ratio crop + temporal conform run before the compare split,
               # so both halves share framing and cadence and the split
               # compares only the look
    src_fps = info["fps"]
    w_px, h_px = info["width"], info["height"]
    out_fps = 24 if (args.conform and src_fps > 24.5) else (src_fps or 24)

    # -- 0. Cinema aspect ratio: center-crop to the target ratio -------------
    if args.ratio:
        r = args.ratio
        sr = w_px / h_px
        if abs(r - sr) > 0.01:
            if r > sr:   # wider target: crop height
                cw, ch = w_px, int(w_px / r / 2) * 2
            else:        # narrower target: crop width
                cw, ch = int(h_px * r / 2) * 2, h_px
            cw, ch = max(2, cw), max(2, ch)
            pre.append(f"crop={cw}:{ch}")
            w_px, h_px = cw, ch

    depth10 = args.depth == 10
    # working format for the filter chain; final format for the encoder;
    # RGB format for screen-blend stages (screen math on YUV chroma planes
    # shifts neutral colors magenta — all screen blends must run in RGB)
    wfmt = "yuv444p10le" if depth10 else "yuv420p"
    rgbfmt = "gbrp10le" if depth10 else "gbrp"
    if depth10:
        ofmt = "yuv422p10le" if args.codec in ("prores", "dnxhr") else "yuv420p10le"
    else:
        ofmt = "yuv420p"

    # -- 1. Temporal conform: 24 fps + ~180° shutter via frame blending ------
    if args.conform:
        if src_fps > 30:
            pre.append("tmix=frames=2")   # synthesize shutter blur
            pre.append("fps=24")
        elif src_fps > 24.5:
            pre.append("fps=24")
        # already ~24 / 23.976: leave cadence alone

    # -- 1.5 HDR development: phones default to HLG/PQ recording; fed to a
    #        Rec.709 pipeline untouched it comes out washed and wrong, and
    #        the user blames the tool. Tone-map to 709 first.
    if info.get("hdr") and not args.no_tonemap and has_filter("zscale"):
        chain.append(
            "zscale=t=linear:npl=100,"
            "tonemap=tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:p=bt709"
        )

    # -- 2. Working bit depth --------------------------------------------------
    chain.append(f"format={wfmt}")

    # -- 3. Log input development: camera log -> display, via generated or
    #       manufacturer LUT. Runs first so the film look lands on properly
    #       developed footage instead of the flat log image.
    if getattr(args, "_loglut", None):
        kind, lpath = args._loglut
        chain.append(f"lut{kind}=file={fpath(lpath)}")

    # -- 3.5 Shot match: gentle, clamped exposure/WB nudge toward the batch
    #        median, computed in main's measurement pass. The colorist's
    #        first hour: match the shots, then lay the look over them.
    mt = getattr(args, "_match", None)
    if mt:
        br, rm, bm = mt
        parts = []
        if abs(br) > 0.004:
            parts.append(f"eq=brightness={br:.4f}")
        if abs(rm) > 0.004 or abs(bm) > 0.004:
            parts.append(f"colorbalance=rm={rm:.4f}:bm={bm:.4f}")
        chain.extend(parts)

    # -- 4. Softening: negative unsharp == controlled blur -------------------
    if p["soften"] > 0:
        chain.append(
            f"unsharp=luma_msize_x=7:luma_msize_y=7:luma_amount=-{p['soften']:.2f}"
        )

    # -- 4.5 Mid-frequency presence: the anti-"flat gray veneer". Film's MTF
    #        rolls off fine detail (our softening) but keeps LOCAL contrast —
    #        texture pop without edge sharpness. Large-radius, low-amount
    #        unsharp is the classic remedy for digital flatness.
    pres = args.presence if args.presence is not None else p.get("presence", 0.3)
    if pres > 0:
        # Large-radius local contrast via unsharp at a safe matrix size (the
        # filter caps at 25 and its internal sum overflows near it — 13 is
        # the practical ceiling). Low amount, wide radius = midtone "pop"
        # without the edge-sharpening that screams digital.
        chain.append(
            f"unsharp=luma_msize_x=13:luma_msize_y=13:luma_amount={pres:.2f}"
        )

    # -- 5. Gate weave: slow frame drift, two layered sines per axis ---------
    if args.weave > 0:
        a = args.weave
        m = max(2, int(a * 1.6) + 1)
        chain.append(
            f"crop=w=iw-{2 * m}:h=ih-{2 * m}:"
            f"x='{m}+{a:.2f}*sin(n/9.1)+{a / 2:.2f}*sin(n/3.7)':"
            f"y='{m}+{a * 0.7:.2f}*sin(n/7.3)+{a / 2:.2f}*sin(n/2.9)'"
        )
        chain.append(f"scale={w_px}:{h_px},setsar=1")

    # -- 6. B&W mode: panchromatic-weighted mono before the tone curve -------
    if args.bw:
        chain.append(BW_MIX)

    # Which color engine owns tone+color? user LUT > print stock > built-in
    use_stock = bool(args.print_stock) and not args.lut

    # -- 7. Filmic tone curve (per-preset contrast character) -----------------
    # The print stock's density curves supply the tone when active.
    if not args.no_curve and not use_stock:
        chain.append(f"curves=all='{p['curve']}'")

    # -- 7.5 Density flicker: film exposure breathes slightly frame to frame;
    #        rock-steady luminance is a digital tell. Layered incommensurate
    #        sines read as irregular variation, not a strobe.
    if args.flicker > 0:
        a = args.flicker * 0.16
        chain.append(
            f"hue=b='{a:.3f}*(0.6*sin(t*7.3)+0.4*sin(t*13.7)+0.3*sin(t*2.9))'"
        )

    # -- 8. Film-stock LUT / print stock ----------------------------------------
    if args.lut:
        chain.append(f"lut3d=file={fpath(args.lut)}")
    elif use_stock:
        chain.append(f"lut3d=file={fpath(stock_lut(args.print_stock))}")

    # -- 9. Color discipline ----------------------------------------------------
    if not args.bw:
        if p["saturation"] != 1.0:
            if args.no_protect_skin:
                chain.append(f"eq=saturation={p['saturation']:.2f}")
            else:
                # Skin-protected desaturation: faces are where audiences
                # look, and global desat pulls skin lifeless along with
                # everything else. Pull non-skin hues the full amount and
                # the red-yellow (skin) range only ~35% of it.
                d = 1.0 - p["saturation"]   # how much we're reducing
                chain.append(
                    f"huesaturation=saturation={-d:.3f}:colors=g+c+b+m,"
                    f"huesaturation=saturation={-d * 0.35:.3f}:colors=r+y"
                )
        if not args.lut and not use_stock:
            # warm highlights, faintly cool shadows — a classic print-stock
            # split. Skipped when a LUT is supplied: the LUT owns the color.
            w = p["warmth"]
            chain.append(
                f"colorbalance="
                f"rh={w:.3f}:bh={-w * 0.5:.3f}:"
                f"rs={-w * 0.3:.3f}:bs={w * 0.4:.3f}"
            )
        # Chroma softening: film's color layers resolve softer than its
        # luminance. Blur ONLY the chroma planes.
        if p["chroma"] > 0:
            chain.append(f"format={wfmt},gblur=sigma={p['chroma']:.2f}:planes=6")

    body = ",".join(chain) if chain else "null"
    pre_str = ",".join(pre) if pre else "null"
    if args.compare:
        prefix = f"[0:v]{pre_str},split[orig][pin];[pin]"
    else:
        prefix = "[0:v]" + (",".join(pre) + "," if pre else "")

    # -- 10. Halation: split → isolate highlights → blur → tint → screen -----
    if p["halation"] > 0:
        t = p["halation_thresh"]
        # B&W stock halos stay neutral; color stock halos go red-orange
        tint = "" if args.bw else ",colorchannelmixer=rr=1.0:gg=0.46:bb=0.24"
        hal = (
            f"format={rgbfmt},"
            f"colorlevels=rimin={t}:gimin={t}:bimin={t},"
            f"gblur=sigma=16"
            f"{tint}"
        )
        graph = (
            f"{prefix}{body},split[base][hl];"
            f"[hl]{hal}[hal];"
            f"[base]format={rgbfmt}[baseR];"
            f"[baseR][hal]blend=all_mode=screen:all_opacity={p['halation']:.2f}[pre]"
        )
    else:
        graph = f"{prefix}{body}[pre]"

    cur = "[pre]"

    # -- 10a. Corner softness (field curvature): sharp center, softer
    #         corners — vintage glass's answer to the everything-in-focus
    #         complaint. Blurred copy merged through an inverted-vignette
    #         radial mask. Before grain: grain lives on the film plane and
    #         stays sharp to the edges.
    if args.corner_soften > 0:
        graph += (
            f";{cur}split[cs_a][cs_b];"
            f"[cs_b]gblur=sigma={args.corner_soften:.2f}[cs_blur];"
            f"color=c=white:s={w_px}x{h_px}:r={out_fps:g},"
            f"vignette=angle=PI/3.4,negate,format={wfmt},gblur=sigma=24[cs_m];"
            f"[cs_a]format={wfmt}[cs_a2];[cs_blur]format={wfmt}[cs_blur2];"
            f"[cs_a2][cs_blur2][cs_m]maskedmerge=planes=7[csf]"
        )
        cur = "[csf]"

    # -- 10b. Anamorphic streak flare: bright lights grow a long horizontal
    #         blue-tinted line — the signature anamorphic-lens artifact,
    #         emulated here the way effect filters do for spherical glass.
    #         Screen blend runs in RGB (YUV screen blending shifts neutral
    #         chroma magenta — same lesson as the light leak).
    if args.flare > 0:
        streak = (
            f"format={rgbfmt},"
            f"colorlevels=rimin=0.85:gimin=0.85:bimin=0.85,"
            f"gblur=sigma={max(20, int(w_px * 0.05))}:sigmaV=0.8,"
            f"colorchannelmixer=rr=0.25:gg=0.55:bb=1.0"
        )
        graph += (
            f";{cur}split[flb][fls];"
            f"[fls]{streak}[flk];"
            f"[flb]format={rgbfmt}[flbr];"
            f"[flbr][flk]blend=all_mode=screen:all_opacity={args.flare:.2f}[flo]"
        )
        cur = "[flo]"

    # -- 11. Light leak: a slow radial warm glow from the frame edge that the
    #        gradients source cycles in and out of existence over time —
    #        appears for a stretch, fades for a longer one, like a real
    #        intermittent body leak.
    if args.leak > 0:
        # Screen-blending must happen in RGB: applying the screen formula to
        # YUV chroma planes (0.5-centered) shifts neutral colors toward
        # magenta across the whole frame (found the hard way).
        leak = (
            f"gradients=s={w_px}x{h_px}:type=radial:n=6:"
            f"x0=0:y0={int(h_px * 0.25)}:x1={int(w_px * 0.55)}:y1={h_px}:"
            f"c0=0xFF7A30:c1=0x000000:c2=0x000000:c3=0x000000:"
            f"c4=0x2A1004:c5=0x000000:"
            f"speed=0.008:rate={out_fps:g},format={rgbfmt}"
        )
        graph += (
            f";{leak}[leakg];"
            f"{cur}format={rgbfmt}[lkbase];"
            f"[lkbase][leakg]blend=all_mode=screen:all_opacity={args.leak:.2f}:shortest=1[lk]"
        )
        cur = "[lk]"

    # -- 12. Grain --------------------------------------------------------------
    if args.grain_plate:
        # Real scanned grain: loop it, scale to cover the frame, overlay-blend.
        graph += (
            f";[1:v]scale={w_px}:{h_px}:force_original_aspect_ratio=increase,"
            f"crop={w_px}:{h_px},format={wfmt}[gp];"
            f"{cur}[gp]blend=all_mode=overlay:all_opacity={p['plate_opacity']:.2f}:shortest=1[gr]"
        )
        cur = "[gr]"
    elif p["grain"] > 0:
        # Synthesized grain v2: grain has PHYSICAL SCALE, not just strength.
        # Per-pixel noise on 4K reads as digital fizz; real grain is sized
        # relative to the frame and the gauge. So: generate noise on a
        # mid-gray plate at reduced resolution (gauge sets the divisor),
        # scale it up bilinearly into soft clumps, overlay-blend, then
        # maskedmerge it through a midtone-weighted luma mask — negative
        # stock wears its grain in the mids; highlights stay cleaner.
        g = int(p["grain"] * (1.5 if args.bw else 1.0))
        gdiv = {"16mm": 2.6, "35mm": 1.6, "70mm": 1.0}[args.gauge]
        gw = max(2, int(w_px / gdiv / 2) * 2)
        gh = max(2, int(h_px / gdiv / 2) * 2)
        upscale = "" if gdiv == 1.0 else f",scale={w_px}:{h_px}:flags=bilinear"
        graph += (
            f";color=c=0x808080:s={gw}x{gh}:r={out_fps:g},"
            f"noise=c0s={g}:c0f=t+u:"
            f"c1s={max(1, g // 3)}:c1f=t+u:c2s={max(1, g // 3)}:c2f=t+u"
            f"{upscale},format={wfmt}[gnz];"
            f"{cur}split=3[gb][gov][gmsk];"
            f"[gov][gnz]blend=all_mode=overlay:shortest=1[govd];"
            f"[gmsk]format=gray,"
            f"curves=all='0/0.35 0.45/1 0.78/0.5 1/0.18',format={wfmt}[gm];"
            f"[gb][govd][gm]maskedmerge[gn]"
        )
        cur = "[gn]"

    # -- 12.5 Print damage: white dust specks (heavily thresholded temporal
    #         noise, scaled up into speck-sized blobs) plus a thin vertical
    #         scratch that wanders and only exists for a moment every few
    #         seconds. Screen-blended in RGB, strictly opt-in.
    if args.age > 0:
        ag = args.age
        dw = max(2, int(w_px / 3 / 2) * 2)
        dh = max(2, int(h_px / 3 / 2) * 2)
        graph += (
            # dust layer
            f";color=c=0x161616:s={dw}x{dh}:r={out_fps:g},"
            f"noise=c0s=82:c0f=t+u,"
            f"colorlevels=rimin=0.62:gimin=0.62:bimin=0.62,"
            f"scale={w_px}:{h_px}:flags=bilinear,gblur=sigma=0.6,"
            f"format={rgbfmt}[dust];"
            # scratch layer: static line on a wider canvas, crop position
            # drifts; visibility gated to a brief window every ~9 s
            f"color=c=black:s={w_px + 240}x{h_px}:r={out_fps:g},"
            f"drawbox=x={(w_px + 240) // 2}:y=0:w=2:h={h_px}:color=0x9A9A9A:t=fill,"
            f"crop={w_px}:{h_px}:x='120+85*sin(t*0.67)+45*sin(t*1.93)':y=0,"
            f"hue=b='if(lt(mod(t,9.2),1.3),0,-12)',"
            f"format={rgbfmt}[scr];"
            f"[dust][scr]blend=all_mode=screen:shortest=1[dmg];"
            f"{cur}format={rgbfmt}[agebase];"
            f"[agebase][dmg]blend=all_mode=screen:all_opacity={ag:.2f}:shortest=1[aged]"
        )
        cur = "[aged]"

    # -- 13. Vignette ------------------------------------------------------------
    if not args.no_vignette:
        if depth10:
            # vignette runs fine at 10-bit in RGB (the earlier "8-bit only"
            # workaround mishandled YUV chroma and turned neutrals magenta).
            graph += (
                f";{cur}format={rgbfmt},vignette=angle={p['vignette']}[vg]"
            )
            cur = "[vg]"
        else:
            graph += f";{cur}vignette=angle={p['vignette']}[vg]"
            cur = "[vg]"

    # -- 14. Final format + compare combiner --------------------------------
    out_label = "[outp]" if args.compare else "[vout]"
    graph += f";{cur}format={ofmt}{out_label}"

    if args.compare:
        graph += (
            f";[orig]format={ofmt},crop=w=iw/2:h=ih:x=0:y=0,setsar=1[L];"
            f"[outp]crop=w=iw/2:h=ih:x=iw/2:y=0,setsar=1[R];"
            f"[L][R]hstack,"
            f"drawbox=x=iw/2-1:y=0:w=2:h=ih:color=white@0.6:t=fill[vout]"
        )

    return graph


def summarize_settings(args) -> str:
    bits = [args.look]
    if getattr(args, "input_log", None):
        n = str(args.input_log)
        bits.append(f"log: {Path(n).name if n.lower() not in LOG_PRESETS else n}")
    if args.depth == 10:
        bits.append("10-bit")
    if args.codec != "h264":
        bits.append(args.codec)
    if args.bw:
        bits.append("B&W")
    if args.conform:
        bits.append("24fps/180° conform")
    if args.weave > 0:
        bits.append(f"weave {args.weave:g}px")
    if args.leak > 0:
        bits.append(f"leak {args.leak:g}")
    if args.flicker > 0:
        bits.append(f"flicker {args.flicker:g}")
    if args.age > 0:
        bits.append(f"aged {args.age:g}")
    if args.corner_soften > 0:
        bits.append(f"corners {args.corner_soften:g}")
    if args.flare > 0:
        bits.append(f"flare {args.flare:g}")
    if args.ratio:
        bits.append(f"{args.ratio:g}:1")
    if args.gauge != "35mm":
        bits.append(args.gauge)
    if args.lut:
        bits.append(f"LUT: {args.lut.name}")
    elif getattr(args, "print_stock", None):
        bits.append(f"stock: {args.print_stock}")
    if args.grain_plate:
        bits.append(f"grain plate: {args.grain_plate.name}")
    if args.preview:
        bits.append(f"preview {args.preview:g}s")
    if args.compare:
        bits.append("compare split")
    if args.look_file:
        bits.append(f"look file: {Path(args.look_file).name}")
    return " + ".join(bits)


def grab_thumb(path: Path, seconds: float) -> str:
    """Return a frame as a base64 JPEG data URI ('' on failure), so the
    report is a single self-contained file."""
    out = run(
        [FFMPEG, "-v", "error", "-ss", f"{max(0.0, seconds):.2f}",
         "-i", str(path), "-frames:v", "1", "-vf", "scale=480:-2",
         "-f", "image2", "-c:v", "mjpeg", "-q:v", "4", "pipe:1"],
        capture_output=True,
    )
    if out.returncode != 0 or not out.stdout:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(out.stdout).decode()


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


_HW_ENCODER = "unset"


def detect_hw_encoder():
    """Return the name of a working hardware H.264 encoder for this machine,
    or None. An encoder being *listed* doesn't mean it *works* (no GPU, no
    driver), so we actually try a 1-frame encode and cache the result."""
    global _HW_ENCODER
    if _HW_ENCODER != "unset":
        return _HW_ENCODER
    if sys.platform == "darwin":
        candidates = ["h264_videotoolbox"]
    elif os.name == "nt":
        candidates = ["h264_nvenc", "h264_qsv", "h264_amf"]
    else:
        candidates = ["h264_nvenc", "h264_qsv", "h264_vaapi"]
    listed = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                            capture_output=True, text=True).stdout
    _HW_ENCODER = None
    for enc in candidates:
        if f" {enc}" not in listed:
            continue
        probe = run([FFMPEG, "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", "testsrc2=s=128x128:d=0.1",
                     "-c:v", enc, "-frames:v", "1", "-f", "null", "-"],
                    capture_output=True)
        if probe.returncode == 0:
            _HW_ENCODER = enc
            break
    return _HW_ENCODER


def render(src: Path, out: Path, args, progress_cb=None) -> dict:
    """Build and run the ffmpeg command for one file. Returns a result
    record for the report; failures are recorded so a batch can continue.
    progress_cb, if given, is called with a 0-100 percentage as ffmpeg runs."""
    res = {"src": src, "out": out, "ok": False, "error": "",
           "fps_in": None, "fps_out": None, "size": None, "dur": None,
           "thumb_before": "", "thumb_after": ""}
    try:
        info = probe(src)
    except RuntimeError as exc:
        res["error"] = str(exc)
        print(f"input : {src}\nFAILED: {res['error']}\n")
        return res
    res["fps_in"] = info["fps"]
    if info.get("hdr"):
        if args.no_tonemap:
            print("note  : HDR source — tone-mapping disabled (--no-tonemap)")
        elif has_filter("zscale"):
            print("note  : HDR source detected — tone-mapping to Rec.709")
        else:
            print("warn  : HDR source, but this ffmpeg lacks zscale — colors "
                  "may look washed; install a full ffmpeg build")

    graph = build_filtergraph(args, info)
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-stats",
           "-i", str(src)]
    if args.grain_plate:
        cmd += ["-stream_loop", "-1", "-i", str(args.grain_plate)]
    cmd += ["-filter_complex", graph, "-map", "[vout]", "-map", "0:a?"]
    if args.preview:
        cmd += ["-t", f"{args.preview:g}"]
    if args.codec == "prores":
        # ProRes 422 HQ — edit-friendly mezzanine (Final Cut, Resolve, Premiere)
        cmd += ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0",
                "-pix_fmt", "yuv422p10le", "-c:a", "pcm_s16le"]
    elif args.codec == "dnxhr":
        # DNxHR — edit-friendly mezzanine (Resolve, Premiere, Avid).
        # HQX is the 10-bit profile; HQ is 8-bit.
        if args.depth == 10:
            cmd += ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx",
                    "-pix_fmt", "yuv422p10le", "-c:a", "pcm_s16le"]
        else:
            cmd += ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq",
                    "-pix_fmt", "yuv422p", "-c:a", "pcm_s16le"]
    else:
        # h264 — delivery codec; fine for a finish pass, poor for editing.
        # Use a hardware encoder when one is actually available (much faster
        # on long clips); otherwise libx264 tuned for grain retention.
        if not args.no_hwaccel and not args.preview:
            hw = detect_hw_encoder()
        else:
            hw = None
        if hw == "h264_nvenc":
            cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                    "-cq", str(args.crf), "-c:a", "copy"]
        elif hw == "h264_videotoolbox":
            cmd += ["-c:v", "h264_videotoolbox", "-q:v",
                    str(max(1, min(100, 100 - args.crf * 3))), "-c:a", "copy"]
        elif hw == "h264_qsv":
            cmd += ["-c:v", "h264_qsv", "-global_quality", str(args.crf),
                    "-c:a", "copy"]
        else:
            cmd += ["-c:v", "libx264",
                    "-preset", "fast" if args.preview else "slow",
                    "-crf", str(args.crf), "-tune", "grain",
                    "-threads", "0", "-c:a", "copy"]
        if hw:
            print(f"encode: hardware ({hw})")
    cmd += ["-metadata",
            f"comment=processed with filmify {__version__} | "
            f"{summarize_settings(args)}"]
    cmd += [str(out)]

    print(f"input : {src}  ({info['width']}x{info['height']} @ {info['fps']:.3f} fps)")
    print(f"output: {out}")
    print(f"look  : {summarize_settings(args)}")
    global _TIP_SHOWN
    if (not _TIP_SHOWN and not args.preview and not args.dry_run
            and info["duration"] > 30):
        print("tip   : add --compare --preview to test the look in seconds "
              "before a full render")
        _TIP_SHOWN = True

    if args.dry_run:
        print("\n" + " ".join(f"'{c}'" if " " in c else c for c in cmd) + "\n")
        res["ok"] = True
        return res

    if progress_cb is None:
        rc = run(cmd).returncode
    else:
        # Total duration we're rendering, for percentage. Preview caps it.
        total = info["duration"] or 0
        if args.preview:
            total = min(total, float(args.preview)) or float(args.preview)
        # -progress pipe:1 emits machine-readable out_time_us=… lines.
        pcmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000
        proc = subprocess.Popen(pcmd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, **kw)
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") and total > 0:
                try:
                    us = int(line.split("=", 1)[1])
                    pct = max(0, min(99, int(us / 1e6 / total * 100)))
                    progress_cb(pct)
                except (ValueError, ZeroDivisionError):
                    pass
            elif line == "progress=end":
                progress_cb(100)
        proc.wait()
        rc = proc.returncode
    if rc != 0:
        res["error"] = f"ffmpeg exited with code {rc} (see console output above)"
        print(f"FAILED: {res['error']}\n")
        return res

    res["ok"] = True
    try:
        o = probe(out)
        res["fps_out"] = o["fps"]
        res["dur"] = o["duration"]
        res["size"] = out.stat().st_size
        t = o["duration"] * 0.4
        res["thumb_before"] = grab_thumb(src, t)
        res["thumb_after"] = grab_thumb(out, t)
    except (RuntimeError, OSError):
        pass  # render succeeded; report just has fewer details
    print("done.\n")
    return res


def write_report(results: list, args, dest: Path) -> None:
    """Single self-contained HTML file: before/after thumbnails, per-clip
    status, and the settings used — visual proof the processing landed."""
    e = html.escape
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ok_n = sum(1 for r in results if r["ok"])
    cards = []
    for r in results:
        if r["ok"]:
            status = '<span class="ok">&#10003; processed</span>'
            facts = []
            if r["fps_in"] is not None and r["fps_out"] is not None:
                facts.append(f"{r['fps_in']:g} fps &rarr; {r['fps_out']:g} fps")
            if r["dur"]:
                facts.append(f"{r['dur']:.1f} s")
            if r["size"]:
                facts.append(fmt_size(r["size"]))
            facts.append(e(args.codec))
            detail = " &middot; ".join(facts)
            thumbs = (
                f'<div class="pair">'
                f'<figure><img src="{r["thumb_before"]}" alt=""><figcaption>before</figcaption></figure>'
                f'<figure><img src="{r["thumb_after"]}" alt=""><figcaption>after</figcaption></figure>'
                f"</div>" if r["thumb_before"] and r["thumb_after"] else ""
            )
        else:
            status = '<span class="bad">&#10007; failed</span>'
            detail = e(r["error"])
            thumbs = ""
        cards.append(
            f'<section class="card"><header><h2>{e(r["src"].name)}</h2>{status}</header>'
            f"{thumbs}<p>{detail}</p></section>"
        )
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>filmify report</title><style>
body{{background:#141210;color:#e8e2d8;font:15px/1.5 system-ui,sans-serif;padding:2rem;max-width:1060px;margin:0 auto}}
h1{{font-weight:600;font-size:1.4rem;margin:0}}
.meta{{color:#a89f90;margin:.3rem 0 2rem}}
.card{{background:#1d1a17;border:1px solid #2c2722;border-radius:10px;padding:1rem 1.2rem;margin-bottom:1.2rem}}
.card header{{display:flex;justify-content:space-between;align-items:baseline;gap:1rem}}
.card h2{{font-size:1.05rem;font-weight:600;margin:0;word-break:break-all}}
.ok{{color:#8fc97c;white-space:nowrap}}.bad{{color:#e07a6a;white-space:nowrap}}
.pair{{display:flex;gap:10px;margin:.8rem 0 .2rem;flex-wrap:wrap}}
figure{{margin:0;flex:1;min-width:260px}}
img{{width:100%;border-radius:6px;display:block}}
figcaption{{color:#a89f90;font-size:.8rem;margin-top:.25rem;text-transform:uppercase;letter-spacing:.06em}}
p{{color:#cfc7ba;margin:.5rem 0 0}}#helppop{display:none;position:absolute;width:300px;background:#262019;border:1px solid var(--acc);color:var(--tx);font-size:12px;line-height:1.5;padding:10px 12px;border-radius:8px;z-index:50;box-shadow:0 6px 24px rgba(0,0,0,.5)}
.hq{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;margin-left:6px;border:1px solid var(--dim);border-radius:50%;color:var(--dim);font-size:10px;cursor:help;flex:none}.hq:hover{border-color:var(--acc);color:var(--acc)}
</style></head><body>
<div id="helppop"></div>
<h1>filmify {e(__version__)} &mdash; {ok_n}/{len(results)} clip{"s" if len(results) != 1 else ""} processed</h1>
<p class="meta">{e(when)} &middot; {e(summarize_settings(args))}</p>
{"".join(cards)}</body></html>"""
    dest.write_text(doc, encoding="utf-8")


UI_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>filmify panel</title><link rel="icon" href="data:image/png;base64,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"><style>
:root{--bg:#141210;--panel:#1d1a17;--line:#2c2722;--tx:#e8e2d8;--dim:#a89f90;--acc:#d98a4a}
body{background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,sans-serif;margin:0;display:flex;min-height:100vh}
#side{width:300px;min-width:300px;background:var(--panel);border-right:1px solid var(--line);padding:16px;overflow-y:auto}
#main{flex:1;display:flex;flex-direction:column;align-items:center;padding:18px;gap:10px}
h1{font-size:15px;margin:0 0 2px;color:var(--acc)}
.fn{color:var(--dim);font-size:12px;margin-bottom:12px;word-break:break-all}
label{display:flex;justify-content:space-between;align-items:center;margin:9px 0 2px;font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
label output{color:var(--tx);font-variant-numeric:tabular-nums}
input[type=range]{width:100%;accent-color:var(--acc)}
select,input[type=text]{width:100%;background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:6px;padding:5px 7px;font:inherit}
.checks{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin:10px 0}
.checks label{display:flex;justify-content:flex-start;gap:6px;text-transform:none;margin:0}
button{background:var(--acc);color:#1a120a;border:0;border-radius:7px;padding:9px 12px;font:inherit;font-weight:600;cursor:pointer;width:100%;margin-top:8px}
button.sec{background:var(--line);color:var(--tx)}
#prev{max-width:100%;max-height:72vh;border-radius:8px;background:#000;min-height:200px}
#scrubrow{width:100%;max-width:960px;display:flex;gap:10px;align-items:center;color:var(--dim);font-size:12px}
#scrubrow input{flex:1}
#status{color:var(--dim);font-size:13px;min-height:1.2em}
hr{border:0;border-top:1px solid var(--line);margin:14px 0}
#cards{display:flex;gap:8px;overflow-x:auto;width:100%;max-width:960px;padding-bottom:4px}
.scard{flex:0 0 150px;cursor:pointer;border:2px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel)}
.scard.sel{border-color:var(--acc)}
.scard img{width:100%;height:84px;object-fit:cover;display:block;background:#000}
.scard div{font-size:11px;text-align:center;padding:3px 2px;color:var(--dim);text-transform:capitalize}
.scard.sel div{color:var(--acc)}
#guide{background:#241f19;border:1px solid #3a3128;color:#cdbfa8;border-radius:8px;padding:7px 12px;font-size:12.5px;max-width:960px;width:100%;box-sizing:border-box;display:flex;justify-content:space-between;align-items:center;gap:8px}
#import{width:100%;max-width:960px}
#dropzone{border:2px dashed var(--line);border-radius:12px;padding:60px 20px;text-align:center;color:var(--dim);background:var(--panel);transition:border-color .15s,background .15s}
#dropzone.drag{border-color:var(--acc);background:#241c14}
#progwrap{width:100%;height:8px;background:var(--line);border-radius:5px;overflow:hidden;margin-top:8px}
#progfill{height:100%;width:0%;background:var(--acc);transition:width .3s ease}
#batchwrap{width:100%;height:8px;background:var(--line);border-radius:5px;overflow:hidden;margin-top:6px}
#batchfill{height:100%;width:0%;background:#6db86d;transition:width .3s ease}
#gx{cursor:pointer;color:#a89f90;padding:0 4px}
#rendered{background:#1d2a1a;border:1px solid #36502f;color:#9fd18b;border-radius:8px;padding:8px 14px;font-size:13px;max-width:960px;width:100%;box-sizing:border-box}
#helppop{display:none;position:absolute;width:300px;background:#262019;border:1px solid var(--acc);color:var(--tx);font-size:12px;line-height:1.5;padding:10px 12px;border-radius:8px;z-index:50;box-shadow:0 6px 24px rgba(0,0,0,.5)}
.hq{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;margin-left:6px;border:1px solid var(--dim);border-radius:50%;color:var(--dim);font-size:10px;cursor:help;flex:none}.hq:hover{border-color:var(--acc);color:var(--acc)}
</style></head><body>
<div id="helppop"></div>
<div id="side">
  <h1 style="display:flex;align-items:center;gap:8px"><img src="data:image/png;base64,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" width="22" height="22" style="border-radius:5px">filmify __VERSION__</h1>
  <div class="fn">__FILENAME__</div>

  <label>Look (intensity)</label>
  <select id="look"><option>subtle</option><option selected>standard</option><option>heavy</option></select>

  <label>Gauge</label>
  <select id="gauge"><option>16mm</option><option selected>35mm</option><option>70mm</option></select>

  <label>Aspect ratio</label>
  <select id="ratio"><option value="">source</option><option value="1.85">1.85 flat</option><option value="2.2">2.2 70mm</option><option value="2.39">2.39 Scope</option><option value="2.76">2.76 Ultra Panavision</option></select>

  <label>Grain <output id="grainV"></output></label>
  <input type="range" id="grain" min="0" max="20" step="1" value="7">
  <label>Halation <output id="halationV"></output></label>
  <input type="range" id="halation" min="0" max="1" step="0.01" value="0.33">
  <label>Soften <output id="softenV"></output></label>
  <input type="range" id="soften" min="0" max="1.5" step="0.05" value="0.55">
  <label>Saturation <output id="saturationV"></output></label>
  <input type="range" id="saturation" min="0" max="2" step="0.01" value="0.88">
  <label>Chroma soften <output id="chroma_softenV"></output></label>
  <input type="range" id="chroma_soften" min="0" max="3" step="0.1" value="1.2">
  <label>Gate weave <output id="weaveV"></output></label>
  <input type="range" id="weave" min="0" max="3" step="0.1" value="0">
  <label>Light leak <output id="leakV"></output></label>
  <input type="range" id="leak" min="0" max="1" step="0.01" value="0">
  <label>Anamorphic flare <output id="flareV"></output></label>
  <input type="range" id="flare" min="0" max="1" step="0.01" value="0">
  <label>Presence (anti-flat) <output id="presenceV"></output></label>
  <input type="range" id="presence" min="0" max="1" step="0.02" value="0.3">
  <label>Density flicker <output id="flickerV"></output></label>
  <input type="range" id="flicker" min="0" max="1" step="0.01" value="0">
  <label>Corner softness <output id="corner_softenV"></output></label>
  <input type="range" id="corner_soften" min="0" max="3" step="0.1" value="0">
  <label>Aged print <output id="ageV"></output></label>
  <input type="range" id="age" min="0" max="1" step="0.01" value="0">

  <div class="checks">
    <label><input type="checkbox" id="bw"> B&amp;W</label>
    <label><input type="checkbox" id="conform"> 24fps/180&deg;</label>
    <label><input type="checkbox" id="vignette" checked> Vignette</label>
    <label><input type="checkbox" id="curve" checked> Film curve</label>
    <label><input type="checkbox" id="compare" checked> A/B split</label>
    <label><input type="checkbox" id="depth10"> 10-bit</label>
  </div>

  <label>Develop log footage</label>
  <select id="input_log"><option value="">none (Rec.709 source)</option><option value="slog3">S-Log3 (Sony)</option><option value="vlog">V-Log (Panasonic)</option><option value="cineon">Cineon (generic)</option></select>

  <label>Print stock (built-in color engine)</label>
  <select id="print_stock"><option value="">built-in curve + split tone</option><option value="neutral">neutral</option><option value="warm">warm</option><option value="cool">cool</option></select>

  <label>Film-stock LUT (.cube path — your pick, overrides stock)</label>
  <input type="text" id="lut" placeholder="leave empty for built-in color">

  <label>Grain plate (video path, optional)</label>
  <input type="text" id="grain_plate" placeholder="leave empty for synthesized">

  <hr>
  <label>Codec for full render</label>
  <select id="codec"><option selected>h264</option><option>prores</option><option>dnxhr</option></select>

  <label>Load a saved look</label>
  <select id="loadlook"><option value="">— choose —</option>__LOOK_OPTS__</select>

  <label>Save look as</label>
  <input type="text" id="lookname" value="myfilm">
  <button class="sec" id="saveBtn">Save look</button>

  <label>Save the film as</label>
  <input type="text" id="outname" placeholder="(defaults to yourclip_film)">

  <div id="destrow" style="font-size:11px;color:var(--dim);margin:10px 0 2px">
    saves to: <span id="destpath" style="color:var(--tx)">—</span>
    <button class="sec" id="destBtn" style="width:auto;padding:3px 8px;margin:4px 0 0;font-size:11px">Save to…</button>
  </div>

  <button id="renderBtn">Render full clip</button>
  <div id="progwrap" hidden><div id="progfill"></div></div>
  <div id="status"></div>

  <div style="border-top:1px solid var(--line);margin-top:14px;padding-top:12px">
    <label style="display:flex;gap:6px;text-transform:none;font-size:12px;margin-bottom:8px">
      <input type="checkbox" id="matchbox" checked> Match shots across clips (cohesive look)</label>
    <button class="sec" id="batchBtn" style="background:var(--acc);color:#1a120a;font-weight:600">Process whole folder\u2026</button>
    <div style="font-size:11px;color:var(--dim);margin-top:4px">Apply this exact look to every video in a folder. Walk away &mdash; results land in a new timestamped folder.</div>
    <div id="batchstat" hidden style="margin-top:8px;font-size:12px;color:var(--tx)"></div>
    <div id="batchwrap" hidden><div id="batchfill"></div></div>
  </div>
</div>
<div id="main">
  <div id="import">
    <div id="dropzone" style="cursor:pointer">
      <div style="font-size:42px;margin-bottom:8px">&#127909;</div>
      <div style="font-size:16px;color:var(--tx);margin-bottom:4px">Drop a video here, or click to browse</div>
      <div style="font-size:13px;margin-bottom:16px">&nbsp;</div>
      <button id="chooseBtn" style="width:auto;padding:9px 20px">Choose a video…</button>
      <div id="importmsg" style="margin-top:12px;font-size:12px;min-height:1em"></div>
    </div>
  </div>
  <div id="guide" hidden>&#9312; Click a style below that looks right &nbsp;&rarr;&nbsp; &#9313; fine-tune with the sliders &nbsp;&rarr;&nbsp; &#9314; Save look &nbsp;&rarr;&nbsp; &#9315; Render <span id="gx">&#10005;</span></div>
  <div id="cards"></div>
  <img id="prev" alt="preview">
  <div id="rendered" hidden>&#10003; saved: <span id="rname"></span> &nbsp;<button id="revealBtn" style="width:auto;padding:4px 12px;font-size:12px">Show in folder</button></div>
  <div id="scrubrow">0s <input type="range" id="scrub" min="0" max="100" value="40"> __DUR__s</div>
</div>
<script>
const $ = id => document.getElementById(id);
const HELP = {
  look: "Overall strength of the film treatment. 'Subtle' is a light, modern finish; 'standard' is clearly filmic; 'heavy' is a vintage, well-worn stock. Think of it as the master intensity dial.",
  gauge: "The film format. 16mm is grainier and softer (documentary / indie). 35mm is the Hollywood standard. 70mm is large-format: extremely fine grain, very clean (epics like 2001 or Dunkirk).",
  ratio: "Aspect ratio \u2014 the shape of the frame. 2.39 is modern widescreen 'Scope'; 2.2 is 70mm; 2.76 is Ultra Panavision (very wide); 1.85 is standard theatrical 'flat'. Crops your footage to that cinematic shape.",
  grain: "Film grain \u2014 the fine, organic texture of photographic emulsion. Real film grain is random and lively, unlike flat digital noise. Higher = more visible texture.",
  halation: "The soft red-orange glow that blooms around bright highlights on film, caused by light scattering back through the emulsion. Subtle halation is a signature 'this was shot on film' tell.",
  soften: "Reduces digital over-sharpness. Real lenses and film resolve slightly softer than a digital sensor's razor edges. A little softening reads as 'cinematic'; a lot reads as dreamy/diffused.",
  saturation: "Color intensity. Film tends toward restrained, believable color rather than punchy digital saturation. Below 1.0 mutes color; skin tones are protected so faces stay alive.",
  chroma_soften: "Blurs only the color (not the detail). Film's color layers resolve softer than its brightness, so slight chroma softening looks natural and hides digital color noise.",
  weave: "Gate weave \u2014 the tiny, slow side-to-side drift of the image as film moves through a projector or camera gate. A small amount adds subconscious 'mechanical film' feel.",
  leak: "Light leak \u2014 a warm flash of color from light sneaking into the film body, common in old or hand-loaded cameras. Intermittent and vintage; off by default.",
  flare: "Anamorphic flare \u2014 the long horizontal blue streak that anamorphic lenses throw off bright lights. The classic blockbuster / sci-fi lens look.",
  presence: "Mid-frequency local contrast. Counteracts the flat, 'gray veneer' look of digital by adding depth and texture pop \u2014 without the harsh edges of sharpening.",
  flicker: "Density flicker \u2014 the subtle frame-to-frame brightness variation of real film exposure. Steady-as-a-rock brightness is a digital giveaway; a touch of flicker breathes.",
  corner_soften: "Field curvature \u2014 vintage lenses are sharp in the center and softer toward the corners. Gently guides the eye to the middle and reads as 'old glass'.",
  age: "Print damage \u2014 dust specks and the occasional drifting vertical scratch, like a well-worn projection print. Strictly for a deliberately aged look.",
  bw: "Black & white, using a panchromatic film mix (the way B&W film responds to color) rather than a flat desaturate.",
  conform: "Cadence \u2014 conform to 24 fps with a 180\u00b0 shutter motion blur, the standard 'film motion' feel, instead of smooth 30/60 fps 'video motion'.",
  vignette: "Gentle darkening toward the edges of the frame, like a real lens. Draws the eye inward.",
  curve: "The filmic tone curve \u2014 how shadows and highlights roll off. Film compresses highlights gracefully (no harsh clipping) and has a characteristic contrast shape.",
  depth: "10-bit processing keeps smoother gradients (skies, soft light) and survives further color grading better. Pair with ProRes/DNxHR. 8-bit is fine for quick delivery.",
  depth10: "10-bit processing keeps smoother gradients (skies, soft light) and survives further color grading better. Pair with ProRes/DNxHR. 8-bit is fine for quick delivery.",
  compare: "A/B split preview \u2014 shows the original on one side and the filmified result on the other, so you can judge the look against your source as you dial it in.",
  input_log: "If your camera shot in a flat 'Log' profile (S-Log3, V-Log, etc.), develop it to normal color first. Pick your camera's profile, or leave as Rec.709 for normal footage.",
  print_stock: "The color character of a film print stock, like choosing Kodak vs a warm or cool emulsion. A built-in 'graded through film' color engine. Your own .cube LUT overrides it.",
  lut: "Your own film-stock color LUT (.cube file). This is YOUR final color pick \u2014 it overrides filmify's built-in color so you stay in control of the grade.",
  grain_plate: "Use a real scanned film-grain video instead of synthesized grain, for maximum authenticity. Optional path to a grain plate clip.",
  codec: "Output format. H.264 = small, ready to share. ProRes / DNxHR = high-quality 'mezzanine' formats for editing in Premiere, Resolve, or Final Cut.",
  match: "Shot matching \u2014 before applying the look, gently nudge every clip toward a common exposure and white balance so mixed cameras and lighting come out cohesive."
};
function showHelp(key, x, y){
  const pop = document.getElementById("helppop");
  pop.textContent = HELP[key] || "";
  pop.style.display = "block";
  const w = 300;
  pop.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + "px";
  pop.style.top = (y + 16) + "px";
}
function hideHelp(){ document.getElementById("helppop").style.display = "none"; }
// Chips open their own popover (direct pointerdown listener). This global
// handler only dismisses when clicking away from a chip or the popover.
document.addEventListener("click", e => {
  if (e.target.classList && e.target.classList.contains("hq")) return;
  if (e.target.id !== "helppop") hideHelp();
});
// add a "?" chip to every label whose following control (or own text) maps
// to a help entry. Runs immediately since this script is at end of body.
(function attachHelpChips(){
  document.querySelectorAll("#side label").forEach(lab => {
    if (lab.querySelector(".hq")) return;
    // the control this label describes: one inside it, or the next element
    let ctrl = lab.querySelector("input,select");
    let sib = lab.nextElementSibling;
    while (!ctrl && sib) {
      if (/input|select/i.test(sib.tagName)) { ctrl = sib; break; }
      if (sib.tagName === "LABEL") break;  // next label = different control
      sib = sib.nextElementSibling;
    }
    let key = null;
    if (ctrl && ctrl.id && HELP[ctrl.id]) {
      key = ctrl.id;
    } else {
      // fall back to longest-matching help key in the label text, so
      // "chroma soften" matches chroma_soften, not soften
      const t = lab.textContent.toLowerCase();
      let best = "";
      for (const k in HELP) {
        const phrase = k.replace(/_/g, " ");
        if (t.includes(phrase) && phrase.length > best.length) { key = k; best = phrase; }
      }
    }
    if (key && HELP[key]) {
      const q = document.createElement("span");
      q.className = "hq"; q.dataset.k = key; q.textContent = "?";
      // Open on click, and stop the event so the document-level dismiss
      // handler (which closes the popover) doesn't fire for this same click.
      // Slider/checkbox labels contain an <output>/<input>, making the label
      // labelable; preventDefault stops the label forwarding the click to its
      // control, and stopPropagation stops the immediate re-close.
      q.addEventListener("click", ev => {
        ev.preventDefault();
        ev.stopPropagation();
        showHelp(key, ev.pageX, ev.pageY);
      });
      lab.appendChild(q);
    }
  });
})();

const sliders = ["grain","halation","soften","saturation","chroma_soften","weave","leak","flare","presence","flicker","corner_soften","age"];
const styles = __STYLES_JSON__;
const looks = __LOOKS_JSON__;
function setAll(d){
  const map = {look:"look",gauge:"gauge",codec:"codec",input_log:"input_log",
               lut:"lut",grain_plate:"grain_plate",print_stock:"print_stock"};
  for (const [k,id] of Object.entries(map))
    if (d[k] !== undefined && d[k] !== null && $(id)) $(id).value = d[k];
  $("ratio").value = d.ratio ? String(d.ratio) : "";
  for (const sname of sliders)
    if (d[sname] !== undefined && d[sname] !== null) $(sname).value = d[sname];
  $("bw").checked = !!d.bw; $("conform").checked = !!d.conform;
  $("vignette").checked = !d.no_vignette; $("curve").checked = !d.no_curve;
  $("depth10").checked = d.depth === 10;
}
function settings(){
  return {
    look: $("look").value, gauge: $("gauge").value, ratio: $("ratio").value,
    grain: $("grain").value, halation: $("halation").value, soften: $("soften").value,
    saturation: $("saturation").value, chroma_soften: $("chroma_soften").value,
    weave: $("weave").value, leak: $("leak").value, flare: $("flare").value,
    presence: $("presence").value, flicker: $("flicker").value,
    corner_soften: $("corner_soften").value, age: $("age").value,
    bw: $("bw").checked, conform: $("conform").checked,
    no_vignette: !$("vignette").checked, no_curve: !$("curve").checked,
    compare: $("compare").checked, depth: $("depth10").checked ? 10 : 8,
    input_log: $("input_log").value, lut: $("lut").value,
    print_stock: $("print_stock").value,
    grain_plate: $("grain_plate").value, codec: $("codec").value,
    outname: $("outname").value,
    t: $("scrub").value
  };
}
let timer = null, busy = false, queued = false;
function refresh(){
  sliders.forEach(s => $(s+"V").textContent = $(s).value);
  if (busy) { queued = true; return; }
  busy = true;
  const q = new URLSearchParams(settings()).toString();
  const img = new Image();
  img.onload = () => { $("prev").src = img.src; busy = false; if (queued){queued=false; refresh();} };
  img.onerror = () => { $("status").textContent = "preview failed — check paths"; busy = false; };
  img.src = "/preview?" + q + "&_=" + Date.now();
}
function schedule(){ clearTimeout(timer); timer = setTimeout(refresh, 180); }
document.querySelectorAll("input,select").forEach(el => {
  el.addEventListener("input", schedule); el.addEventListener("change", schedule);
});
const DEFAULTS = {look:"standard",gauge:"35mm",ratio:"",grain:7,halation:0.33,
  soften:0.55,saturation:0.88,chroma_soften:1.2,weave:0,leak:0,flare:0,
  presence:0.3,flicker:0,corner_soften:0,age:0,
  bw:false,depth:8,codec:"h264",print_stock:"",lut:"",grain_plate:"",input_log:""};
function styleSettings(name){
  const d = Object.assign({}, DEFAULTS, styles[name] || {});
  return {look:d.look,gauge:d.gauge,ratio:d.ratio||"",grain:d.grain,
    halation:d.halation,soften:d.soften,saturation:d.saturation,
    chroma_soften:d.chroma_soften,weave:d.weave,leak:d.leak,flare:d.flare,
    presence:d.presence,flicker:d.flicker,corner_soften:d.corner_soften,
    age:d.age,
    bw:d.bw,conform:false,no_vignette:false,no_curve:false,compare:false,
    depth:d.depth,input_log:"",lut:"",grain_plate:"",
    print_stock:d.print_stock||"",codec:d.codec,t:$("scrub").value,pw:240};
}
function applyStyle(name){
  const sdef = styles[name]; if (!sdef) return;
  setAll(Object.assign({}, DEFAULTS, sdef));
  document.querySelectorAll(".scard").forEach(c =>
    c.classList.toggle("sel", c.dataset.style === name));
  schedule();
}
function buildCards(){
  const wrap = $("cards");
  wrap.innerHTML = "";
  for (const name of Object.keys(styles)){
    const c = document.createElement("div");
    c.className = "scard"; c.dataset.style = name;
    c.innerHTML = "<img alt=''><div>" + name + "</div>";
    c.onclick = () => applyStyle(name);
    wrap.appendChild(c);
  }
  loadCardThumbs();
}
async function loadCardThumbs(){
  // sequential so the main preview keeps priority
  for (const c of document.querySelectorAll(".scard")){
    const q = new URLSearchParams(styleSettings(c.dataset.style)).toString();
    const img = c.querySelector("img");
    await new Promise(res => {
      const i = new Image();
      i.onload = () => { img.src = i.src; res(); };
      i.onerror = res;
      i.src = "/preview?" + q;
    });
  }
}
// any manual tweak deselects the highlighted card
document.querySelectorAll("#side input, #side select").forEach(el =>
  el.addEventListener("input", () =>
    document.querySelectorAll(".scard.sel").forEach(c => c.classList.remove("sel"))));
async function post(url, body){
  $("status").textContent = "working…";
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  return r.json();
}
$("loadlook").addEventListener("change", () => {
  const d = looks[$("loadlook").value]; if (!d) return;
  setAll(d); schedule();
});
$("saveBtn").onclick = async () => {
  const body = settings(); body.lookname = $("lookname").value;
  const r = await post("/save", body);
  $("status").textContent = r.ok ? "look saved: " + r.path : "save failed: " + r.error;
};
$("renderBtn").onclick = async () => {
  $("rendered").hidden = true;
  $("renderBtn").disabled = true;
  $("progwrap").hidden = false;
  $("progfill").style.width = "0%";
  $("status").textContent = "starting render…";
  await post("/render", settings());
  const poll = setInterval(async () => {
    const s = await (await fetch("/status")).json();
    if (s.rendering) {
      const p = s.pct || 0;
      $("progfill").style.width = p + "%";
      $("status").textContent = "rendering full clip… " + p + "%";
    } else {
      clearInterval(poll);
      $("renderBtn").disabled = false;
      if (s.error) {
        $("progwrap").hidden = true;
        $("status").textContent = "render failed: " + s.error;
      } else {
        $("progfill").style.width = "100%";
        setTimeout(() => { $("progwrap").hidden = true; }, 600);
        $("status").textContent = "";
        $("rname").textContent = s.done;
        $("rendered").hidden = false;
        $("prev").src = "/result_frame?_=" + Date.now();
      }
    }
  }, 700);
};
try {
  if (localStorage.getItem("filmify_guide_done")) $("guide").hidden = true;
} catch(e) {}
$("gx").onclick = () => {
  $("guide").hidden = true;
  try { localStorage.setItem("filmify_guide_done", "1"); } catch(e) {}
};
const HAS_CLIP_INIT = __HAS_CLIP__;
function showEditor(name){
  $("import").hidden = true;
  $("cards").hidden = false; $("prev").hidden = false; $("scrubrow").hidden = false;
  if (name) document.querySelector(".fn").textContent = name;
  try { if (!localStorage.getItem("filmify_guide_done")) $("guide").hidden = false; } catch(e){ $("guide").hidden = false; }
  buildCards();
  refresh();
  refreshDest();
}
function showImport(){
  $("import").hidden = false;
  $("cards").hidden = true; $("prev").hidden = true; $("scrubrow").hidden = true;
  $("guide").hidden = true;
}
async function loadPath(path){
  // If we have no path, the server is about to open the OS file picker —
  // tell the user to look for it (it can surface in front of the browser).
  $("importmsg").textContent = path ? "loading\u2026"
    : "opening the file picker\u2026 if you don't see it, check your taskbar or behind this window";
  try {
    const r = await (await fetch("/load", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:path||""})})).json();
    if (r.ok){ showEditor(r.name); }
    else if (r.cancel){ $("importmsg").textContent = ""; }
    else { $("importmsg").textContent = r.error || "couldn't load that file"; }
  } catch(e){ $("importmsg").textContent = "load failed"; }
}
$("chooseBtn").onclick = (e) => { e.stopPropagation(); loadPath(""); };   // server opens the native picker
const dz = $("dropzone");
["dragenter","dragover"].forEach(ev => dz.addEventListener(ev, e => {e.preventDefault(); dz.classList.add("drag");}));
["dragleave","drop"].forEach(ev => dz.addEventListener(ev, e => {e.preventDefault(); dz.classList.remove("drag");}));
dz.addEventListener("drop", e => {
  // A browser never exposes a dropped file's real disk path (security), and
  // the server needs a real path to process it — so a drop can't load the
  // file directly. Instead we treat a drop as a shortcut to the picker,
  // opened to a sensible place. Honest and always reliable.
  loadPath("");
});
dz.addEventListener("click", () => loadPath(""));

async function refreshDest(){
  try { const r = await (await fetch("/destdir")).json();
    $("destpath").textContent = r.dir || "next to your clip"; } catch(e){}
}
$("destBtn").onclick = async () => {
  const r = await (await fetch("/setdest",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).json();
  if (r.ok){ $("destpath").textContent = r.dir; }
};
$("revealBtn").onclick = () => { fetch("/reveal").catch(()=>{}); };
$("batchBtn").onclick = async () => {
  const body = settings();
  body.match = $("matchbox").checked;
  body.folder = "";
  const r = await (await fetch("/batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json();
  if (!r.ok) { if(!r.cancel) $("batchstat").textContent = "couldn't start"; return; }
  $("batchstat").hidden = false; $("batchwrap").hidden = false;
  $("batchBtn").disabled = true; $("renderBtn").disabled = true;
  const poll = setInterval(async () => {
    const s = await (await fetch("/status")).json();
    if (s.batch && s.rendering) {
      const overall = s.b_total ? Math.round((s.b_done + (s.pct||0)/100) / s.b_total * 100) : 0;
      $("batchfill").style.width = overall + "%";
      $("batchstat").textContent = "clip " + (s.b_done+1) + " of " + s.b_total + " \u2014 " + (s.b_name||"") + " (" + (s.pct||0) + "%)";
    } else if (s.batch && !s.rendering) {
      clearInterval(poll);
      $("batchfill").style.width = "100%";
      $("batchBtn").disabled = false; $("renderBtn").disabled = false;
      $("batchstat").innerHTML = "\u2713 " + (s.b_name||"done") + " \u2014 saved to a new folder &nbsp;<button id=\'brev\' style=\'width:auto;padding:3px 10px;font-size:11px\'>Show in folder</button>";
      const b = document.getElementById("brev");
      if (b) b.onclick = () => { fetch("/reveal").catch(()=>{}); };
    }
  }, 800);
};

if (HAS_CLIP_INIT) showEditor(); else showImport();
setInterval(() => { fetch("/alive").catch(()=>{}); }, 8000);
fetch("/alive").catch(()=>{});
</script></body></html>"""


def _ui_args(base, q):
    """Build an args namespace for a preview/render request from the panel's
    settings, on top of the launch-time args."""
    a = argparse.Namespace(**vars(base))
    fl = lambda k, d=0.0: float(q.get(k, d) or d)
    a.look = q.get("look", "standard")
    a.gauge = q.get("gauge", "35mm")
    a.ratio = float(q["ratio"]) if q.get("ratio") else None
    a.grain = int(float(q.get("grain", 7)))
    a.halation = fl("halation", 0.33)
    a.soften = fl("soften", 0.55)
    a.saturation = fl("saturation", 0.88)
    a.chroma_soften = fl("chroma_soften", 1.2)
    a.weave = fl("weave")
    a.leak = fl("leak")
    a.flare = fl("flare")
    a.bw = str(q.get("bw")) in ("true", "True", "1")
    a.conform = str(q.get("conform")) in ("true", "True", "1")
    a.no_vignette = str(q.get("no_vignette")) in ("true", "True", "1")
    a.no_curve = str(q.get("no_curve")) in ("true", "True", "1")
    a.compare = str(q.get("compare", "true")) in ("true", "True", "1")
    a.depth = int(q.get("depth", 8))
    a.codec = q.get("codec", "h264")
    a.input_log = q.get("input_log") or None
    a.lut = Path(q["lut"]) if q.get("lut") else None
    a.grain_plate = Path(q["grain_plate"]) if q.get("grain_plate") else None
    a.plate_opacity = None
    a.print_stock = q.get("print_stock") or None
    a.no_hwaccel = False
    a.presence = float(q["presence"]) if q.get("presence") not in (None, "") else None
    a.flicker = fl("flicker")
    a.corner_soften = fl("corner_soften")
    a.age = fl("age")
    a.no_protect_skin = str(q.get("no_protect_skin")) in ("true", "True", "1")
    a._match = None
    return a


_UI_LOG_LUTS = {}


def _ui_loglut(a):
    if not a.input_log:
        a._loglut = None
        return None
    name = str(a.input_log).lower()
    if name in LOG_PRESETS:
        if name not in _UI_LOG_LUTS:
            _UI_LOG_LUTS[name] = make_log_lut(name)
        a._loglut = ("1d", _UI_LOG_LUTS[name])
    else:
        p = Path(a.input_log)
        a._loglut = ("3d", p) if p.exists() else None
    return None


def run_ui(args) -> None:
    """Serve the control panel on localhost and open it in the browser."""
    import http.server
    import json as _json
    import threading
    import urllib.parse

    src = args.input   # may be None: panel opens in import state
    cur = {"src": src, "info": probe(src) if src else None, "outdir": None}
    state = {"rendering": False, "done": None, "error": None, "pct": 0,
             "batch": False, "b_total": 0, "b_done": 0, "b_name": "",
             "b_outdir": None}

    def pick_file_dialog():
        """Open the OS-native file picker and return a path, or '' on cancel.
        Forced to the foreground so it surfaces over a fullscreen browser."""
        try:
            if sys.platform == "darwin":
                out = run(
                    ["osascript",
                     "-e", 'tell application "System Events" to activate',
                     "-e", 'POSIX path of (choose file with prompt '
                           '"filmify — choose a video clip" of type '
                           '{"public.movie","public.video"})'],
                    capture_output=True, text=True, timeout=300)
                return out.stdout.strip()
            if os.name == "nt":
                # Force the dialog to the foreground via the Win32 API — a
                # TopMost owner form alone doesn't reliably beat the browser
                # window. We create an owner form, push it to the front with
                # SetForegroundWindow, and parent the dialog to it.
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "Add-Type -AssemblyName System.Drawing;"
                    'Add-Type @"\n'
                    'using System;using System.Runtime.InteropServices;\n'
                    'public class FG{\n'
                    '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);\n'
                    '[DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);\n'
                    '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);\n'
                    '}\n'
                    '"@;'
                    '$o=New-Object System.Windows.Forms.Form;'
                    '$o.TopMost=$true;$o.ShowInTaskbar=$false;'
                    '$o.FormBorderStyle="None";$o.Width=1;$o.Height=1;'
                    '$o.StartPosition="Manual";$o.Location='
                    "New-Object System.Drawing.Point(-2000,-2000);"
                    '$o.Show();$o.Activate();'
                    '[FG]::ShowWindow($o.Handle,5)|Out-Null;'
                    '[FG]::BringWindowToTop($o.Handle)|Out-Null;'
                    '[FG]::SetForegroundWindow($o.Handle)|Out-Null;'
                    '$f=New-Object System.Windows.Forms.OpenFileDialog;'
                    "$f.Filter='Video|*.mp4;*.mov;*.mkv;*.avi;*.m4v;*.webm;*.mts|All|*.*';"
                    '$r=$f.ShowDialog($o);$o.Close();'
                    "if($r -eq 'OK'){$f.FileName}")
                out = run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                          capture_output=True, text=True, timeout=300)
                return out.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            return ""
        return ""

    def pick_folder_dialog():
        """Native folder picker (output destination), forced to the front."""
        try:
            if sys.platform == "darwin":
                out = run(
                    ["osascript",
                     "-e", 'tell application "System Events" to activate',
                     "-e", 'POSIX path of (choose folder with prompt '
                           '"filmify — choose where to save renders")'],
                    capture_output=True, text=True, timeout=300)
                return out.stdout.strip()
            if os.name == "nt":
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "Add-Type -AssemblyName System.Drawing;"
                    'Add-Type @"\n'
                    'using System;using System.Runtime.InteropServices;\n'
                    'public class FG2{\n'
                    '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);\n'
                    '[DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);\n'
                    '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);\n'
                    '}\n'
                    '"@;'
                    '$o=New-Object System.Windows.Forms.Form;'
                    '$o.TopMost=$true;$o.ShowInTaskbar=$false;'
                    '$o.FormBorderStyle="None";$o.Width=1;$o.Height=1;'
                    '$o.StartPosition="Manual";$o.Location='
                    "New-Object System.Drawing.Point(-2000,-2000);"
                    '$o.Show();$o.Activate();'
                    '[FG2]::ShowWindow($o.Handle,5)|Out-Null;'
                    '[FG2]::BringWindowToTop($o.Handle)|Out-Null;'
                    '[FG2]::SetForegroundWindow($o.Handle)|Out-Null;'
                    '$f=New-Object System.Windows.Forms.FolderBrowserDialog;'
                    "$f.Description='filmify - choose where to save renders';"
                    '$r=$f.ShowDialog($o);$o.Close();'
                    "if($r -eq 'OK'){$f.SelectedPath}")
                out = run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                          capture_output=True, text=True, timeout=300)
                return out.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            return ""
        return ""

    def fname():
        return cur["src"].name if cur["src"] else ""

    def dur():
        return (cur["info"]["duration"] or 10.0) if cur["info"] else 10.0

    page = (UI_PAGE
            .replace("__VERSION__", __version__)
            .replace("__FILENAME__", html.escape(fname()))
            .replace("__DUR__", f"{dur():.0f}")
            .replace("__STYLE_OPTS__", "".join(
                f'<option value="{s}">{s}</option>' for s in sorted(STYLES)))
            .replace("__STYLES_JSON__", json.dumps(STYLES)))
    looks = {}
    look_dir = (src.parent if src else Path.cwd())
    for j in sorted(look_dir.glob("*.json")):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
            if isinstance(d, dict) and "filmify_version" in d:
                looks[j.name] = d
        except (OSError, json.JSONDecodeError):
            continue
    page = (page
            .replace("__LOOK_OPTS__", "".join(
                f'<option value="{html.escape(n)}">{html.escape(n)}</option>'
                for n in looks))
            .replace("__LOOKS_JSON__", json.dumps(looks))
            .replace("__HAS_CLIP__", "true" if cur["src"] else "false"))

    def preview_jpeg(q):
        if not cur["src"]:
            raise RuntimeError("no clip loaded")
        info = cur["info"]
        a = _ui_args(args, q)
        _ui_loglut(a)
        if a.lut and not a.lut.exists():
            a.lut = None
        if a.grain_plate and not a.grain_plate.exists():
            a.grain_plate = None
        d = info["duration"] or 10.0
        t = max(0.0, min(d * 0.98, d * float(q.get("t", 40)) / 100.0))
        # Proxy: scale FIRST, then run every filter at proxy resolution —
        # the difference between sluggish and plugin-instant on 4K footage.
        pw = min(max(120, int(float(q.get("pw", 960)))), 1280, info["width"])
        ph = max(2, int(info["height"] * pw / info["width"] / 2) * 2)
        pinfo = dict(info, width=pw, height=ph)
        graph = build_filtergraph(a, pinfo)
        graph = graph.replace("[0:v]", f"[0:v]scale={pw}:{ph},", 1)
        cmd = [FFMPEG, "-v", "error", "-ss", f"{t:.2f}", "-i", str(cur["src"])]
        if a.grain_plate:
            cmd += ["-stream_loop", "-1", "-i", str(a.grain_plate)]
        cmd += ["-filter_complex", graph, "-map", "[vout]", "-frames:v", "1",
                "-f", "image2", "-c:v", "mjpeg", "-q:v", "4", "pipe:1"]
        out = run(cmd, capture_output=True)
        if out.returncode != 0 or not out.stdout:
            raise RuntimeError(out.stderr.decode("utf-8", "replace")[-400:])
        return out.stdout

    def do_render(q):
        if not cur["src"]:
            state.update(rendering=False, error="no clip loaded")
            return
        s = cur["src"]
        a = _ui_args(args, q)
        _ui_loglut(a)
        a.compare = False
        a.preview = None
        a.dry_run = False
        ext2 = ".mp4" if a.codec == "h264" else ".mov"
        outdir = cur["outdir"] or s.parent
        # Output name: user-supplied (sanitized) or the default <name>_film.
        raw = (q.get("outname") or "").strip()
        if raw:
            stem = Path(raw).stem  # drop any extension/path the user typed
            stem = re.sub(r'[<>:"/\\|?*]', "_", stem) or (s.stem + "_film")
        else:
            stem = s.stem + "_film"
        out = outdir / (stem + ext2)
        # Don't silently overwrite: if it exists, append -2, -3, …
        n = 2
        while out.exists():
            out = outdir / (f"{stem}-{n}" + ext2)
            n += 1
        state.update(rendering=True, done=None, error=None, pct=0)
        try:
            res = render(s, out, a,
                         progress_cb=lambda p: state.update(pct=p))
            if res["ok"]:
                state.update(rendering=False, done=str(out), pct=100)
            else:
                state.update(rendering=False, error=res["error"])
        except Exception as exc:  # noqa: BLE001 — surface anything to the panel
            state.update(rendering=False, error=str(exc))

    VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mts",
                  ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg"}

    def do_batch(q, folder):
        """Process every video in a folder with the current look, into a
        timestamped filmify_<when> subfolder. Set-it-and-walk-away."""
        a = _ui_args(args, q)
        _ui_loglut(a)
        a.compare = False
        a.preview = None
        a.dry_run = False
        do_match = str(q.get("match")) in ("true", "True", "1")
        src_dir = Path(folder)
        files = sorted(f for f in src_dir.iterdir()
                       if f.is_file() and f.suffix.lower() in VIDEO_EXTS
                       and "filmify_" not in f.parent.name)
        if not files:
            state.update(rendering=False, error="no videos found in that folder")
            return
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        outdir = src_dir / f"filmify_{stamp}"
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            state.update(rendering=False, error=str(exc))
            return
        ext2 = ".mp4" if a.codec == "h264" else ".mov"

        # Shot matching: measure all clips, nudge each toward the batch median
        nudges = {}
        if do_match and len(files) > 1:
            stats = {}
            for f in files:
                state.update(b_name=f"measuring {f.name}")
                m = measure_clip(f)
                if m:
                    stats[f] = m
            if len(stats) > 1:
                med = tuple(sorted(v[i] for v in stats.values())[len(stats) // 2]
                            for i in range(3))
                clamp = lambda x, c: max(-c, min(c, x))
                for f, (y, u, v) in stats.items():
                    nudges[f] = (clamp((med[0] - y) / 255.0 * 0.7, 0.10),
                                 clamp((med[2] - v) / 255.0 * 1.1, 0.08),
                                 clamp((med[1] - u) / 255.0 * 1.1, 0.08))

        state.update(rendering=True, done=None, error=None, pct=0,
                     batch=True, b_total=len(files), b_done=0,
                     b_outdir=str(outdir))
        ok = 0
        for i, f in enumerate(files):
            state.update(b_name=f.name, b_done=i, pct=0)
            a._match = nudges.get(f)
            out = outdir / (f.stem + "_film" + ext2)
            try:
                res = render(f, out, a,
                             progress_cb=lambda p: state.update(pct=p))
                if res["ok"]:
                    ok += 1
            except Exception:  # noqa: BLE001 — keep going; one bad clip≠stop
                pass
        state.update(rendering=False, batch=True, b_done=len(files),
                     pct=100, done=str(outdir),
                     b_name=f"{ok} of {len(files)} clips done")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(200, "text/html; charset=utf-8", page.encode())
            elif self.path.startswith("/preview"):
                q = dict(urllib.parse.parse_qsl(
                    urllib.parse.urlsplit(self.path).query))
                try:
                    self._send(200, "image/jpeg", preview_jpeg(q))
                except Exception as exc:  # noqa: BLE001
                    self._send(500, "text/plain", str(exc).encode())
            elif self.path.startswith("/result_frame"):
                if state["done"]:
                    try:
                        p = Path(state["done"])
                        d = probe(p)["duration"] or 1.0
                        self._send(200, "image/jpeg",
                                   run(
                                       [FFMPEG, "-v", "error",
                                        "-ss", f"{d * 0.4:.2f}", "-i", str(p),
                                        "-frames:v", "1", "-vf", "scale=960:-2",
                                        "-f", "image2", "-c:v", "mjpeg",
                                        "-q:v", "4", "pipe:1"],
                                       capture_output=True).stdout or b"")
                    except (RuntimeError, OSError) as exc:
                        self._send(500, "text/plain", str(exc).encode())
                else:
                    self._send(404, "text/plain", b"no render yet")
            elif self.path == "/status":
                self._send(200, "application/json",
                           _json.dumps(state).encode())
            elif self.path == "/alive":
                self.server._last_ping = __import__("time").time()
                self._send(200, "application/json", b'{"ok":true}')
            elif self.path == "/loaded":
                # tell the page what clip (if any) is active
                self._send(200, "application/json", _json.dumps(
                    {"name": fname(), "dur": dur() if cur["src"] else 0}).encode())
            elif self.path == "/destdir":
                where = cur["outdir"] or (cur["src"].parent if cur["src"] else None)
                self._send(200, "application/json", _json.dumps(
                    {"dir": str(where) if where else ""}).encode())
            elif self.path == "/reveal":
                if state["done"]:
                    reveal_in_file_manager(Path(state["done"]))
                    self._send(200, "application/json", b'{"ok":true}')
                else:
                    self._send(404, "application/json", b'{"ok":false}')
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            q = _json.loads(self.rfile.read(n) or b"{}")
            q = {k: ("" if v is None else v) for k, v in q.items()}
            if self.path == "/load":
                # open the native picker (or accept a dropped path), probe it,
                # make it the active clip — no restart needed
                p = (q.get("path") or "").strip() or pick_file_dialog()
                if not p:
                    self._send(200, "application/json", b'{"ok": false, "cancel": true}')
                    return
                path = Path(p)
                if not path.exists():
                    self._send(200, "application/json", _json.dumps(
                        {"ok": False, "error": f"not found: {p}"}).encode())
                    return
                try:
                    cur["src"] = path
                    cur["info"] = probe(path)
                    self._send(200, "application/json", _json.dumps(
                        {"ok": True, "name": path.name,
                         "dur": cur["info"]["duration"] or 10.0}).encode())
                except RuntimeError as exc:
                    self._send(200, "application/json", _json.dumps(
                        {"ok": False, "error": str(exc)}).encode())
            elif self.path == "/save":
                try:
                    if not cur["src"]:
                        raise RuntimeError("load a clip first")
                    a = _ui_args(args, q)
                    name = Path(str(q.get("lookname") or "myfilm")).name
                    if not name.endswith(".json"):
                        name += ".json"
                    a.save_look = cur["src"].parent / name
                    save_look_file(a)
                    self._send(200, "application/json", _json.dumps(
                        {"ok": True, "path": str(a.save_look)}).encode())
                except Exception as exc:  # noqa: BLE001
                    self._send(200, "application/json", _json.dumps(
                        {"ok": False, "error": str(exc)}).encode())
            elif self.path == "/render":
                if not state["rendering"]:
                    threading.Thread(target=do_render, args=(q,),
                                     daemon=True).start()
                self._send(200, "application/json", b'{"ok": true}')
            elif self.path == "/batch":
                if state["rendering"]:
                    self._send(200, "application/json", b'{"ok": false}')
                    return
                folder = (q.get("folder") or "").strip() or pick_folder_dialog()
                if not folder or not Path(folder).is_dir():
                    self._send(200, "application/json",
                               b'{"ok": false, "cancel": true}')
                    return
                threading.Thread(target=do_batch, args=(q, folder),
                                 daemon=True).start()
                self._send(200, "application/json", _json.dumps(
                    {"ok": True, "folder": folder}).encode())
            elif self.path == "/setdest":
                p = (q.get("path") or "").strip() or pick_folder_dialog()
                if p and Path(p).is_dir():
                    cur["outdir"] = Path(p)
                    self._send(200, "application/json", _json.dumps(
                        {"ok": True, "dir": str(cur["outdir"])}).encode())
                else:
                    self._send(200, "application/json", b'{"ok": false}')
            else:
                self._send(404, "text/plain", b"not found")

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"filmify panel: {url}")
    print("(Ctrl+C here closes it, or just close the browser tab)")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass

    # When launched without a terminal (the Mac .app / silent launcher),
    # there's no Ctrl+C to stop the server — so it exits on its own once the
    # browser tab goes away. The page pings /alive periodically; if the
    # pings stop for a grace period, shut down.
    import threading
    import time as _time

    def watchdog():
        while True:
            _time.sleep(20)
            last = getattr(httpd, "_last_ping", 0)
            if last and (_time.time() - last) > 30:
                httpd.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\npanel closed.")


def main() -> None:
    if len(sys.argv) == 1:
        print(QUICKSTART)
        return
    ap = argparse.ArgumentParser(
        description="Process digital video to look like physical film.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("input", type=Path, nargs="?", default=None,
                    help="input video file, or a folder to batch-process "
                         "(optional with --ui: import from the panel instead)")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="output file (or output folder in batch mode)")
    ap.add_argument("-V", "--version", action="version",
                    version=f"filmify {__version__}")
    ap.add_argument("--look", choices=LOOKS, default="standard",
                    help="overall intensity preset")
    ap.add_argument("--conform", action="store_true",
                    help="convert to 24 fps with simulated 180-degree shutter blur")
    ap.add_argument("--preview", nargs="?", const=5.0, type=float, default=None,
                    metavar="SECONDS",
                    help="render only the first N seconds (default 5) with a fast "
                         "encode, for quick look iteration")
    ap.add_argument("--compare", action="store_true",
                    help="split-screen output: left half original, right half "
                         "graded, with a divider line — for dialing in a look "
                         "(pairs well with --preview)")
    ap.add_argument("--print-stock", choices=sorted(PRINT_STOCKS), default=None,
                    help="built-in subtractive print-film color engine "
                         "(density curves + interlayer crosstalk); replaces "
                         "the built-in curve and split tone; your --lut "
                         "still overrides it")
    ap.add_argument("--lut", type=Path, default=None, metavar="FILE.cube",
                    help="apply a film-stock 3D LUT (.cube); disables built-in split tone")
    ap.add_argument("--grain-plate", type=Path, default=None, metavar="FILE",
                    help="overlay a real scanned grain plate (video file, looped)")
    ap.add_argument("--plate-opacity", type=float, default=None, metavar="0-1",
                    help="grain plate blend opacity override")
    ap.add_argument("--grain", type=int, default=None, metavar="0-20",
                    help="synthesized grain strength override (0 disables)")
    ap.add_argument("--halation", type=float, default=None, metavar="0-1",
                    help="halation/bloom strength override (0 disables)")
    ap.add_argument("--soften", type=float, default=None, metavar="0-1.5",
                    help="softening strength override (0 disables)")
    ap.add_argument("--saturation", type=float, default=None, metavar="0-2",
                    help="saturation override (1 = unchanged)")
    ap.add_argument("--bw", action="store_true",
                    help="black & white film mode: panchromatic-weighted mono, "
                         "neutral halation, heavier grain")
    ap.add_argument("--chroma-soften", type=float, default=None, metavar="0-3",
                    help="chroma-only blur strength override (0 disables); "
                         "film color resolves softer than its luminance")
    ap.add_argument("--weave", type=float, default=0.0, metavar="PX",
                    help="gate weave: slow frame drift in pixels (try 1-2; 0 disables)")
    ap.add_argument("--codec", choices=("h264", "prores", "dnxhr"),
                    default="h264",
                    help="output codec: h264 for delivery/finish pass; "
                         "prores or dnxhr (both .mov, PCM audio) for "
                         "edit-friendly graded dailies")
    ap.add_argument("--look-file", type=Path, default=None, metavar="FILE.json",
                    help="load project look settings from a JSON file "
                         "(explicit flags still override)")
    ap.add_argument("--save-look", type=Path, default=None, metavar="FILE.json",
                    help="save the effective settings to a JSON look file "
                         "for reuse across shoot days and the finish pass")
    ap.add_argument("--no-curve", action="store_true",
                    help="disable the built-in filmic tone curve (e.g. when your LUT includes one)")
    ap.add_argument("--no-vignette", action="store_true",
                    help="disable the vignette")
    ap.add_argument("--input-log", type=str, default=None, metavar="CURVE|FILE.cube",
                    help="develop log footage first: 'slog3' (Sony), 'vlog' "
                         "(Panasonic), 'cineon' (generic), or a path to your "
                         "camera maker's official log-to-709 3D .cube LUT "
                         "(use that for C-Log, Apple Log, D-Log, etc.)")
    ap.add_argument("--style", choices=sorted(STYLES), default=None,
                    help="named recipe that expands to a flag set "
                         "(individual flags still override): " +
                         ", ".join(sorted(STYLES)))
    ap.add_argument("--ui", action="store_true",
                    help="open the control panel in your browser: sliders "
                         "for every parameter, instant frame preview with "
                         "A/B split, save-look and render buttons")
    ap.add_argument("--flare", nargs="?", const=0.35, type=float, default=0.0,
                    metavar="0-1",
                    help="anamorphic streak flare: bright lights grow a "
                         "horizontal blue-tinted line (off by default; "
                         "bare flag = 0.35)")
    ap.add_argument("--ratio", type=float, default=None, metavar="R",
                    help="center-crop to a cinema aspect ratio: 2.39 (Scope), "
                         "2.2 (70mm Todd-AO), 2.76 (Ultra Panavision), "
                         "1.85 (flat widescreen)")
    ap.add_argument("--gauge", choices=("16mm", "35mm", "70mm"), default="35mm",
                    help="film gauge character: 16mm = chunky grain and "
                         "softer, 35mm = standard, 70mm = fine grain and "
                         "cleaner (the large-format epic look)")
    ap.add_argument("--presence", type=float, default=None, metavar="0-1",
                    help="mid-frequency local contrast (anti-flatness) "
                         "override; 0 disables")
    ap.add_argument("--flicker", nargs="?", const=0.5, type=float, default=0.0,
                    metavar="0-1",
                    help="film density flicker: subtle irregular exposure "
                         "variance (off by default; bare flag = 0.5)")
    ap.add_argument("--corner-soften", type=float, default=0.0, metavar="0-3",
                    help="field curvature: sharp center, progressively "
                         "softer corners, like vintage glass (0 disables)")
    ap.add_argument("--age", nargs="?", const=0.4, type=float, default=0.0,
                    metavar="0-1",
                    help="print damage: dust specks plus an occasional "
                         "wandering scratch line (off by default)")
    ap.add_argument("--no-protect-skin", action="store_true",
                    help="disable skin-tone protection during desaturation")
    ap.add_argument("--leak", nargs="?", const=0.3, type=float, default=0.0,
                    metavar="0-1",
                    help="intermittent warm light leak from the frame edge "
                         "(off by default; bare flag = 0.3)")
    ap.add_argument("--depth", type=int, choices=(8, 10), default=8,
                    help="internal processing bit depth; 10 reduces banding "
                         "in gradients and survives further grading better "
                         "(pairs with --codec prores or dnxhr)")
    ap.add_argument("--match", action="store_true",
                    help="batch shot matching: measure every clip, nudge each "
                         "gently toward the batch median exposure and white "
                         "balance before applying the look — mixed cameras "
                         "come out at the same level, not just the same look")
    ap.add_argument("--no-hwaccel", action="store_true",
                    help="disable hardware-accelerated H.264 encoding even if "
                         "a GPU encoder is available (use software libx264)")
    ap.add_argument("--no-tonemap", action="store_true",
                    help="don't auto tone-map HDR (HLG/PQ) sources to Rec.709")
    ap.add_argument("--force", action="store_true",
                    help="re-render batch outputs that already exist")
    ap.add_argument("--no-report", action="store_true",
                    help="skip writing/opening the HTML processing report")
    ap.add_argument("--crf", type=int, default=17,
                    help="x264 quality (lower = better; grain needs bitrate)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the ffmpeg command without running it")
    args = ap.parse_args()

    # Windows consoles/redirects can use legacy code pages that choke on
    # characters like ° — degrade gracefully instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    global FFMPEG, FFPROBE
    FFMPEG = find_tool("ffmpeg")
    FFPROBE = find_tool("ffprobe")
    for name, hit in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)):
        if hit is None:
            sys.exit(
                f"error: {name} not found.\n"
                f"  Windows: winget install ffmpeg   (or drop {name}.exe next to filmify.py)\n"
                f"  macOS  : brew install ffmpeg"
            )
    if args.input is None and not args.ui:
        sys.exit("error: need an input file or folder (or use --ui to open "
                 "the panel and import one)")
    if args.input is not None and not args.input.exists():
        sys.exit(f"error: {args.input} not found")
    for opt in ("lut", "grain_plate"):
        f = getattr(args, opt)
        if f and not f.exists():
            sys.exit(f"error: {f} not found")

    if args.look_file:
        apply_look_file(args, ap)
    if args.style:
        apply_style(args, ap)
    if args.save_look:
        save_look_file(args)

    if args.ui:
        if args.input is not None and args.input.is_dir():
            sys.exit("error: --ui needs a single clip (or none — you can "
                     "import one from the panel). For a folder, drop the "
                     "--ui flag to batch it.")
        run_ui(args)
        return

    args._loglut = None
    _loglut_tmp = None
    if args.input_log:
        name = str(args.input_log).lower()
        if name in LOG_PRESETS:
            _loglut_tmp = make_log_lut(name)
            args._loglut = ("1d", _loglut_tmp)
        else:
            lp = Path(args.input_log)
            if not lp.exists():
                sys.exit(f"error: log LUT not found: {lp} "
                         f"(presets: {', '.join(LOG_PRESETS)})")
            args._loglut = ("3d", lp)

    if args.compare:
        suffix = "_compare"
    elif args.preview:
        suffix = "_preview"
    else:
        suffix = "_film"
    ext = ".mp4" if args.codec == "h264" else ".mov"
    print(f"filmify {__version__}\n")

    results = []
    if args.input.is_dir():
        files = sorted(
            f for f in args.input.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS
            # don't reprocess our own outputs on a rerun
            and not f.stem.endswith(("_film", "_preview", "_compare"))
        )
        if not files:
            sys.exit(f"error: no video files found in {args.input}")
        outdir = args.output or (args.input / "filmified")
        if outdir.exists() and not outdir.is_dir():
            sys.exit(f"error: {outdir} exists and is not a folder")
        outdir.mkdir(parents=True, exist_ok=True)
        print(f"batch : {len(files)} file(s) → {outdir}\n")
        nudges = {}
        if args.match and len(files) > 1:
            print("match : measuring clips…")
            stats = {}
            for f in files:
                m = measure_clip(f)
                if m:
                    stats[f] = m
            if len(stats) > 1:
                med = tuple(
                    sorted(v[i] for v in stats.values())[len(stats) // 2]
                    for i in range(3))
                clamp = lambda x, c: max(-c, min(c, x))
                for f, (y, u, v) in stats.items():
                    br = clamp((med[0] - y) / 255.0 * 0.7, 0.10)
                    bm = clamp((med[1] - u) / 255.0 * 1.1, 0.08)
                    rm = clamp((med[2] - v) / 255.0 * 1.1, 0.08)
                    nudges[f] = (br, rm, bm)
                    print(f"match : {f.name}: exposure {br:+.3f}, "
                          f"r {rm:+.3f}, b {bm:+.3f}")
            print()
        skipped = 0
        for i, f in enumerate(files, 1):
            outp = outdir / (f.stem + suffix + ext)
            if outp.exists() and not args.force:
                print(f"[{i}/{len(files)}] skip (already rendered): {outp.name}")
                skipped += 1
                continue
            print(f"[{i}/{len(files)}]")
            args._match = nudges.get(f)
            results.append(render(f, outp, args))
        args._match = None
        if skipped:
            print(f"\nskipped {skipped} already-rendered clip(s) — use --force to redo\n")
        if not results:
            print("nothing to do.")
            return
        report_dir = outdir
    else:
        out = args.output or args.input.with_name(args.input.stem + suffix + ext)
        if args.output and args.codec != "h264" and out.suffix.lower() not in (".mov", ".mxf"):
            out = out.with_suffix(".mov")
            print(f"note  : {args.codec} needs a .mov container — output is {out.name}")
        results.append(render(args.input, out, args))
        report_dir = out.parent

    ok_n = sum(1 for r in results if r["ok"])
    summary = f"{ok_n}/{len(results)} clip{'s' if len(results) != 1 else ''} ✓"
    if not args.dry_run and not args.no_report:
        report = report_dir / "filmify_report.html"
        try:
            write_report(results, args, report)
            summary += f" · report: {report}"
            try:
                webbrowser.open(report.resolve().as_uri())
            except Exception:
                pass  # headless/odd environments: the file is still there
        except OSError as exc:
            print(f"note  : couldn't write report: {exc}")
    print(summary)
    if _loglut_tmp:
        try:
            _loglut_tmp.unlink()
        except OSError:
            pass
    if ok_n < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
