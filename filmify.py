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
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

__version__ = "0.10.0"

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

A report with before/after thumbnails opens in your browser after each run.
Full options: python filmify.py --help
"""

# Settings persisted in a project look file (--save-look / --look-file)
LOOK_KEYS = [
    "look", "bw", "conform", "weave", "grain", "halation", "soften",
    "saturation", "chroma_soften", "plate_opacity", "no_curve",
    "no_vignette", "crf", "codec", "lut", "grain_plate",
    "input_log", "leak", "depth",
]

# Resolved at startup by find_tool(); plain names work as a fallback.
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
_TIP_SHOWN = False


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
        curve="0/0.01 0.22/0.2 0.5/0.51 0.8/0.825 0.93/0.925 1/0.965",
    ),
    # contrast concentrated in the midtones — classic print-stock snap
    "standard": dict(
        soften=0.55, saturation=0.88, halation=0.33, halation_thresh=0.78,
        grain=7, plate_opacity=0.42, vignette="PI/6", warmth=0.06, chroma=1.2,
        curve="0/0.015 0.15/0.12 0.35/0.33 0.5/0.52 0.72/0.78 0.92/0.915 1/0.955",
    ),
    # lifted faded blacks, contrast in the lower-mids, compressed top — vintage
    "heavy": dict(
        soften=0.85, saturation=0.82, halation=0.48, halation_thresh=0.72,
        grain=11, plate_opacity=0.55, vignette="PI/5", warmth=0.09, chroma=1.8,
        curve="0/0.03 0.12/0.115 0.3/0.3 0.55/0.62 0.8/0.85 1/0.945",
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
        "-show_entries", "stream=avg_frame_rate,width,height:format=duration",
        "-of", "json", str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(out.stdout) if out.returncode == 0 else {}
    if out.returncode != 0 or not data.get("streams"):
        detail = out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "no video stream"
        raise RuntimeError(f"ffprobe failed on {path.name}: {detail}")
    info = data["streams"][0]
    num, den = info["avg_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    dur = float(data.get("format", {}).get("duration", 0) or 0)
    return {"fps": fps, "width": info["width"], "height": info["height"],
            "duration": dur}


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

    chain = []
    pre = []   # temporal conform runs before the compare split, so both
               # halves share cadence and the split compares only the look
    src_fps = info["fps"]
    w_px, h_px = info["width"], info["height"]
    out_fps = 24 if (args.conform and src_fps > 24.5) else (src_fps or 24)

    depth10 = args.depth == 10
    # working format for the filter chain; final format for the encoder
    wfmt = "yuv444p10le" if depth10 else "yuv420p"
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

    # -- 2. Working bit depth --------------------------------------------------
    chain.append(f"format={wfmt}")

    # -- 3. Log input development: camera log -> display, via generated or
    #       manufacturer LUT. Runs first so the film look lands on properly
    #       developed footage instead of the flat log image.
    if getattr(args, "_loglut", None):
        kind, lpath = args._loglut
        chain.append(f"lut{kind}=file={fpath(lpath)}")

    # -- 4. Softening: negative unsharp == controlled blur -------------------
    if p["soften"] > 0:
        chain.append(
            f"unsharp=luma_msize_x=7:luma_msize_y=7:luma_amount=-{p['soften']:.2f}"
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

    # -- 7. Filmic tone curve (per-preset contrast character) -----------------
    if not args.no_curve:
        chain.append(f"curves=all='{p['curve']}'")

    # -- 8. Film-stock LUT ------------------------------------------------------
    if args.lut:
        chain.append(f"lut3d=file={fpath(args.lut)}")

    # -- 9. Color discipline ----------------------------------------------------
    if not args.bw:
        if p["saturation"] != 1.0:
            chain.append(f"eq=saturation={p['saturation']:.2f}")
        if not args.lut:
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
            f"colorlevels=rimin={t}:gimin={t}:bimin={t},"
            f"gblur=sigma=16"
            f"{tint}"
        )
        graph = (
            f"{prefix}{body},split[base][hl];"
            f"[hl]{hal}[hal];"
            f"[base][hal]blend=all_mode=screen:all_opacity={p['halation']:.2f}[pre]"
        )
    else:
        graph = f"{prefix}{body}[pre]"

    cur = "[pre]"

    # -- 11. Light leak: a slow radial warm glow from the frame edge that the
    #        gradients source cycles in and out of existence over time —
    #        appears for a stretch, fades for a longer one, like a real
    #        intermittent body leak.
    if args.leak > 0:
        # Screen-blending must happen in RGB: applying the screen formula to
        # YUV chroma planes (0.5-centered) shifts neutral colors toward
        # magenta across the whole frame (found the hard way).
        rgbfmt = "gbrp10le" if depth10 else "gbrp"
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
        # Synthesized: temporal, regenerated per frame, luma-weighted so it
        # reads as silver grain. B&W stocks wear their grain more openly.
        # (The noise filter processes at up to 16-bit, so this is safe in
        # 10-bit mode too.)
        g = int(p["grain"] * (1.5 if args.bw else 1.0))
        graph += (
            f";{cur}noise=c0s={g}:c0f=t+u:"
            f"c1s={max(1, g // 3)}:c1f=t+u:c2s={max(1, g // 3)}:c2f=t+u[gn]"
        )
        cur = "[gn]"

    # -- 13. Vignette ------------------------------------------------------------
    if not args.no_vignette:
        if depth10:
            # The vignette filter is 8-bit-only (verified empirically) and
            # would silently bottleneck the chain. Instead: render the
            # falloff as an 8-bit mask on a white source, upconvert, smooth
            # the quantization steps away with a blur, and multiply it into
            # the luma plane only (chroma passes through untouched).
            graph += (
                f";color=c=white:s={w_px}x{h_px}:r={out_fps:g},"
                f"vignette=angle={p['vignette']},format={wfmt},gblur=sigma=3[vm];"
                f"{cur}[vm]blend=c0_mode=multiply:"
                f"c1_mode=normal:c1_opacity=0:c2_mode=normal:c2_opacity=0:"
                f"shortest=1[vg]"
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
    if args.lut:
        bits.append(f"LUT: {args.lut.name}")
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
    out = subprocess.run(
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


def render(src: Path, out: Path, args) -> dict:
    """Build and run the ffmpeg command for one file. Returns a result
    record for the report; failures are recorded so a batch can continue."""
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

    graph = build_filtergraph(args, info)
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "warning", "-stats",
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
        # h264 — delivery codec; fine for a finish pass, poor for editing
        cmd += ["-c:v", "libx264",
                "-preset", "fast" if args.preview else "slow",
                "-crf", str(args.crf), "-tune", "grain", "-c:a", "copy"]
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

    rc = subprocess.run(cmd).returncode
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
p{{color:#cfc7ba;margin:.5rem 0 0}}</style></head><body>
<h1>filmify {e(__version__)} &mdash; {ok_n}/{len(results)} clip{"s" if len(results) != 1 else ""} processed</h1>
<p class="meta">{e(when)} &middot; {e(summarize_settings(args))}</p>
{"".join(cards)}</body></html>"""
    dest.write_text(doc, encoding="utf-8")


def main() -> None:
    if len(sys.argv) == 1:
        print(QUICKSTART)
        return
    ap = argparse.ArgumentParser(
        description="Process digital video to look like physical film.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("input", type=Path,
                    help="input video file, or a folder to batch-process")
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
    ap.add_argument("--leak", nargs="?", const=0.3, type=float, default=0.0,
                    metavar="0-1",
                    help="intermittent warm light leak from the frame edge "
                         "(off by default; bare flag = 0.3)")
    ap.add_argument("--depth", type=int, choices=(8, 10), default=8,
                    help="internal processing bit depth; 10 reduces banding "
                         "in gradients and survives further grading better "
                         "(pairs with --codec prores or dnxhr)")
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
    if not args.input.exists():
        sys.exit(f"error: {args.input} not found")
    for opt in ("lut", "grain_plate"):
        f = getattr(args, opt)
        if f and not f.exists():
            sys.exit(f"error: {f} not found")

    if args.look_file:
        apply_look_file(args, ap)
    if args.save_look:
        save_look_file(args)

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
        for i, f in enumerate(files, 1):
            print(f"[{i}/{len(files)}]")
            results.append(render(f, outdir / (f.stem + suffix + ext), args))
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
