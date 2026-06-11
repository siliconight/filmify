#!/usr/bin/env python3
"""
filmify — make digital video look like physical film.

A single-file FFmpeg pipeline. No dependencies beyond ffmpeg/ffprobe on PATH.

The processing chain (in order — order matters):

  1. Temporal conform   24 fps + simulated 180° shutter (frame blending),
                        so motion blur reads like a film camera, not a phone.
  2. Softening          Gentle de-sharpening. Digital is too crisp; film
                        lenses + the film plane itself are slightly soft.
  3. Filmic tone curve  S-curve with a soft shoulder. Whites roll off and
                        never reach 100% — highlights are protected, never
                        clipped. Blacks are lifted a hair (film never goes
                        to true zero either).
  4. Color discipline   Mild desaturation + a subtle warm-highlight /
                        cool-shadow split tone. Restrained, not "teal &
                        orange". Skin survives because saturation is pulled
                        globally and gently rather than pushed anywhere.
  5. Halation           Bright areas are isolated, blurred wide, tinted
                        red-orange (the color of light bouncing off the
                        film base back into the emulsion), and screened
                        over the image. Lights glow instead of clipping.
  6. Grain              Temporal, regenerated every frame, luma-weighted.
                        Subtle by default.
  7. Vignette           Very slight corner falloff, like a real lens.

Usage:
  python filmify.py input.mp4
  python filmify.py input.mp4 -o graded.mp4 --look heavy
  python filmify.py clip.mov --conform --grain 9 --halation 0.45
  python filmify.py clip.mov --dry-run        # print the ffmpeg command only

Shoot advice this tool can't replace: expose to protect highlights (or shoot
log/raw and grade first), light intentionally, shoot 24fps/180° in camera
when you can. This tool finishes the look; it can't recover clipped whites.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# ----------------------------------------------------------------------------
# Look presets. Every value can be overridden from the CLI.
# ----------------------------------------------------------------------------
LOOKS = {
    "subtle": dict(
        soften=0.35, saturation=0.93, halation=0.22, halation_thresh=0.82,
        grain=5, vignette="PI/7", black_lift=0.010, shoulder=0.965,
        warmth=0.04,
    ),
    "standard": dict(
        soften=0.55, saturation=0.88, halation=0.33, halation_thresh=0.78,
        grain=7, vignette="PI/6", black_lift=0.015, shoulder=0.955,
        warmth=0.06,
    ),
    "heavy": dict(
        soften=0.85, saturation=0.82, halation=0.48, halation_thresh=0.72,
        grain=11, vignette="PI/5", black_lift=0.025, shoulder=0.945,
        warmth=0.09,
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


def build_filtergraph(args, src_fps: float) -> str:
    p = dict(LOOKS[args.look])  # copy preset, then apply overrides
    if args.grain is not None:
        p["grain"] = args.grain
    if args.halation is not None:
        p["halation"] = args.halation
    if args.soften is not None:
        p["soften"] = args.soften
    if args.saturation is not None:
        p["saturation"] = args.saturation

    chain = []

    # -- 1. Temporal conform: 24 fps + ~180° shutter via frame blending ------
    if args.conform:
        if src_fps > 30:
            # Blend adjacent source frames to synthesize shutter blur,
            # then decimate to 24. From 50/60fps this approximates a
            # half-open (180°) shutter well.
            chain.append("tmix=frames=2")
            chain.append("fps=24")
        elif src_fps > 24.5:
            chain.append("fps=24")
        # already ~24 or 23.976: leave cadence alone

    # -- 2. Softening: negative unsharp == controlled blur -------------------
    if p["soften"] > 0:
        chain.append(
            f"unsharp=luma_msize_x=7:luma_msize_y=7:luma_amount=-{p['soften']:.2f}"
        )

    # -- 3. Filmic tone curve -------------------------------------------------
    chain.append(f"curves=all='{tone_curve(p['black_lift'], p['shoulder'])}'")

    # -- 4. Color discipline --------------------------------------------------
    chain.append(f"eq=saturation={p['saturation']:.2f}")
    w = p["warmth"]
    # warm highlights, faintly cool shadows — a classic print-stock split
    chain.append(
        f"colorbalance="
        f"rh={w:.3f}:bh={-w * 0.5:.3f}:"      # highlights toward warm
        f"rs={-w * 0.3:.3f}:bs={w * 0.4:.3f}"  # shadows faintly cool
    )

    graph = ",".join(chain)

    # -- 5. Halation: split → isolate highlights → blur → tint → screen ------
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
            f"[base][hal]blend=all_mode=screen:all_opacity={p['halation']:.2f}"
        )
    else:
        graph = f"[0:v]{graph}"

    tail = []

    # -- 6. Grain: temporal, regenerated per frame ----------------------------
    if p["grain"] > 0:
        g = p["grain"]
        # stronger on luma, faint on chroma — reads as silver grain,
        # not RGB sensor noise
        tail.append(f"noise=c0s={g}:c0f=t+u:c1s={max(1, g // 3)}:c1f=t+u:c2s={max(1, g // 3)}:c2f=t+u")

    # -- 7. Vignette -----------------------------------------------------------
    if not args.no_vignette:
        tail.append(f"vignette=angle={p['vignette']}")

    tail.append("format=yuv420p")

    return graph + "," + ",".join(tail) + "[vout]"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Process digital video to look like physical film.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("input", type=Path, help="input video file")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="output file (default: <input>_film.mp4)")
    ap.add_argument("--look", choices=LOOKS, default="standard",
                    help="overall intensity preset")
    ap.add_argument("--conform", action="store_true",
                    help="convert to 24 fps with simulated 180-degree shutter blur")
    ap.add_argument("--grain", type=int, default=None, metavar="0-20",
                    help="grain strength override (0 disables)")
    ap.add_argument("--halation", type=float, default=None, metavar="0-1",
                    help="halation/bloom strength override (0 disables)")
    ap.add_argument("--soften", type=float, default=None, metavar="0-1.5",
                    help="softening strength override (0 disables)")
    ap.add_argument("--saturation", type=float, default=None, metavar="0-2",
                    help="saturation override (1 = unchanged)")
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

    out = args.output or args.input.with_name(args.input.stem + "_film.mp4")
    info = probe(args.input)
    graph = build_filtergraph(args, info["fps"])

    cmd = [
        "ffmpeg", "-y", "-i", str(args.input),
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf),
        # tune for grain retention so the encoder doesn't smooth it away
        "-tune", "grain",
        "-c:a", "copy",
        str(out),
    ]

    print(f"input : {args.input}  ({info['width']}x{info['height']} @ {info['fps']:.3f} fps)")
    print(f"output: {out}")
    print(f"look  : {args.look}" + ("  + 24fps/180° conform" if args.conform else ""))
    if args.dry_run:
        print("\n" + " ".join(f"'{c}'" if " " in c else c for c in cmd))
        return

    rc = subprocess.run(cmd).returncode
    if rc != 0:
        sys.exit(rc)
    print("done.")


if __name__ == "__main__":
    main()
