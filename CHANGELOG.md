# Changelog

All notable changes to filmify are documented here.
Versioning follows [SemVer](https://semver.org).

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
