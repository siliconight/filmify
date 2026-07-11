#!/usr/bin/env python3
"""
photochemical.py — density mathematics and stock profiles for filmify's
photochemical pipeline.

This is the foundation the photochemical chain builds on: pure math and
profile data, fully unit tested, with no FFmpeg or filtergraph knowledge.
Stdlib only — user machines self-bootstrap a bare Python, so nothing here
may require pip.

What lives here:
  * optical density <-> transmittance conversion  (D = -log10 T)
  * scene-linear <-> normalized log-exposure encoding (the bounded domain
    generated LUTs need)
  * monotone cubic (Fritsch–Carlson) curve interpolation with a hard
    no-overshoot guarantee, plus a linear fallback
  * per-layer characteristic-curve evaluation
  * stock-profile schema validation and loading
  * generic built-in profiles (placeholders — descriptive names only,
    deliberately NOT claims about any commercial stock)

Nothing in this file changes any render yet. filmify.py gains a --pipeline
flag defaulting to legacy; the photochemical render chain arrives in later
releases (LUT generation, then the filtergraph stages).

Self-check:      python photochemical.py --selftest
Validate a file: python photochemical.py --validate my_stock.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

SCHEMA_VERSION = 1

# Transmittance below this is treated as opaque when converting to density —
# log10(0) is -inf, and no real film base passes literally zero light.
MIN_TRANSMITTANCE = 1e-8

# Sanity ceiling for any density value we accept from a profile. Projection
# print D-max tops out well under 5; anything above 8 is a data error.
MAX_REASONABLE_DENSITY = 8.0

# Default scene-log encoding domain (stops relative to 18% gray). Wide on
# purpose: the negative's toe/shoulder do the creative compression, and a
# clipped domain would pre-crush what the curve is supposed to shape.
DEFAULT_STOP_RANGE = (-10.0, 6.0)
MID_GRAY = 0.18


# ---------------------------------------------------------------------------
# density <-> transmittance
# ---------------------------------------------------------------------------

def density_to_transmittance(d: float) -> float:
    """Optical density -> fraction of light transmitted. T = 10^(-D)."""
    return 10.0 ** (-d)


def transmittance_to_density(t: float) -> float:
    """Fraction of light transmitted -> optical density. D = -log10(T).
    Transmittance is floored at MIN_TRANSMITTANCE so a zero never produces
    infinity — it produces a very dense (but finite) result instead."""
    return -math.log10(max(t, MIN_TRANSMITTANCE))


# ---------------------------------------------------------------------------
# scene-linear <-> normalized log exposure
# ---------------------------------------------------------------------------

def scene_linear_to_log(lin: float,
                        min_stops: float = DEFAULT_STOP_RANGE[0],
                        max_stops: float = DEFAULT_STOP_RANGE[1]) -> float:
    """Encode relative scene-linear light into the normalized 0..1 log domain
    a generated LUT samples. 18% gray sits at stops == 0. Values outside the
    configured stop range clamp — the range is recorded in profiles/reports
    so a clamp is visible, never silent-and-unknowable."""
    stops = math.log2(max(lin, 1e-10) / MID_GRAY)
    enc = (stops - min_stops) / (max_stops - min_stops)
    return min(1.0, max(0.0, enc))


def log_to_scene_linear(enc: float,
                        min_stops: float = DEFAULT_STOP_RANGE[0],
                        max_stops: float = DEFAULT_STOP_RANGE[1]) -> float:
    """Inverse of scene_linear_to_log for in-domain values."""
    stops = min_stops + min(1.0, max(0.0, enc)) * (max_stops - min_stops)
    return MID_GRAY * (2.0 ** stops)


# ---------------------------------------------------------------------------
# monotone curve interpolation
# ---------------------------------------------------------------------------

def _fc_tangents(xs, ys):
    """Fritsch–Carlson tangents for a monotone cubic Hermite interpolant.
    On monotone data this guarantees a monotone interpolant — the property
    that makes 'no overshoot beyond the sampled densities' a theorem here
    rather than a hope."""
    n = len(xs)
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        m[i] = 0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2.0
    for i in range(n - 1):
        if d[i] == 0.0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9.0:                      # limit circle: keeps monotonicity
            t = 3.0 / math.sqrt(s)
            m[i] = t * a * d[i]
            m[i + 1] = t * b * d[i]
    return m


class CharacteristicCurve:
    """One film layer's response: sampled (log_exposure, density) points,
    evaluated with monotone cubic interpolation, clamped to the layer's
    density bounds, held flat outside the sampled exposure domain (a film
    curve's toe and shoulder really do go flat)."""

    def __init__(self, points, d_min: float, d_max: float,
                 interpolation: str = "monotonic_cubic"):
        pts = [(float(x), float(y)) for x, y in points]
        if len(pts) < 2:
            raise ValueError("curve needs at least 2 points")
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise ValueError("curve log-exposure values must strictly increase")
        if any(b < a for a, b in zip(ys, ys[1:])):
            raise ValueError("curve density must never decrease with exposure")
        if not all(math.isfinite(v) for v in xs + ys):
            raise ValueError("curve contains a non-finite value")
        if not (d_min < d_max):
            raise ValueError("d_min must be below d_max")
        self.xs, self.ys = xs, ys
        self.d_min, self.d_max = float(d_min), float(d_max)
        self.interpolation = interpolation
        self._m = _fc_tangents(xs, ys) if interpolation == "monotonic_cubic" else None

    def density(self, log_exposure: float) -> float:
        xs, ys = self.xs, self.ys
        if log_exposure <= xs[0]:
            return self._clamp(ys[0])
        if log_exposure >= xs[-1]:
            return self._clamp(ys[-1])
        # locate the interval (curves are short — linear scan is fine and
        # avoids an off-by-one; bisect would work identically)
        i = 0
        while xs[i + 1] < log_exposure:
            i += 1
        h = xs[i + 1] - xs[i]
        t = (log_exposure - xs[i]) / h
        if self._m is None:              # linear fallback
            y = ys[i] + (ys[i + 1] - ys[i]) * t
        else:
            t2, t3 = t * t, t * t * t
            h00 = 2 * t3 - 3 * t2 + 1
            h10 = t3 - 2 * t2 + t
            h01 = -2 * t3 + 3 * t2
            h11 = t3 - t2
            y = (h00 * ys[i] + h10 * h * self._m[i]
                 + h01 * ys[i + 1] + h11 * h * self._m[i + 1])
        return self._clamp(y)

    def _clamp(self, y: float) -> float:
        return min(self.d_max, max(self.d_min, y))

    def sample(self, n: int = 64):
        """n evenly spaced (log_exposure, density) samples across the curve's
        domain — the shape LUT generation will consume."""
        x0, x1 = self.xs[0], self.xs[-1]
        return [(x0 + (x1 - x0) * i / (n - 1),
                 self.density(x0 + (x1 - x0) * i / (n - 1)))
                for i in range(n)]

    def fingerprint(self) -> str:
        """Stable content hash — one ingredient of the LUT cache key. Byte
        determinism here is what makes 'same settings, same LUT' testable."""
        payload = json.dumps(
            {"xs": self.xs, "ys": self.ys, "d_min": self.d_min,
             "d_max": self.d_max, "interp": self.interpolation},
            sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# stock-profile schema
# ---------------------------------------------------------------------------

def _is_3x3(m) -> bool:
    return (isinstance(m, (list, tuple)) and len(m) == 3
            and all(isinstance(r, (list, tuple)) and len(r) == 3
                    and all(isinstance(v, (int, float)) and math.isfinite(v)
                            for v in r)
                    for r in m))


def validate_profile(data) -> list:
    """Return a list of human-readable problems (empty list = valid).
    Deliberately a report, not an exception, so a validation CLI can show
    everything wrong at once instead of one error per run."""
    errs = []
    if not isinstance(data, dict):
        return ["profile is not a JSON object"]

    if data.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version must be {SCHEMA_VERSION} "
                    f"(got {data.get('schema_version')!r})")
    ptype = data.get("profile_type")
    if ptype not in ("negative", "print"):
        errs.append(f"profile_type must be 'negative' or 'print' (got {ptype!r})")
    if not isinstance(data.get("profile_id"), str) or not data.get("profile_id"):
        errs.append("profile_id must be a non-empty string")

    rng = data.get("density_storage_range")
    if (not isinstance(rng, (list, tuple)) or len(rng) != 2
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rng)
            or not rng[0] < rng[1] or rng[1] > MAX_REASONABLE_DENSITY):
        errs.append("density_storage_range must be [lo, hi] with lo < hi "
                    f"<= {MAX_REASONABLE_DENSITY}")

    layers = data.get("layers")
    if not isinstance(layers, dict) or set(layers) != {"red", "green", "blue"}:
        errs.append("layers must contain exactly red, green, blue")
    else:
        for name, layer in layers.items():
            if not isinstance(layer, dict):
                errs.append(f"layer {name} is not an object")
                continue
            try:
                CharacteristicCurve(layer.get("curve") or [],
                                    layer.get("d_min", 0.0),
                                    layer.get("d_max", 0.0))
            except (ValueError, TypeError) as exc:
                errs.append(f"layer {name}: {exc}")
                continue
            dmin, dmax = layer["d_min"], layer["d_max"]
            if dmax > MAX_REASONABLE_DENSITY:
                errs.append(f"layer {name}: d_max {dmax} is not a plausible density")
            ys = [p[1] for p in layer["curve"]]
            if min(ys) < dmin - 1e-9 or max(ys) > dmax + 1e-9:
                errs.append(f"layer {name}: curve leaves the d_min..d_max range")

    if ptype == "negative":
        if not _is_3x3(data.get("sensitivity_matrix")):
            errs.append("negative profile needs a finite 3x3 sensitivity_matrix")
        hal = data.get("halation")
        if hal is not None:
            if not isinstance(hal, dict) or not _is_3x3(hal.get("matrix")):
                errs.append("halation, when present, needs a 3x3 matrix")
    if ptype == "print":
        if not _is_3x3(data.get("printer_matrix")):
            errs.append("print profile needs a finite 3x3 printer_matrix")
        lights = data.get("neutral_printer_lights")
        if (not isinstance(lights, (list, tuple)) or len(lights) != 3
                or not all(isinstance(v, (int, float)) for v in lights)):
            errs.append("print profile needs neutral_printer_lights [r, g, b]")

    return errs


def load_profile(path) -> dict:
    """Read + validate a profile JSON. Raises ValueError listing every
    problem, so a bad file fails loudly and completely."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p} is not valid JSON: {exc}") from exc
    errs = validate_profile(data)
    if errs:
        raise ValueError(f"{p} failed validation:\n  - " + "\n  - ".join(errs))
    return data


def profile_curves(profile: dict) -> dict:
    """The three layer curves of a validated profile, ready to evaluate."""
    return {name: CharacteristicCurve(layer["curve"],
                                      layer["d_min"], layer["d_max"])
            for name, layer in profile["layers"].items()}


def profile_fingerprint(profile: dict) -> str:
    """Stable content hash of a whole profile — cache-key ingredient.
    Key order in the source JSON must not matter, so it's canonicalized."""
    payload = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# built-in generic profiles
# ---------------------------------------------------------------------------
# Placeholder numbers for implementation and validation. The names are
# descriptive on purpose ('a modern high-speed tungsten negative'), NOT
# claims about any commercial stock — a profile may only claim an exact
# stock match when built from real, legally usable measurement data.

GENERIC_NEGATIVE = {
    "schema_version": 1,
    "profile_id": "modern_500t",
    "display_name": "Modern 500T",
    "profile_type": "negative",
    "description": "A generic modern tungsten-balanced high-speed negative. "
                   "Placeholder values, not a commercial stock measurement.",
    "nominal_ei": 500,
    "balance_kelvin": 3200,
    "working_space": "linear_bt2020",
    "scene_stop_range": [-10.0, 6.0],
    "density_storage_range": [0.0, 3.5],
    "sensitivity_matrix": [
        [0.92, 0.06, 0.02],
        [0.04, 0.92, 0.04],
        [0.02, 0.09, 0.89],
    ],
    "layers": {
        # Channel curves share one shape, offset by base density. Parallel
        # curves mean the printer's per-channel timing neutralizes the WHOLE
        # gray ramp, not just the patch it was calibrated on — deliberate
        # crossover can come later from a curve that earns it.
        "red":   {"d_min": 0.18, "d_max": 2.85,
                  "curve": [[-4.0, 0.18], [-2.0, 0.28], [0.0, 1.05],
                            [2.0, 2.20], [4.0, 2.78]]},
        "green": {"d_min": 0.20, "d_max": 2.87,
                  "curve": [[-4.0, 0.20], [-2.0, 0.30], [0.0, 1.07],
                            [2.0, 2.22], [4.0, 2.80]]},
        "blue":  {"d_min": 0.24, "d_max": 2.91,
                  "curve": [[-4.0, 0.24], [-2.0, 0.34], [0.0, 1.11],
                            [2.0, 2.26], [4.0, 2.84]]},
    },
    "halation": {
        "threshold_stops": 0.5,
        "radius_pixels_at_2k": 60.0,
        "strength": 0.40,
        "matrix": [
            [1.00, 0.18, 0.05],
            [0.15, 0.30, 0.04],
            [0.02, 0.03, 0.02],
        ],
    },
    "grain": {
        "reference_gauge": "35mm",
        # RMS granularity per layer (diffuse RMS density x1000 at 1.0D over a
        # 0.048mm aperture — the standard microdensitometer measure). Blue
        # (fastest, largest crystals) is grainiest; red finest. These set the
        # amplitude in physical density units, not an arbitrary slider.
        "rms_granularity": [9.0, 10.0, 13.0],
        # Silver-halide grain has a CRYSTAL SIZE DISTRIBUTION, not one clump
        # size — a fine high-frequency layer plus a sparser large-crystal
        # low-frequency layer. The single-scale Gaussian field is the tell of
        # synthetic grain; summing two scales breaks it. Values are clump
        # radii in px at the reference 2K width, and each layer's share of
        # the total variance.
        "crystal_scales": [
            {"radius_2k": 1.1, "weight": 0.68},
            {"radius_2k": 3.2, "weight": 0.32},
        ],
        # Grain is strongest where the negative is THIN (shadows): relative
        # density fluctuation is largest at low density, and faster/larger
        # crystals live in the shadow-sensitive toe. So the mask RISES toward
        # D-min and falls toward the dense highlights — the opposite of an
        # overlay, and the opposite of the old mid-peaked curve.
        "density_amplitude_curve": [
            [0.0, 1.00], [0.15, 0.95], [0.4, 0.70],
            [0.7, 0.45], [1.0, 0.28],
        ],
        # Independent R/G/B emulsion layers -> color grain is decorrelated
        # from luma, not tinted luma. But grain is MOSTLY luminance: only a
        # small fraction is decorrelated colour, or independent layers
        # produce "rainbow" R/G/B speckle (digital-compression look). chroma
        # is that small fraction; grain_saturation clamps residual colour.
        "layer_correlation": 0.15,
        "chroma_weight": 0.12,
        "grain_saturation": 0.45,
    },
    "development_defaults": {
        "push_pull_stops": 0.0,
        "gamma_multiplier": 1.0,
        "fog_density": 0.0,
    },
}

# Print stock reads the negative's transmitted light: more print exposure
# means more print density means a darker patch on screen. Steeper than the
# negative — that's where theatrical contrast comes from.
GENERIC_PRINT = {
    "schema_version": 1,
    "profile_id": "neutral_release",
    "display_name": "Neutral Release Print",
    "profile_type": "print",
    "description": "A generic neutral release print stock. Placeholder "
                   "values, not a commercial stock measurement.",
    "density_storage_range": [0.0, 4.0],
    "neutral_printer_lights": [25, 25, 25],
    "light_point_stops": 0.025,
    "printer_matrix": [
        [0.90, 0.07, 0.03],
        [0.05, 0.90, 0.05],
        [0.03, 0.09, 0.88],
    ],
    "layers": {
        # Same parallel-shape discipline as the negative (see note there).
        # Mid-scale slope ~2.5 D/logE: with the negative's ~0.575 that gives
        # the ~1.45 system gamma a theatrical print chain actually has.
        "red":   {"d_min": 0.08, "d_max": 3.60,
                  "curve": [[-3.0, 0.08], [-2.6, 0.12], [-2.2, 0.40],
                            [-1.8, 1.35], [-1.4, 2.40], [-1.0, 3.15],
                            [-0.6, 3.48], [0.0, 3.58], [0.4, 3.60]]},
        "green": {"d_min": 0.08, "d_max": 3.60,
                  "curve": [[-3.0, 0.08], [-2.6, 0.12], [-2.2, 0.40],
                            [-1.8, 1.35], [-1.4, 2.40], [-1.0, 3.15],
                            [-0.6, 3.48], [0.0, 3.58], [0.4, 3.60]]},
        "blue":  {"d_min": 0.10, "d_max": 3.62,
                  "curve": [[-3.0, 0.10], [-2.6, 0.14], [-2.2, 0.42],
                            [-1.8, 1.37], [-1.4, 2.42], [-1.0, 3.17],
                            [-0.6, 3.50], [0.0, 3.60], [0.4, 3.62]]},
    },
    "projection": {
        "flare": 0.004,
        "black_floor": 0.002,
        "white_scale": 0.96,
    },
}

BUILTIN_PROFILES = {
    p["profile_id"]: p for p in (GENERIC_NEGATIVE, GENERIC_PRINT)
}


def get_builtin(profile_id: str) -> dict:
    """A deep copy of a built-in profile (callers may mutate freely)."""
    try:
        return copy.deepcopy(BUILTIN_PROFILES[profile_id])
    except KeyError:
        raise ValueError(
            f"unknown built-in profile {profile_id!r} "
            f"(have: {', '.join(sorted(BUILTIN_PROFILES))})") from None


# ---------------------------------------------------------------------------
# CLI: --selftest / --validate
# ---------------------------------------------------------------------------

def _selftest() -> int:
    ok = True

    def chk(name, cond):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # density <-> transmittance round trip, D = 0..5
    worst = max(abs(transmittance_to_density(density_to_transmittance(d / 10)) - d / 10)
                for d in range(0, 51))
    chk(f"density round trip 0..5 (worst err {worst:.2e})", worst < 1e-9)

    # log encode round trip
    worst = max(abs(log_to_scene_linear(scene_linear_to_log(v)) - v)
                for v in (0.001, 0.01, 0.18, 1.0, 4.0, 10.0))
    chk("scene-log round trip", worst < 1e-6)

    # every built-in validates and its curves are monotone with no overshoot
    for pid, prof in BUILTIN_PROFILES.items():
        errs = validate_profile(prof)
        chk(f"builtin {pid} validates", not errs)
        for e in errs:
            print(f"        - {e}")
        for name, curve in profile_curves(prof).items():
            dense = [curve.density(curve.xs[0]
                     + (curve.xs[-1] - curve.xs[0]) * i / 500) for i in range(501)]
            mono = all(b >= a - 1e-9 for a, b in zip(dense, dense[1:]))
            bounded = all(curve.d_min - 1e-9 <= v <= curve.d_max + 1e-9 for v in dense)
            finite = all(math.isfinite(v) for v in dense)
            chk(f"builtin {pid}/{name} monotone, bounded, finite",
                mono and bounded and finite)

    print("all green" if ok else "FAILURES above")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(
        description="filmify photochemical foundation — density math and "
                    "stock profiles. No rendering happens here.")
    ap.add_argument("--selftest", action="store_true",
                    help="run the built-in invariant checks")
    ap.add_argument("--validate", type=Path, metavar="PROFILE.json",
                    help="validate a stock-profile JSON file")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(_selftest())
    if args.validate:
        try:
            data = load_profile(args.validate)
        except ValueError as exc:
            sys.exit(f"INVALID\n{exc}")
        print(f"VALID: {data['profile_id']} ({data['profile_type']}) — "
              f"fingerprint {profile_fingerprint(data)[:12]}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
