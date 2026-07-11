#!/usr/bin/env python3
"""
lut_generation.py — generates the two LUTs at the heart of filmify's
photochemical pipeline, with content-hash caching.

  NEGATIVE LUT   display-encoded source RGB  ->  normalized negative density
  PRINT LUT      normalized negative density ->  display-encoded positive

Conceptually the chain is: input transfer decode -> scene-linear exposure ->
stock sensitivity matrix -> per-layer characteristic curves -> density;
then density -> transmittance -> printer lights -> printer matrix -> print
curves -> print density -> transmitted light -> projection/scan -> display
encode. For the FFmpeg backend the purely per-pixel technical transforms at
each end (transfer decode, projection, display encode) are COMPOSED INTO the
two LUTs — semantics identical, one fewer fragile filter per stage, and the
frame between the LUTs is exactly the TDD's normalized-density intermediate,
where grain will be injected. `--dump-pipeline` documents the composition.

Printer calibration: real labs time a print — per-channel printer lights are
set so a reference gray hits the print stock's neutral aim. We do the same at
generation time: a per-channel exposure trim is solved (bisection; every
stage is monotone) so an 18%-gray scene lands on a neutral mid on screen.
The negative's per-channel base densities (the orange-mask ancestor) are
thereby neutralized by the printer, not by hiding them in the curves. User
--printer-lights values are offsets around that calibrated neutral, in
profile-defined light points; higher = more exposure = denser = LESS of that
color in the print, exactly like a real timer.

Stdlib only. Deterministic: identical inputs produce byte-identical .cube
files, and the cache key is a hash of everything that matters and nothing
that doesn't.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import photochemical as pc

# Bump to invalidate every previously cached LUT (schema/algorithm changes).
GENERATOR_VERSION = 1

# Dense 1D tables stand in for repeated Hermite evaluation in the grid loop.
_TABLE_N = 4096

MID_GRAY = pc.MID_GRAY


# ---------------------------------------------------------------------------
# input transfer functions (display/camera encoding -> scene-linear)
# ---------------------------------------------------------------------------
# The log formulas are kept in sync with filmify.py's reference
# implementations (_slog3_to_linear / _vlog_to_linear / _cineon_to_linear).
# Duplicated on purpose: importing 2,500 lines of filmify to get 30 lines of
# math would couple the generator to the whole app.

def _rec709_to_linear(y: float) -> float:
    # Inverse BT.709 OETF — the standard pragmatic reading of an SDR source
    # as relative scene light.
    if y < 0.081:
        return y / 4.5
    return ((y + 0.099) / 1.099) ** (1.0 / 0.45)


def _linear_to_rec709(lin: float) -> float:
    lin = max(0.0, lin)
    if lin < 0.018:
        y = 4.5 * lin
    else:
        y = 1.099 * (lin ** 0.45) - 0.099
    return min(1.0, max(0.0, y))


def _slog3_to_linear(x: float) -> float:
    cv = x * 1023.0
    if cv >= 171.2102946929:
        return (10 ** ((cv - 420.0) / 261.5)) * (0.18 + 0.01) - 0.01
    return (cv - 95.0) * 0.01125 / (171.2102946929 - 95.0)


def _vlog_to_linear(x: float) -> float:
    b, c, d = 0.00873, 0.241514, 0.598206
    if x < 0.181:
        return (x - 0.125) / 5.6
    return 10 ** ((x - d) / c) - b


def _cineon_to_linear(x: float) -> float:
    cv = x * 1023.0
    blk = 10 ** ((95.0 - 685.0) / 300.0)
    return (10 ** ((cv - 685.0) / 300.0) - blk) / (1.0 - blk)


TRANSFERS = {
    "rec709": _rec709_to_linear,
    "slog3": _slog3_to_linear,
    "vlog": _vlog_to_linear,
    "cineon": _cineon_to_linear,
}

# Linear ceiling for the halation exposure frame: +2 stops over diffuse
# white, so a highlight's halo has room to add ABOVE white before clipping.
# Shared by the linear exposure LUT and the log shaper that undoes it.
HALATION_HEADROOM = 4.0


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------

def cache_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        d = base / "filmify" / "luts"
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Caches" / "filmify" / "luts"
    else:
        d = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "filmify" / "luts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(kind: str, size: int, **relevant) -> str:
    payload = json.dumps({"generator": GENERATOR_VERSION, "kind": kind,
                          "size": size, **relevant},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cube_path(kind: str, key: str, size: int) -> Path:
    return cache_dir() / f"{kind}_{key[:16]}_{size}.cube"


def _write_cube(path: Path, size: int, rows, title: str) -> None:
    """Atomic, deterministic .cube write. rows yields (r, g, b) floats with
    red varying fastest (the .cube convention FFmpeg's lut3d expects)."""
    lines = [f"TITLE \"{title}\"",
             f"LUT_3D_SIZE {size}",
             "DOMAIN_MIN 0.0 0.0 0.0",
             "DOMAIN_MAX 1.0 1.0 1.0"]
    lines += [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in rows]
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# dense 1D lookup tables (grid loops must not re-run Hermite per point)
# ---------------------------------------------------------------------------

class _Table:
    """Uniform 1D lookup with linear interpolation, flat outside the domain
    — matching CharacteristicCurve's flat toe/shoulder extension."""

    def __init__(self, x0: float, x1: float, fn, n: int = _TABLE_N):
        self.x0, self.x1 = x0, x1
        self.inv_step = (n - 1) / (x1 - x0)
        self.vals = [fn(x0 + (x1 - x0) * i / (n - 1)) for i in range(n)]

    def __call__(self, x: float) -> float:
        t = (x - self.x0) * self.inv_step
        if t <= 0.0:
            return self.vals[0]
        i = int(t)
        if i >= len(self.vals) - 1:
            return self.vals[-1]
        f = t - i
        return self.vals[i] * (1.0 - f) + self.vals[i + 1] * f


# ---------------------------------------------------------------------------
# negative LUT
# ---------------------------------------------------------------------------

def negative_lut(negative: dict, *, transfer: str = "rec709",
                 exposure_stops: float = 0.0, size: int = 33) -> Path:
    """Display-encoded source RGB (0..1) -> normalized negative density.
    Composed: transfer decode -> exposure -> sensitivity matrix ->
    per-layer characteristic curves -> storage normalization."""
    if transfer not in TRANSFERS:
        raise ValueError(f"unknown input transfer {transfer!r} "
                         f"(have: {', '.join(sorted(TRANSFERS))})")
    key = _cache_key("negative", size,
                     profile=pc.profile_fingerprint(negative),
                     transfer=transfer, exposure_stops=round(exposure_stops, 4))
    path = _cube_path("negative", key, size)
    if path.exists():
        return path

    dec = TRANSFERS[transfer]
    gain = 2.0 ** exposure_stops
    axis = [dec(i / (size - 1)) * gain for i in range(size)]

    m = negative["sensitivity_matrix"]
    (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
    curves = pc.profile_curves(negative)
    s0, s1 = negative["density_storage_range"]
    inv_span = 1.0 / (s1 - s0)

    def dens_table(c):
        # log relative exposure -> normalized storage density
        return _Table(c.xs[0] - 1.0, c.xs[-1] + 1.0,
                      lambda le: min(1.0, max(0.0, (c.density(le) - s0) * inv_span)))

    tr, tg, tb = (dens_table(curves[k]) for k in ("red", "green", "blue"))
    log10, eps = math.log10, 1e-8

    def rows():
        for bi in range(size):
            lb = axis[bi]
            for gi in range(size):
                lg = axis[gi]
                for ri in range(size):
                    lr = axis[ri]
                    er = m00 * lr + m01 * lg + m02 * lb
                    eg = m10 * lr + m11 * lg + m12 * lb
                    eb = m20 * lr + m21 * lg + m22 * lb
                    yield (tr(log10((er if er > eps else eps) / MID_GRAY)),
                           tg(log10((eg if eg > eps else eps) / MID_GRAY)),
                           tb(log10((eb if eb > eps else eps) / MID_GRAY)))

    _write_cube(path, size, rows(),
                f"filmify negative {negative['profile_id']} ({transfer})")
    return path


# ---------------------------------------------------------------------------
# printer calibration
# ---------------------------------------------------------------------------

def _projection_encode_fn(print_profile: dict, curve):
    """print log-exposure -> displayed value, for one channel: print curve ->
    print density -> transmittance -> projection (flare, floor, white scale,
    normalized so print D-min projects at white_scale) -> display encode."""
    proj = print_profile.get("projection", {})
    flare = float(proj.get("flare", 0.0))
    floor = float(proj.get("black_floor", 0.0))
    scale = float(proj.get("white_scale", 1.0))
    t_white = 10.0 ** (-curve.d_min)
    norm = scale / (t_white + flare)

    def fn(le: float) -> float:
        t = 10.0 ** (-curve.density(le))
        return _linear_to_rec709(floor + norm * (t + flare))
    return fn


def _calibrate_printer(negative: dict, print_profile: dict) -> dict:
    """Per-channel log10 exposure trims so an 18%-gray scene prints to a
    neutral mid on screen — the virtual lab timing its print to a LAD-style
    aim. Every stage is monotone, so bisection is exact enough."""
    target = _linear_to_rec709(MID_GRAY)          # neutral mid, on screen
    neg_curves = pc.profile_curves(negative)
    prt_curves = pc.profile_curves(print_profile)
    trims = {}
    for ch in ("red", "green", "blue"):
        t_mid = 10.0 ** (-neg_curves[ch].density(0.0))   # mid-gray negative
        enc = _projection_encode_fn(print_profile, prt_curves[ch])
        lo, hi = -8.0, 8.0                                # log10 trim bounds
        for _ in range(60):
            mid = (lo + hi) / 2.0
            # more exposure -> denser print -> darker: enc is decreasing
            if enc(math.log10(t_mid) + mid) > target:
                lo = mid
            else:
                hi = mid
        trims[ch] = (lo + hi) / 2.0
    return trims


# ---------------------------------------------------------------------------
# print LUT
# ---------------------------------------------------------------------------

def print_lut(negative: dict, print_profile: dict, *,
              printer_lights=(25, 25, 25), size: int = 33) -> Path:
    """Normalized negative density -> display-encoded positive.
    Composed: storage denormalization -> transmittance -> printer lights
    (calibrated trims + user offsets) -> printer matrix -> print curves ->
    print density -> transmittance -> projection -> display encode."""
    lights = tuple(int(v) for v in printer_lights)
    key = _cache_key("print", size,
                     negative=pc.profile_fingerprint(negative),
                     print=pc.profile_fingerprint(print_profile),
                     lights=lights)
    path = _cube_path("print", key, size)
    if path.exists():
        return path

    s0, s1 = negative["density_storage_range"]
    trims = _calibrate_printer(negative, print_profile)
    neutral = print_profile["neutral_printer_lights"]
    lp_stops = float(print_profile.get("light_point_stops", 0.025))
    # log10 per-channel exposure factor: calibrated trim + user light offset.
    # Higher light number = more exposure = denser = less of that color.
    log2_10 = math.log10(2.0)
    lfac = {ch: 10.0 ** (trims[ch] + (lights[i] - neutral[i]) * lp_stops * log2_10)
            for i, ch in enumerate(("red", "green", "blue"))}

    # Axis precompute: normalized density -> exposure contribution (before
    # the printer matrix, which is the only cross-channel step).
    def t_axis(ch):
        f = lfac[ch]
        return [f * 10.0 ** (-(s0 + (s1 - s0) * i / (size - 1)))
                for i in range(size)]
    ar, ag, ab = t_axis("red"), t_axis("green"), t_axis("blue")

    m = print_profile["printer_matrix"]
    (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
    prt_curves = pc.profile_curves(print_profile)

    def out_table(ch):
        c = prt_curves[ch]
        return _Table(c.xs[0] - 2.0, c.xs[-1] + 2.0,
                      _projection_encode_fn(print_profile, c))
    tr, tg, tb = (out_table(k) for k in ("red", "green", "blue"))
    log10, eps = math.log10, 1e-12

    def rows():
        for bi in range(size):
            xb = ab[bi]
            for gi in range(size):
                xg = ag[gi]
                for ri in range(size):
                    xr = ar[ri]
                    er = m00 * xr + m01 * xg + m02 * xb
                    eg = m10 * xr + m11 * xg + m12 * xb
                    eb = m20 * xr + m21 * xg + m22 * xb
                    yield (tr(log10(er if er > eps else eps)),
                           tg(log10(eg if eg > eps else eps)),
                           tb(log10(eb if eb > eps else eps)))

    _write_cube(path, size, rows(),
                f"filmify print {print_profile['profile_id']} "
                f"lights {lights[0]},{lights[1]},{lights[2]}")
    return path


# ---------------------------------------------------------------------------
# split negative: exposure LUT + response LUT (for the halation stage)
# ---------------------------------------------------------------------------
# Halation is a SPATIAL exposure spread — it cannot live inside a per-pixel
# LUT. When it's active the fused negative LUT splits in two around a
# scene-log exposure frame the bloom runs on:
#
#   EXPOSURE LUT   source encoding -> scene-log exposure   (per-pixel)
#   ...halation threshold/blur/matrix/screen happens here, in log exposure...
#   RESPONSE LUT   scene-log exposure -> normalized density   (per-pixel)
#
# Both LUTs share photochemical's scene-log domain (−10..+6 stops over mid
# gray), so composition is exact: response(exposure(v)) == the fused
# negative LUT, tested. Log — not linear — because a linear exposure axis
# packs the whole toe into the first grid cell, where tetrahedral
# interpolation flattens shadow detail into garbage.


def exposure_lut(negative: dict, *, transfer: str = "rec709",
                 exposure_stops: float = 0.0, size: int = 33,
                 linear: bool = False, headroom: float = 4.0) -> Path:
    """Source-encoded RGB -> scene exposure, post sensitivity matrix.

    Two output encodings:
      * scene-log (default) — photochemical's 0..1 over −10..+6 stops. Same
        domain the response LUT reads, so exposure∘response == the fused
        negative LUT. Used when halation is off (one fewer stage).
      * linear (linear=True) — linear scene light / headroom, clamped 0..1.
        Halation must spread in LINEAR light (adding light in a log domain
        under-blooms), so the linear encoding is what the halo blurs and
        adds into; log_shaper_lut then re-encodes to scene-log before the
        response LUT. `headroom` is the linear ceiling (4.0 = +2 stops over
        diffuse white) giving the halo room to add ABOVE white without
        clipping."""
    if transfer not in TRANSFERS:
        raise ValueError(f"unknown input transfer {transfer!r}")
    kind = "exposurelin" if linear else "exposure"
    key = _cache_key(kind, size,
                     profile=pc.profile_fingerprint(negative),
                     transfer=transfer, stops=pc.DEFAULT_STOP_RANGE,
                     exposure_stops=round(exposure_stops, 4),
                     headroom=round(headroom, 4) if linear else None)
    path = _cube_path(kind, key, size)
    if path.exists():
        return path

    dec = TRANSFERS[transfer]
    gain = 2.0 ** exposure_stops
    axis = [dec(i / (size - 1)) * gain for i in range(size)]
    m = negative["sensitivity_matrix"]
    (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
    if linear:
        inv = 1.0 / headroom
        enc = lambda v: min(1.0, max(0.0, v * inv))  # noqa: E731
    else:
        enc = pc.scene_linear_to_log

    def rows():
        for bi in range(size):
            lb = axis[bi]
            for gi in range(size):
                lg = axis[gi]
                for ri in range(size):
                    lr = axis[ri]
                    yield (enc(m00 * lr + m01 * lg + m02 * lb),
                           enc(m10 * lr + m11 * lg + m12 * lb),
                           enc(m20 * lr + m21 * lg + m22 * lb))

    tag = "linear" if linear else "log"
    _write_cube(path, size, rows(),
                f"filmify exposure {negative['profile_id']} ({transfer}, {tag})")
    return path


def log_shaper_lut(*, headroom: float = 4.0, size: int = 33) -> Path:
    """Linear scene light / headroom -> scene-log encoding (photochemical's
    0..1 over −10..+6 stops). A per-channel shaper (diagonal 3D LUT) between
    the linear-light halation stage and the response LUT, doing the
    linear->log conversion the response LUT's input domain requires.

    Stock-independent — it depends only on headroom and the shared scene-log
    domain — so one cache entry serves every negative."""
    key = _cache_key("logshaper", size,
                     headroom=round(headroom, 4), stops=pc.DEFAULT_STOP_RANGE)
    path = _cube_path("logshaper", key, size)
    if path.exists():
        return path

    enc = pc.scene_linear_to_log
    axis = [enc((i / (size - 1)) * headroom) for i in range(size)]

    def rows():
        for bi in range(size):
            for gi in range(size):
                for ri in range(size):
                    yield (axis[ri], axis[gi], axis[bi])

    _write_cube(path, size, rows(),
                f"filmify log shaper (headroom {headroom:g})")
    return path


def negative_response_lut(negative: dict, *, size: int = 33) -> Path:
    """Scene-log encoded exposure (photochemical.scene_linear_to_log's
    0..1, −10..+6 stops) -> normalized negative density. Per-channel (the
    sensitivity matrix already ran in the exposure LUT).

    The input domain is LOG on purpose: a linear domain packs the whole
    toe into the first grid cell, where tetrahedral interpolation flattens
    it into garbage shadows. Uniform-in-stops is what a film curve wants —
    the ffmpeg `curves` shaper between the halation add and this LUT does
    the linear->log conversion on the frame."""
    key = _cache_key("response", size,
                     profile=pc.profile_fingerprint(negative),
                     stops=pc.DEFAULT_STOP_RANGE)
    path = _cube_path("response", key, size)
    if path.exists():
        return path

    curves = pc.profile_curves(negative)
    s0, s1 = negative["density_storage_range"]
    inv_span = 1.0 / (s1 - s0)
    lo, hi = pc.DEFAULT_STOP_RANGE
    log10_2 = math.log10(2.0)

    def ax(ch):
        c = curves[ch]
        out = []
        for i in range(size):
            stops = lo + (hi - lo) * i / (size - 1)
            le = stops * log10_2            # stops over mid gray -> decades
            out.append(min(1.0, max(0.0, (c.density(le) - s0) * inv_span)))
        return out
    ar, ag, ab = ax("red"), ax("green"), ax("blue")

    def rows():
        for bi in range(size):
            for gi in range(size):
                for ri in range(size):
                    yield (ar[ri], ag[gi], ab[bi])

    _write_cube(path, size, rows(),
                f"filmify negative response {negative['profile_id']}")
    return path


# ---------------------------------------------------------------------------
# grain amplitude mask (density -> per-channel grain strength)
# ---------------------------------------------------------------------------

def _interp_linear(points, x: float) -> float:
    """Piecewise-linear interpolation, flat outside the domain. The grain
    density curve is a bell (rises then falls), so the monotone machinery
    in CharacteristicCurve deliberately does not apply here."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = 0
    while xs[i + 1] < x:
        i += 1
    f = (x - xs[i]) / (xs[i + 1] - xs[i])
    return ys[i] * (1.0 - f) + ys[i + 1] * f


def grain_mask_lut(negative: dict, size: int = 17) -> Path:
    """Normalized negative density -> per-channel grain amplitude (0..1),
    from the profile's density curve × per-channel strengths. Drives a
    maskedmerge between the clean and fully-grained density frames, which
    is what makes grain density-dependent: mids wear it, D-min and D-max
    stay quieter — negative grain, not overlay grain."""
    g = negative.get("grain", {})
    dcurve = g.get("density_curve") or [[0.0, 1.0], [1.0, 1.0]]
    strengths = g.get("channel_strength", [1.0, 1.0, 1.0])
    key = _cache_key("grainmask", size,
                     profile=pc.profile_fingerprint(negative))
    path = _cube_path("grainmask", key, size)
    if path.exists():
        return path

    def ax(ci):
        s = float(strengths[ci])
        return [min(1.0, max(0.0, _interp_linear(dcurve, i / (size - 1)) * s))
                for i in range(size)]
    ar, ag, ab = ax(0), ax(1), ax(2)

    def rows():
        for bi in range(size):
            for gi in range(size):
                for ri in range(size):
                    yield (ar[ri], ag[gi], ab[bi])

    _write_cube(path, size, rows(),
                f"filmify grain mask {negative['profile_id']}")
    return path


# ---------------------------------------------------------------------------
# negative transmitted-light preview (for --debug-stage negative-preview)
# ---------------------------------------------------------------------------

def negative_preview_lut(negative: dict, size: int = 33) -> Path:
    """Normalized negative density -> a viewable image of the negative as
    transmitted light (bright scene = dense = dark, like holding the neg up
    to a light). Diagnostic only — never part of the render chain."""
    key = _cache_key("negpreview", size,
                     profile=pc.profile_fingerprint(negative))
    path = _cube_path("negpreview", key, size)
    if path.exists():
        return path
    s0, s1 = negative["density_storage_range"]
    axis = [_linear_to_rec709(10.0 ** (-(s0 + (s1 - s0) * i / (size - 1))))
            for i in range(size)]

    def rows():
        for bi in range(size):
            for gi in range(size):
                for ri in range(size):
                    yield (axis[ri], axis[gi], axis[bi])

    _write_cube(path, size, rows(),
                f"filmify negative preview {negative['profile_id']}")
    return path


# ---------------------------------------------------------------------------
# CLI: quick generation timing / cache inspection
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import time
    ap = argparse.ArgumentParser(description="filmify LUT generator")
    ap.add_argument("--bench", action="store_true",
                    help="time 33- and 65-cube generation (cache bypassed)")
    args = ap.parse_args()
    if args.bench:
        neg = pc.get_builtin("modern_500t")
        prt = pc.get_builtin("neutral_release")
        for size in (33, 65):
            neg["description"] += f" bench{time.time()}"   # defeat cache
            t0 = time.time()
            n = negative_lut(neg, size=size)
            t1 = time.time()
            p = print_lut(neg, prt, size=size)
            t2 = time.time()
            print(f"{size}^3: negative {t1 - t0:.2f}s, print {t2 - t1:.2f}s")
            print(f"   {n.name}\n   {p.name}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
