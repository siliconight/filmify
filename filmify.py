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
  4. Filmic tone curve  S-curve with a soft shoulder. Whites roll off and
                        never reach 100% — highlights are protected, never
                        clipped. Blacks are lifted a hair.
  5. Film-stock LUT     Optional .cube 3D LUT (Kodak/Fuji print emulations,
                        etc.). When a LUT is supplied it owns the color
                        character, so the built-in split tone is skipped.
  6. Color discipline   Mild desaturation + a subtle warm-highlight /
                        cool-shadow split tone (when no LUT is given).
  7. Halation           Bright areas isolated, blurred wide, tinted
                        red-orange, screened back over the image.
  8. Grain              Real scanned grain plate (--grain-plate) overlaid
                        and looped, or synthesized temporal luma-weighted
                        grain as the fallback.
  9. Vignette           Very slight corner falloff, like a real lens.

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
import json
import shutil
import subprocess
import sys
from pathlib import Path

__version__ = "0.3.0"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mts", ".mxf"}

# ----------------------------------------------------------------------------
# Look presets. Every value can be overridden from the CLI.
# ----------------------------------------------------------------------------
LOOKS = {
    "subtle": dict(
        soften=0.35, saturation=0.93, halation=0.22, halation_thresh=0.82,
        grain=5, plate_opacity=0.30, vignette="PI/7", black_lift=0.010,
        shoulder=0.965, warmth=0.04,
    ),
    "standard": dict(
        soften=0.55, saturation=0.88, halation=0.33, halation_thresh=0.78,
        grain=7, plate_opacity=0.42, vignette="PI/6", black_lift=0.015,
        shoulder=0.955, warmth=0.06,
    ),
    "heavy": dict(
        soften=0.85, saturation=0.82, halation=0.48, halation_thresh=0.72,
        grain=11, plate_opacity=0.55, vignette="PI/5", black_lift=0.025,
        shoulder=0.945, warmth=0.09,
    ),
}


def probe(path: Path) -> dict:
    """Return basic stream info for the input file."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,width,height",
        "-of", "json", str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"ffprobe failed on {path}:\n{out.stderr}")
    info = json.loads(out.stdout)["streams"][0]
    num, den = info["avg_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    return {"fps": fps, "width": info["width"], "height": info["height"]}


def fpath(path: Path) -> str:
    """Escape a file path for use inside an ffmpeg filtergraph.

    Filtergraph syntax treats ':' and '\\' specially, which breaks Windows
    paths like C:\\luts\\film.cube. Forward slashes work fine on Windows.
    """
    s = str(path).replace("\\", "/").replace(":", "\\\\:")
    return f"'{s}'"


def tone_curve(black_lift: float, shoulder: float) -> str:
    """
    Filmic S-curve as ffmpeg 'curves' points.
    - black_lift raises pure black slightly (faded film base).
    - shoulder is where pure white lands (<1.0 = highlights protected).
    The midsection adds gentle contrast; the top rolls off smoothly so
    bright areas compress instead of clipping.
    """
    pts = [
        (0.00, black_lift),
        (0.18, 0.155 + black_lift * 0.5),
        (0.50, 0.515),
        (0.78, 0.815),
        (0.92, 0.915),
        (1.00, shoulder),
    ]
    return " ".join(f"{x:g}/{y:g}" for x, y in pts)


def build_filtergraph(args, info: dict) -> str:
    p = dict(LOOKS[args.look])  # copy preset, then apply CLI overrides
    for key in ("grain", "halation", "soften", "saturation", "plate_opacity"):
        v = getattr(args, key, None)
        if v is not None:
            p[key] = v

    chain = []
    src_fps = info["fps"]
    w_px, h_px = info["width"], info["height"]

    # -- 1. Temporal conform: 24 fps + ~180° shutter via frame blending ------
    if args.conform:
        if src_fps > 30:
            chain.append("tmix=frames=2")   # synthesize shutter blur
            chain.append("fps=24")
        elif src_fps > 24.5:
            chain.append("fps=24")
        # already ~24 / 23.976: leave cadence alone

    # -- 2. Softening: negative unsharp == controlled blur -------------------
    if p["soften"] > 0:
        chain.append(
            f"unsharp=luma_msize_x=7:luma_msize_y=7:luma_amount=-{p['soften']:.2f}"
        )

    # -- 3. Gate weave: slow frame drift, two layered sines per axis ---------
    # (Pure random() reads as digital jitter; layered slow sines read as a
    #  projector gate.) Crops a small margin, drifts inside it, scales back.
    if args.weave > 0:
        a = args.weave
        m = max(2, int(a * 1.6) + 1)
        chain.append(
            f"crop=w=iw-{2 * m}:h=ih-{2 * m}:"
            f"x='{m}+{a:.2f}*sin(n/9.1)+{a / 2:.2f}*sin(n/3.7)':"
            f"y='{m}+{a * 0.7:.2f}*sin(n/7.3)+{a / 2:.2f}*sin(n/2.9)'"
        )
        chain.append(f"scale={w_px}:{h_px},setsar=1")

    # -- 4. Filmic tone curve -------------------------------------------------
    if not args.no_curve:
        chain.append(f"curves=all='{tone_curve(p['black_lift'], p['shoulder'])}'")

    # -- 5. Film-stock LUT ------------------------------------------------------
    if args.lut:
        chain.append(f"lut3d=file={fpath(args.lut)}")

    # -- 6. Color discipline ----------------------------------------------------
    if p["saturation"] != 1.0:
        chain.append(f"eq=saturation={p['saturation']:.2f}")
    if not args.lut:
        # warm highlights, faintly cool shadows — a classic print-stock split.
        # Skipped when a LUT is supplied: the LUT owns the color character.
        w = p["warmth"]
        chain.append(
            f"colorbalance="
            f"rh={w:.3f}:bh={-w * 0.5:.3f}:"
            f"rs={-w * 0.3:.3f}:bs={w * 0.4:.3f}"
        )

    graph = ",".join(chain) if chain else "null"

    # -- 7. Halation: split → isolate highlights → blur → tint → screen ------
    if p["halation"] > 0:
        t = p["halation_thresh"]
        hal = (
            f"colorlevels=rimin={t}:gimin={t}:bimin={t},"
            f"gblur=sigma=16,"
            f"colorchannelmixer=rr=1.0:gg=0.46:bb=0.24"
        )
        graph = (
            f"[0:v]{graph},split[base][hl];"
            f"[hl]{hal}[hal];"
            f"[base][hal]blend=all_mode=screen:all_opacity={p['halation']:.2f}[pre]"
        )
    else:
        graph = f"[0:v]{graph}[pre]"

    # -- 8. Grain ----------------------------------------------------------------
    if args.grain_plate:
        # Real scanned grain: loop it, scale to cover the frame, overlay-blend.
        graph += (
            f";[1:v]scale={w_px}:{h_px}:force_original_aspect_ratio=increase,"
            f"crop={w_px}:{h_px},format=yuv420p[gp];"
            f"[pre][gp]blend=all_mode=overlay:all_opacity={p['plate_opacity']:.2f}:shortest=1[gr]"
        )
        tail = []
    elif p["grain"] > 0:
        # Synthesized fallback: temporal, regenerated per frame, luma-weighted
        # so it reads as silver grain rather than RGB sensor noise.
        g = int(p["grain"])
        tail = [
            f"noise=c0s={g}:c0f=t+u:"
            f"c1s={max(1, g // 3)}:c1f=t+u:c2s={max(1, g // 3)}:c2f=t+u"
        ]
    else:
        tail = []

    # -- 9. Vignette ----------------------------------------------------------
    if not args.no_vignette:
        tail.append(f"vignette=angle={p['vignette']}")

    tail.append("format=yuv420p")

    last_label = "[gr]" if args.grain_plate else "[pre]"
    return graph + f";{last_label}" + ",".join(tail) + "[vout]"


def render(src: Path, out: Path, args) -> None:
    """Build and run the ffmpeg command for one file."""
    info = probe(src)
    graph = build_filtergraph(args, info)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-stats",
           "-i", str(src)]
    if args.grain_plate:
        cmd += ["-stream_loop", "-1", "-i", str(args.grain_plate)]
    cmd += ["-filter_complex", graph, "-map", "[vout]", "-map", "0:a?"]
    if args.preview:
        cmd += ["-t", f"{args.preview:g}"]
    cmd += [
        "-c:v", "libx264",
        # preview trades quality for iteration speed
        "-preset", "fast" if args.preview else "slow",
        "-crf", str(args.crf),
        # tune for grain retention so the encoder doesn't smooth it away
        "-tune", "grain",
        "-c:a", "copy",
        str(out),
    ]

    bits = [args.look]
    if args.conform:
        bits.append("24fps/180° conform")
    if args.weave > 0:
        bits.append(f"weave {args.weave:g}px")
    if args.lut:
        bits.append(f"LUT: {args.lut.name}")
    if args.grain_plate:
        bits.append(f"grain plate: {args.grain_plate.name}")
    if args.preview:
        bits.append(f"preview {args.preview:g}s")
    print(f"input : {src}  ({info['width']}x{info['height']} @ {info['fps']:.3f} fps)")
    print(f"output: {out}")
    print(f"look  : {' + '.join(bits)}")

    if args.dry_run:
        print("\n" + " ".join(f"'{c}'" if " " in c else c for c in cmd) + "\n")
        return

    rc = subprocess.run(cmd).returncode
    if rc != 0:
        sys.exit(rc)
    print("done.\n")


def main() -> None:
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
    ap.add_argument("--weave", type=float, default=0.0, metavar="PX",
                    help="gate weave: slow frame drift in pixels (try 1-2; 0 disables)")
    ap.add_argument("--no-curve", action="store_true",
                    help="disable the built-in filmic tone curve (e.g. when your LUT includes one)")
    ap.add_argument("--no-vignette", action="store_true",
                    help="disable the vignette")
    ap.add_argument("--crf", type=int, default=17,
                    help="x264 quality (lower = better; grain needs bitrate)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the ffmpeg command without running it")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"error: {tool} not found on PATH")
    if not args.input.exists():
        sys.exit(f"error: {args.input} not found")
    for opt in ("lut", "grain_plate"):
        f = getattr(args, opt)
        if f and not f.exists():
            sys.exit(f"error: {f} not found")

    suffix = "_preview" if args.preview else "_film"
    print(f"filmify {__version__}\n")

    if args.input.is_dir():
        files = sorted(
            f for f in args.input.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS
            # don't reprocess our own outputs on a rerun
            and not f.stem.endswith(("_film", "_preview"))
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
            render(f, outdir / (f.stem + suffix + ".mp4"), args)
    else:
        out = args.output or args.input.with_name(args.input.stem + suffix + ".mp4")
        render(args.input, out, args)


if __name__ == "__main__":
    main()
