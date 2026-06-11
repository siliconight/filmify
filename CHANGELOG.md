# Changelog

All notable changes to filmify are documented here.
Versioning follows [SemVer](https://semver.org).

## [0.4.0] — 2026-06-11

### Added
- B&W film mode (`--bw`): panchromatic-weighted mono conversion (red-favoring
  vs Rec.709 luma, so skin renders bright and skies darker), neutral halation
  instead of red-orange, and 1.5× grain. A deliberate, forgiving finish for
  productions without a colorist.
- Chroma softening: film's color layers resolve softer than its luminance,
  so the chroma planes (only) get a gentle blur. Per-preset strength,
  override with `--chroma-soften` (0 disables). Kills the digital crispness
  of color edges while leaving detail untouched.
- Per-preset contrast character: each preset now has its own curve *shape*,
  not just amount — `subtle` keeps near-neutral mids with a soft shoulder,
  `standard` concentrates contrast in the midtones like a print stock,
  `heavy` lifts/fades blacks with lower-mid contrast and a compressed top.
  All keep the protected-highlight shoulder.

### Changed
- Preset definition: explicit `curve` point strings replace the shared
  `black_lift`/`shoulder` parameters.

## [0.3.0] — 2026-06-11

### Added
- Preview mode (`--preview [seconds]`, default 5): renders only the first
  N seconds with a fast encode preset, for quick look iteration before
  committing to a full render.
- Batch processing: pass a folder as input and every video file in it is
  processed into a `filmified/` subfolder (or `-o <folder>`). Files already
  carrying a `_film`/`_preview` suffix are skipped, so reruns are safe.
- Gate weave (`--weave PX`): slow frame drift built from layered sines per
  axis — reads as film transport through a projector gate, not digital
  jitter. Off by default; 1–2 px is the sweet spot. Aspect ratio is
  preserved (`setsar=1` after the scale-back).

### Changed
- ffmpeg output quieted to warnings + progress stats so batch runs are
  readable.

## [0.2.0] — 2026-06-11

### Added
- Real grain plate support (`--grain-plate`): overlay a scanned film grain
  video, automatically looped, scaled/cropped to cover the frame, and
  overlay-blended. Per-preset default opacity, override with
  `--plate-opacity`.
- Film-stock 3D LUT support (`--lut file.cube`), applied after the tone
  curve. When a LUT is supplied, the built-in split tone is skipped so the
  LUT owns the color character. Windows paths are escaped correctly.
- `--no-curve` to disable the built-in filmic curve (for LUTs that include
  their own tone mapping).
- `--version` flag and `__version__` string.
- Input validation for LUT and grain plate paths.

### Changed
- Synthesized grain is now the fallback when no grain plate is given.
- `eq=saturation` is skipped entirely when saturation is 1.0.

## [0.1.0] — 2026-06-11

### Added
- Initial release. Single-file FFmpeg pipeline:
  - 24 fps conform with simulated 180° shutter (frame blending)
  - gentle de-sharpening
  - filmic S-curve with protected highlights and lifted blacks
  - mild desaturation + warm-highlight / cool-shadow split tone
  - halation (highlight isolation → wide blur → red-orange tint → screen)
  - synthesized temporal luma-weighted grain
  - subtle vignette
  - `subtle` / `standard` / `heavy` presets with per-component overrides
  - x264 encoding with `-tune grain`
