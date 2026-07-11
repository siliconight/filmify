#!/usr/bin/env python3
"""
test_photochemical.py — unit tests for the photochemical foundation
(photochemical.py) plus the --pipeline flag contract in filmify.py.

These lock the TDD section 26.1 invariants: density round trips, curve
monotonicity, bounds, determinism, and the schema-v1-look protection
(look files must not silently start selecting a different pipeline).

Run directly (python test_photochemical.py) or via pytest.
"""

import importlib.util
import math
import subprocess
import sys

try:
    import pytest
except ImportError:                       # stdlib-only __main__ fallback
    class _NoPytest:
        class mark:
            @staticmethod
            def xfail(*a, **k):
                def deco(fn):
                    fn._xfail = True
                    return fn
                return deco
    pytest = _NoPytest()
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "photochemical", ROOT / "photochemical.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pc = _load()


# --- density <-> transmittance ---------------------------------------------

def test_density_round_trip_0_to_5():
    for i in range(0, 501):
        d = i / 100.0
        assert abs(pc.transmittance_to_density(
            pc.density_to_transmittance(d)) - d) < 1e-9


def test_zero_transmittance_stays_finite():
    d = pc.transmittance_to_density(0.0)
    assert math.isfinite(d) and d > 5.0


# --- scene-log encoding ------------------------------------------------------

def test_scene_log_round_trip_and_anchors():
    for v in (0.001, 0.01, 0.18, 1.0, 4.0, 10.0):
        assert abs(pc.log_to_scene_linear(pc.scene_linear_to_log(v)) - v) < 1e-6
    # 18% gray = 0 stops = 10/16 of the -10..+6 domain
    assert abs(pc.scene_linear_to_log(0.18) - 10.0 / 16.0) < 1e-9
    # out-of-domain clamps to the ends, never wraps or explodes
    assert pc.scene_linear_to_log(1e9) == 1.0
    assert pc.scene_linear_to_log(0.0) == 0.0


# --- characteristic curves ---------------------------------------------------

def _dense(curve, n=500):
    x0, x1 = curve.xs[0], curve.xs[-1]
    return [curve.density(x0 + (x1 - x0) * i / n) for i in range(n + 1)]


def test_curve_passes_through_knots():
    c = pc.CharacteristicCurve([[-4, 0.2], [0, 1.1], [4, 2.8]], 0.2, 2.9)
    for x, y in zip(c.xs, c.ys):
        assert abs(c.density(x) - y) < 1e-9


def test_curve_monotone_bounded_finite_no_overshoot():
    for prof in pc.BUILTIN_PROFILES.values():
        for name, c in pc.profile_curves(prof).items():
            vals = _dense(c)
            assert all(math.isfinite(v) for v in vals), (prof["profile_id"], name)
            assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:])), \
                f"{prof['profile_id']}/{name} not monotone"
            assert all(c.d_min - 1e-9 <= v <= c.d_max + 1e-9 for v in vals), \
                f"{prof['profile_id']}/{name} overshoots its density bounds"


def test_curve_flat_outside_domain():
    c = pc.CharacteristicCurve([[-2, 0.3], [2, 2.0]], 0.3, 2.0)
    assert c.density(-100) == 0.3
    assert c.density(+100) == 2.0


def test_linear_fallback_matches_knots_and_stays_monotone():
    c = pc.CharacteristicCurve([[-4, 0.2], [0, 1.1], [4, 2.8]], 0.2, 2.9,
                               interpolation="linear")
    vals = _dense(c)
    assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))
    assert abs(c.density(0) - 1.1) < 1e-9


def test_curve_rejects_bad_data():
    for bad in (
        [[0, 1.0]],                       # one point
        [[0, 1.0], [0, 2.0]],             # non-increasing x
        [[0, 2.0], [1, 1.0]],             # decreasing density
        [[0, float("nan")], [1, 1.0]],    # non-finite
    ):
        try:
            pc.CharacteristicCurve(bad, 0.0, 3.0)
            assert False, f"accepted bad curve {bad}"
        except (ValueError, TypeError):
            pass


def test_determinism_fingerprints():
    a = pc.CharacteristicCurve([[-4, 0.2], [0, 1.1], [4, 2.8]], 0.2, 2.9)
    b = pc.CharacteristicCurve([[-4, 0.2], [0, 1.1], [4, 2.8]], 0.2, 2.9)
    assert a.fingerprint() == b.fingerprint()
    assert a.sample(65) == b.sample(65)
    # profile fingerprint ignores key order (irrelevant ordering must not
    # change a future LUT cache hash)
    p1 = pc.get_builtin("modern_500t")
    p2 = dict(reversed(list(p1.items())))
    assert pc.profile_fingerprint(p1) == pc.profile_fingerprint(p2)
    # but any relevant value change must change it (get_builtin deep-copies,
    # so p3 is independent of p1)
    p3 = pc.get_builtin("modern_500t")
    p3["layers"]["red"]["d_max"] += 0.01
    assert pc.profile_fingerprint(p1) != pc.profile_fingerprint(p3)


# --- profile schema ----------------------------------------------------------

def test_builtin_profiles_validate():
    for pid, prof in pc.BUILTIN_PROFILES.items():
        assert pc.validate_profile(prof) == [], pid


def test_validation_catches_breakage():
    p = pc.get_builtin("modern_500t")
    p["layers"]["green"]["curve"][2][1] = 9.9        # leaves d range, breaks mono
    assert pc.validate_profile(p)

    p = pc.get_builtin("modern_500t")
    p["sensitivity_matrix"] = [[1, 0], [0, 1]]        # not 3x3
    assert pc.validate_profile(p)

    p = pc.get_builtin("neutral_release")
    del p["printer_matrix"]
    assert pc.validate_profile(p)

    p = pc.get_builtin("modern_500t")
    p["schema_version"] = 99
    assert pc.validate_profile(p)

    assert pc.validate_profile("not a dict")
    assert pc.validate_profile({})


def test_load_profile_round_trip(tmp_path=None):
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "p.json"
        f.write_text(json.dumps(pc.GENERIC_NEGATIVE), encoding="utf-8")
        assert pc.load_profile(f)["profile_id"] == "modern_500t"
        f.write_text("{ nope", encoding="utf-8")
        try:
            pc.load_profile(f)
            assert False, "accepted invalid JSON"
        except ValueError:
            pass


# --- filmify.py --pipeline contract ------------------------------------------

def test_pipeline_flag_contract():
    # photochemical accepts the flag; a missing file is a missing-file error
    r = subprocess.run(
        [sys.executable, str(ROOT / "filmify.py"),
         "_no_such_clip_.mp4", "--pipeline", "photochemical"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "not found" in (r.stdout + r.stderr)
    # unknown negative stock fails with the available list
    r = subprocess.run(
        [sys.executable, str(ROOT / "filmify.py"),
         "_no_such_clip_.mp4", "--pipeline", "photochemical",
         "--negative-stock", "kodak_5219"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "modern_500t" in (r.stdout + r.stderr)
    # a photochemical print profile without the pipeline flag gets a hint
    r = subprocess.run(
        [sys.executable, str(ROOT / "filmify.py"),
         "_no_such_clip_.mp4", "--print-stock", "neutral_release"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "--pipeline photochemical" in (r.stdout + r.stderr)
    # legacy: flag accepted, failure (if any) is about the missing file
    r = subprocess.run(
        [sys.executable, str(ROOT / "filmify.py"),
         "_no_such_clip_.mp4", "--pipeline", "legacy"],
        capture_output=True, text=True, timeout=60)
    assert "not found" in (r.stdout + r.stderr)


# --- LUT generation (TDD 26.2) ----------------------------------------------

def _lg():
    spec = importlib.util.spec_from_file_location(
        "lut_generation", ROOT / "lut_generation.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _parse_cube(path):
    size, rows = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("LUT_3D_SIZE"):
            size = int(line.split()[1])
        elif line and line[0] in "0123456789.-":
            rows.append(tuple(float(v) for v in line.split()))
    return size, rows


def test_cube_files_valid():
    lg = _lg()
    neg = pc.get_builtin("modern_500t")
    prt = pc.get_builtin("neutral_release")
    for path in (lg.negative_lut(neg, size=17),
                 lg.print_lut(neg, prt, size=17)):
        size, rows = _parse_cube(path)
        assert size == 17
        assert len(rows) == 17 ** 3, path
        for row in rows:
            assert len(row) == 3
            assert all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in row), row


def test_lut_cache_determinism():
    lg = _lg()
    neg = pc.get_builtin("modern_500t")
    prt = pc.get_builtin("neutral_release")
    a = lg.print_lut(neg, prt, size=17)
    b = lg.print_lut(neg, prt, size=17)
    assert a == b                                    # cache hit, same key
    data = a.read_bytes()
    a.unlink()
    c = lg.print_lut(neg, prt, size=17)
    assert c.read_bytes() == data                    # byte-identical regen
    d = lg.print_lut(neg, prt, printer_lights=(33, 25, 25), size=17)
    assert d != a                                    # relevant change, new key


def test_density_is_not_rgb_inversion():
    """TDD 27.1.4 at the math level: the negative LUT's gray-axis response
    must not be 1 - input."""
    lg = _lg()
    neg = pc.get_builtin("modern_500t")
    size, rows = _parse_cube(lg.negative_lut(neg, size=17))
    diffs = []
    for i in range(size):
        v = i / (size - 1)
        idx = i + i * size + i * size * size          # gray axis, r fastest
        diffs.append(abs(rows[idx][1] - (1.0 - v)))
    assert max(diffs) > 0.15, "negative density looks like an RGB inversion"


# --- full-chain FFmpeg renders (TDD 27.1, 27.3) ------------------------------

def _rgb_at(path, x, y=32):
    d = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
         f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return tuple(d[:3]) if len(d) >= 3 else None


def _render(src, out, *extra):
    r = subprocess.run(
        [sys.executable, str(ROOT / "filmify.py"), str(src), "-o", str(out),
         "--pipeline", "photochemical", "--no-report", "--no-hwaccel",
         *extra],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert Path(out).exists()


def test_photochemical_chain_renders():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ramp = td / "ramp.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "gradients=s=256x64:c0=black:c1=white:x0=0:y0=32:x1=255:y1=32"
             ":n=2:d=1:r=24",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(ramp)], check=True, timeout=120)

        # 27.1.1/27.1.9: full chain, monotone luminance, neutral gray ramp.
        # Grain OFF here — per-channel grain intentionally adds channel
        # variance now (blue grainiest), which is verified in the grain
        # tests; neutrality is a property of the base development.
        out = td / "out.mp4"
        _render(ramp, out, "--grain", "0")
        prev, worst_spread = -1, 0
        for x in (8, 40, 72, 104, 136, 168, 200, 232):
            px = _rgb_at(out, x)
            assert px is not None
            worst_spread = max(worst_spread, max(px) - min(px))
            lum = sum(px) / 3
            assert lum >= prev - 2, "output not monotone with exposure"
            prev = lum
        assert worst_spread <= 4, f"gray ramp not neutral (spread {worst_spread})"
        mid = _rgb_at(out, 104)
        assert abs(sum(mid) / 3 - 103) <= 8, f"mid-gray drifted: {mid}"

        # 27.3: +8 red printer points prints denser red = less red out.
        # Grain off for a clean per-channel read (grain adds channel spread).
        red = td / "red.mp4"
        _render(ramp, red, "--grain", "0", "--printer-lights", "33,25,25")
        n, r = _rgb_at(out, 104), _rgb_at(red, 104)
        assert n[0] - r[0] >= 10, f"red light had no effect: {n} -> {r}"
        assert abs(n[2] - r[2]) <= 5, f"blue moved with red light: {n} -> {r}"

        # 27.1.3/27.1.4: density debug render rises with exposure and is
        # not an RGB inversion
        dens = td / "dens.mp4"
        _render(ramp, dens, "--grain", "0", "--debug-stage", "negative-density")
        lo, mi, hi = (_rgb_at(dens, x) for x in (8, 104, 232))
        assert lo[1] < mi[1] < hi[1], f"density not rising: {lo} {mi} {hi}"
        assert abs(mi[1] - (255 - 103)) > 30, "density looks like 1 - RGB"


# --- Milestone 2: halation in exposure space, grain in density space --------

def test_split_negative_composition_matches_fused():
    """The exposure LUT composed with the response LUT must reproduce the
    fused negative LUT — halation being ON must not change the base
    chemistry, only add the halo."""
    lg = _lg()
    neg = pc.get_builtin("modern_500t")
    n = 33
    _, fused = _parse_cube(lg.negative_lut(neg, size=n))
    _, expo = _parse_cube(lg.exposure_lut(neg, size=n))
    _, resp = _parse_cube(lg.negative_response_lut(neg, size=n))

    def resp_gray(v, ch):        # linear interp along the response gray axis
        t = v * (n - 1)
        i = min(n - 2, int(t))
        f = t - i
        lo = resp[i + i * n + i * n * n][ch]
        hi = resp[(i + 1) + (i + 1) * n + (i + 1) * n * n][ch]
        return lo * (1 - f) + hi * f

    worst = 0.0
    for i in range(n):
        idx = i + i * n + i * n * n
        for ch in range(3):
            composed = resp_gray(expo[idx][ch], ch)
            worst = max(worst, abs(composed - fused[idx][ch]))
    assert worst < 0.02, f"split/fused negative diverge (worst {worst:.4f})"


def test_grain_mask_lut_shape():
    """The grain mask is SHADOW-WEIGHTED: grain is strongest where the
    negative is thin (low density = scene shadow) and quiets in the dense
    highlights — the opposite of an overlay, and the film-correct direction
    (relative density fluctuation is largest at low density; faster/larger
    crystals live in the shadow-sensitive toe). Blue (fastest layer, largest
    crystals) is the grainiest channel."""
    lg = _lg()
    neg = pc.get_builtin("modern_500t")
    size, rows = _parse_cube(lg.grain_mask_lut(neg))
    assert all(0.0 <= v <= 1.0 for row in rows for v in row)
    gray = [rows[i + i * size + i * size * size] for i in range(size)]
    lo, mid, hi = gray[0], gray[size // 2], gray[-1]
    for ch in range(3):
        # monotonically stronger toward low density (scene shadow)
        assert lo[ch] > mid[ch] > hi[ch], \
            "mask not shadow-weighted (should fall from D-min to D-max)"
    # blue layer grainiest, red finest, at every density
    assert lo[2] >= lo[1] >= lo[0], "blue should be the grainiest layer"


def test_graph_places_effects_at_their_stages():
    """TDD 27.1.6/27.1.7 as string order on the real filtergraph: the halo
    adds in linear before the response transform, the base develops through
    the fused negative, the two merge, and grain sits after the negative and
    before the print."""
    import argparse
    spec = importlib.util.spec_from_file_location("filmify", ROOT / "filmify.py")
    fm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fm)
    lg = _lg()
    neg = pc.get_builtin("modern_500t")
    prt = pc.get_builtin("neutral_release")
    hr = lg.HALATION_HEADROOM
    a = argparse.Namespace(
        ratio=None, conform=False, depth=8, codec="h264", lut=None,
        debug_stage=None, input_range="auto",
        soften=0.5, weave=1.2, flicker=0.3, no_vignette=False, vignette=0.5,
        _pc={"negative": "modern_500t", "print": "neutral_release",
             "lights": (25, 25, 25), "transfer": "rec709", "size": 17,
             "neg_lut": lg.negative_lut(neg, size=17),
             "exp_lut": lg.exposure_lut(neg, size=17, linear=True,
                                        headroom=hr),
             "shaper_lut": lg.log_shaper_lut(headroom=hr, size=17),
             "resp_lut": lg.negative_response_lut(neg, size=17),
             "print_lut": lg.print_lut(neg, prt, size=17),
             "preview_lut": None,
             "hal": {"thr_lin": 0.25, "headroom": hr, "radius2k": 60.0,
                     "strength": 0.4, "matrix": neg["halation"]["matrix"]},
             "grain": {"g": 7, "amp": 1.0, "div": 1.6,
                       "rms": [9.0, 10.0, 13.0],
                       "scales": [{"radius_2k": 1.1, "weight": 0.68},
                                  {"radius_2k": 3.2, "weight": 0.32}],
                       "chroma": 0.12, "plate_sat": 0.45,
                       "mask_lut": lg.grain_mask_lut(neg)}})
    info = {"width": 640, "height": 360, "fps": 24.0, "hdr": False,
            "color_range": "", "color_primaries": "", "color_space": "",
            "pix_fmt": "yuv420p"}
    g = fm.build_photochemical_graph(a, info)
    i_exp = g.index(str(a._pc["exp_lut"].name))
    i_add = g.index("[linb][halo]blend=all_mode=addition")
    i_shaper = g.index(str(a._pc["shaper_lut"].name))
    i_resp = g.index(str(a._pc["resp_lut"].name))
    i_merge = g.index("maskedmerge")
    i_grain = g.index("grainmerge")
    i_print = g.index(str(a._pc["print_lut"].name))
    assert i_exp < i_add < i_shaper < i_resp, \
        "halo does not add in linear before the response transform"
    assert i_resp < i_merge, "base/halo merge is not after development"
    assert i_merge < i_grain < i_print, \
        "grain is not between the negative merge and the print"
    assert "colorlevels=rimin=" in g and "maskedmerge" in g
    # camera -> develop -> projection: lens softness precedes the exposure
    # LUT; gate weave, lamp flicker, and lens vignette follow the print.
    i_soften = g.index("unsharp=")
    i_weave = g.index("crop=w=iw-")
    i_flicker = g.index("hue=b=")
    i_vig = g.index("vignette=angle=")
    assert i_soften < i_exp, "lens softness is not before exposure"
    assert i_print < i_weave < i_flicker < i_vig, \
        "projection stages are not after the print in physical order"
    assert g.endswith("[vout]")


def test_projection_stages_follow_the_print():
    """Lens vignette is OPT-IN in the photochemical chain — the develop
    stage is film physics and corner falloff is a lens artifact, so the
    default render leaves corners alone; --vignette 0-1 enables it.
    Rendered end-to-end so the stage actually runs, not just appears in
    the graph string."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "flat.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "color=0x9a9a9a:s=320x180:r=24:d=0.3",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(src)], check=True, timeout=120)
        plain = td / "plain.mp4"
        vig = td / "vig.mp4"
        _render(src, plain, "--grain", "0", "--halation", "0")
        _render(src, vig, "--grain", "0", "--halation", "0",
                "--vignette", "0.8")
        corner_p, corner_v = _rgb_at(plain, 6, 6), _rgb_at(vig, 6, 6)
        center_p, center_v = _rgb_at(plain, 160, 90), _rgb_at(vig, 160, 90)
        assert sum(corner_p) - sum(corner_v) >= 6, \
            f"--vignette had no effect: corner {corner_p} -> {corner_v}"
        assert abs(sum(center_v) - sum(center_p)) <= 3, \
            f"vignette moved the center: {center_p} -> {center_v}"
        # and the default is genuinely untouched: corner ~= center-field
        # brightness of the same flat source developed without lens character
        assert abs(sum(corner_p) - sum(center_p)) <= 6, \
            f"default render has forced vignette: corner {corner_p} " \
            f"vs center {center_p}"


def test_halation_leaves_clean_shadow_untouched():
    """The decoupled base path is exact: a frame with a highlight must leave
    clean shadow (far from any highlight) identical to the halation-off
    development — the linear encoding's shadow crush is masked away."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "practical.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "color=0x0a0a0a:s=256x128:r=24:d=0.5,"
             "drawbox=x=108:y=44:w=40:h=40:color=white:t=fill",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(src)], check=True, timeout=120)
        on = td / "on.mp4"
        off = td / "off.mp4"
        _render(src, on, "--grain", "0")
        _render(src, off, "--grain", "0", "--halation", "0")
        far_on, far_off = _rgb_at(on, 236, 62), _rgb_at(off, 236, 62)
        assert abs(sum(far_on) - sum(far_off)) <= 3, \
            f"halation corrupted far pixels: {far_off} -> {far_on}"


def test_halation_blooms_in_linear_light():
    """Linear-light halation: a bright practical on darkness bleeds exposure
    past its own edge (the bloom), while far clean shadow stays exactly on
    the base development. The halo also carries the stock's red bias, checked
    just outside the edge where 8-bit still resolves the channel split."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "practical.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "color=0x0a0a0a:s=256x128:r=24:d=0.5,"
             "drawbox=x=108:y=44:w=40:h=40:color=white:t=fill",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(src)], check=True, timeout=120)
        on = td / "on.mp4"
        off = td / "off.mp4"
        _render(src, on, "--grain", "0")
        _render(src, off, "--grain", "0", "--halation", "0")
        near_on, near_off = _rgb_at(on, 152, 62), _rgb_at(off, 152, 62)
        far_on, far_off = _rgb_at(on, 236, 62), _rgb_at(off, 236, 62)
        glow = sum(near_on) - sum(near_off)
        assert glow >= 5, f"no bloom past the edge: {near_off} -> {near_on}"
        # far clean shadow must stay exactly on the base (crush masked away)
        assert abs(sum(far_on) - sum(far_off)) <= 3, \
            f"halation disturbed clean shadow: {far_off} -> {far_on}"
        # red-biased halo: probe right at the edge where the split resolves
        edge_on, edge_off = _rgb_at(on, 150, 62), _rgb_at(off, 150, 62)
        assert (edge_on[0] - edge_off[0]) >= (edge_on[2] - edge_off[2]), \
            "halo lost the stock's red bias"


def test_grain_is_temporal_density_masked_and_mean_stable():
    """Grain must change frame to frame, leave the mean alone, and wear
    heavier in the mids than in the highlights (density masking)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ramp = td / "ramp.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "gradients=s=256x64:c0=black:c1=white:x0=0:y0=32:x1=255:y1=32"
             ":n=2:d=0.5:r=24",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(ramp)], check=True, timeout=120)
        gr = td / "grain.mp4"
        cl = td / "clean.mp4"
        _render(ramp, gr, "--halation", "0", "--grain", "12")
        _render(ramp, cl, "--halation", "0", "--grain", "0")

        def patch(path, x, frame=0):
            d = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                 f"select=eq(n\\,{frame}),crop=16:16:{x}:24",
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray",
                 "-"], capture_output=True).stdout
            return list(d[:256])

        def stats(vals):
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            return mean, var ** 0.5

        # temporal: mid-ramp patch differs between frames with grain on
        f0, f5 = patch(gr, 120, 0), patch(gr, 120, 5)
        assert f0 != f5, "grain pattern is frozen across frames"

        # mean stability: grained mid within a few codes of clean mid
        m_gr, s_mid = stats(f0)
        m_cl, s_mid_cl = stats(patch(cl, 120))
        assert abs(m_gr - m_cl) <= 4, f"grain shifted the mean: {m_cl} -> {m_gr}"

        # density masking: mid-ramp noisier than near-white
        _, s_hi = stats(patch(gr, 232))
        assert s_mid > s_mid_cl + 0.5, "no visible grain at mid density"
        assert s_mid > s_hi, \
            f"grain not density-masked (mid {s_mid:.2f} <= high {s_hi:.2f})"


def test_grain_is_multiscale_and_neutral():
    """Silver-halide grain, not tinted-luma noise. Two measurable properties
    separate it from a single Gaussian overlay:
      * MULTI-SCALE — a large-crystal low-frequency layer survives heavy
        downsampling far more than single-frequency noise would;
      * DECORRELATED COLOUR — the three emulsion layers are different noise,
        so per-channel grain is not identical, and blue (fastest, largest
        crystals) is the grainiest channel.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        skin = td / "skin.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "color=0xb98a6f:s=320x320:r=24:d=0.5",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(skin)], check=True, timeout=120)
        gr = td / "gr.mp4"
        _render(skin, gr, "--halation", "0", "--grain", "14")

        def gray_sigma(div):
            vf = ("select=eq(n\\,3),crop=240:240:40:40"
                  + (f",scale=iw/{div}:ih/{div}" if div > 1 else ""))
            d = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(gr), "-vf", vf,
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                capture_output=True).stdout
            v = list(d)
            m = sum(v) / len(v)
            return (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5

        full, quarter = gray_sigma(1), gray_sigma(4)
        # single-frequency noise loses almost all energy by 1/4 (~0.15-0.25);
        # a real large-crystal layer retains a clearly higher fraction
        assert quarter / max(full, 1e-6) > 0.30, \
            f"grain is single-scale (1/4 retains {quarter / full:.2f} of energy)"

        d = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(gr), "-vf",
             "select=eq(n\\,3),crop=240:240:40:40", "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True).stdout
        r, g, b = list(d[0::3]), list(d[1::3]), list(d[2::3])

        def sig(v):
            m = sum(v) / len(v)
            return (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5

        # chroma noise = std of channel differences (0 for neutral grain).
        # This is the "rainbow speckle" metric — it must be small relative to
        # the luminance grain. Fully-decorrelated colour grain reads as
        # digital-compression sparkle; real grain is luminance-dominant.
        n = len(r)
        rg = [r[i] - g[i] for i in range(n)]
        bg = [b[i] - g[i] for i in range(n)]
        lum = [(r[i] + g[i] + b[i]) / 3 for i in range(n)]
        chroma_noise = (sig(rg) + sig(bg)) / 2
        luma_noise = sig(lum)
        assert luma_noise > 1.0, "no visible grain"
        assert chroma_noise < 0.4 * luma_noise, \
            (f"grain too chromatic (rainbow risk): chroma {chroma_noise:.2f} "
             f"vs luma {luma_noise:.2f}")


def test_rotated_video_renders():
    """Portrait phone video: coded landscape + a display-rotation side data
    entry. ffprobe reports the coded size but ffmpeg autorotates on decode,
    so every generated plate must be sized to the DECODED orientation — this
    was the first bug real-machine testing found (every pipeline failed with
    a blend size mismatch). Both pipelines must render it, output upright."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        plain = td / "plain.mp4"
        rot = td / "rot.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "testsrc2=s=320x180:r=24:d=0.4",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(plain)], check=True, timeout=120)
        mk = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-display_rotation", "90",
             "-i", str(plain), "-c", "copy", str(rot)],
            capture_output=True, text=True, timeout=120)
        if mk.returncode != 0:
            return  # this ffmpeg can't author rotation metadata; skip

        def dims(path):
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0",
                 str(path)], capture_output=True, text=True, timeout=60)
            w, h = out.stdout.strip().split(",")[:2]
            return int(w), int(h)

        # photochemical
        pc_out = td / "pc.mp4"
        _render(rot, pc_out, "--grain", "5")
        assert dims(pc_out) == (180, 320), \
            f"photochemical lost the rotation: {dims(pc_out)}"
        # legacy (the original failing case: grain-plate blend size mismatch)
        leg_out = td / "leg.mp4"
        r = subprocess.run(
            [sys.executable, str(ROOT / "filmify.py"), str(rot),
             "-o", str(leg_out), "--no-report", "--no-hwaccel"],
            capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        assert dims(leg_out) == (180, 320), \
            f"legacy lost the rotation: {dims(leg_out)}"


def test_schema_v1_looks_stay_legacy():
    """TDD 15.1: schema-version-1 look files must keep selecting the legacy
    pipeline. Enforced structurally: 'pipeline' must not join LOOK_KEYS until
    the schema-v2 work lands with explicit versioning."""
    spec = importlib.util.spec_from_file_location("filmify", ROOT / "filmify.py")
    fm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fm)
    assert "pipeline" not in fm.LOOK_KEYS


def main():
    fails = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [{'XPASS' if getattr(fn, '_xfail', False) else 'PASS'}]"
                      f" {name}")
            except AssertionError as exc:
                if getattr(fn, "_xfail", False):
                    print(f"  [xfail] {name}")
                else:
                    print(f"  [FAIL] {name}  -> {exc}")
                    fails.append(name)
    print("all green" if not fails else f"FAILED: {', '.join(fails)}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
