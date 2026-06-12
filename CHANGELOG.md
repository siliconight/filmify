# Changelog

All notable changes to filmify are documented here.
Versioning follows [SemVer](https://semver.org).

## [0.12.0] — 2026-06-12

### Added
- Style presets (`--style documentary|noir|anamorphic|home-movie|epic`):
  named recipes that expand to full flag sets. Pure expansion — explicit
  flags and look files still override, and `--save-look` captures the
  resolved settings.
- Control panel (`--ui`): a browser-based parameter panel in the spirit of
  an audio plugin. Sliders for every parameter, style preset selector, an
  A/B split frame preview that re-renders as you drag (debounced,
  single-frame, seconds-fast), a scrub bar, log/LUT/grain-plate inputs, and
  Save Look / Render Full buttons with status polling. Served from a
  localhost-only stdlib HTTP server — no dependencies, no network exposure,
  still one file.

## [0.11.0] — 2026-06-11

The format-character release: emulating the gauge and the glass, not just
the emulsion.

### Added
- Anamorphic streak flare (`--flare [0-1]`, off by default): bright lights
  grow a long horizontal blue-tinted line — the signature anamorphic-lens
  artifact, emulated the way effect filters do it for spherical glass.
- Cinema aspect ratios (`--ratio`): center-crop to 2.39 (modern Scope),
  2.2 (70mm Todd-AO), 2.76 (Ultra Panavision / Hateful Eight), 1.85 (flat
  widescreen), or any custom ratio. Applied before the look and before the
  compare split, so framing matches on both halves; even dimensions
  guaranteed.
- Film gauge presets (`--gauge 16mm|35mm|70mm`): 16mm = chunkier grain,
  softer, heavier chroma bleed; 35mm = standard; 70mm = fine grain and
  cleaner (large-format epic look — its negative is ~3.5x the area of 35mm).
  Composes with `--look` and all overrides.

### Fixed
- **Halation chroma bug, present since v0.1.0**: the halation screen blend
  ran in YUV, where screen math corrupts the 0.5-centered chroma planes —
  crushing green and shifting dark scenes magenta. Invisible on bright
  saturated footage, ugly on dark scenes. All screen blends (halation,
  leak, flare) now run in RGB. Verified by pixel inspection: a dark
  neutral scene now stays dark and neutral. If dark footage processed
  with earlier versions looked oddly purple, re-render with this one.

## [0.10.0] — 2026-06-11

### Added
- Self-bootstrapping Mac launcher: `filmify-drop.command` now sets up its
  own dependencies on first run. Missing Python triggers macOS's own
  signed "install command line developer tools" dialog (which includes
  Python) with plain-language instructions. Missing FFmpeg prompts for
  consent, then downloads the official static build for the detected
  architecture — Intel from evermeet.cx (the build linked from
  ffmpeg.org), Apple Silicon from ffmpeg.martin-riedl.de — saves it next
  to the script (nothing system-wide), clears quarantine, and verifies the
  binary actually executes before proceeding. Download failures and
  wrong-architecture binaries produce clear guidance instead of cryptic
  errors. The full flow was tested end to end with simulated downloads.
- README Mac quick start rewritten as five concrete steps (download ZIP →
  right-click Open → Apple's Python dialog → FFmpeg consent → drag clip),
  noting that setup steps happen only once.

### Security note
- The launcher downloads FFmpeg binaries from third-party build servers
  (the standard distribution path for static macOS FFmpeg — ffmpeg.org
  itself links to these). It always asks before downloading, states the
  source, and never installs system-wide.

## [0.9.0] — 2026-06-11

The roadmap release: log input, light leaks, 10-bit pipeline.

### Added
- Log footage development (`--input-log`): `slog3` (Sony) and `vlog`
  (Panasonic) via LUTs generated from the manufacturers' published formulas
  (mid-gray anchors verified numerically: 0.180 / 0.179), `cineon` as a
  reasonable generic, or a path to your camera maker's official
  log-to-709 3D .cube (the right answer for C-Log, Apple Log, D-Log).
  Conversion runs before the look, with a smooth tanh highlight shoulder —
  the extended range compresses instead of clipping. Persisted in look files.
- Light leaks (`--leak [0-1]`, off by default): an intermittent warm radial
  glow from the frame edge that cycles in and out of existence over time,
  built from an animated gradients source. Blended in RGB — screen-blending
  in YUV shifts the entire frame magenta (caught in frame-extraction
  testing).
- 10-bit pipeline (`--depth 10`): the filter chain processes at 10-bit,
  reducing banding in skies, soft lighting, and halation, and leaving more
  room for further grading. Output: ProRes stays yuv422p10le, DNxHR switches
  to the HQX profile (10-bit), h264 outputs yuv420p10le. Filter support was
  verified empirically; the one 8-bit-only filter (vignette) is replaced in
  10-bit mode by a blurred luma-multiply mask so the chain never silently
  bottlenecks to 8-bit.

### Notes
- Synthesized grain (noise) processes at up to 16-bit, so it's safe in
  10-bit mode — better than previously documented.

## [0.8.0] — 2026-06-11

First-time-user experience release: closing the gap between download and
the first "wow".

### Added
- Drop launchers: `filmify-drop.bat` (Windows — drag clips or a folder onto
  it) and `filmify-drop.command` (Mac — double-click, drag the clip into the
  window). Both run a `--compare --preview` split-screen test and keep the
  window open; both detect a missing Python and say exactly how to install
  it. No terminal knowledge needed for the first taste.
- Friendly no-args screen: `python filmify.py` alone prints a quickstart
  (try-this-first command + three-step workflow) instead of an argparse
  usage dump.
- First-run tip: a full-quality render of a clip longer than 30 s without
  `--preview` prints a one-line nudge toward `--compare --preview`.
- README "Your first five minutes" section with per-OS Python install
  notes, including the Windows Microsoft-Store-opens trap.
- `.gitattributes` pinning CRLF for the .bat and LF for the .command so
  line endings survive cloning on any OS.

## [0.7.0] — 2026-06-11

### Added
- HTML processing report: after every run, filmify writes
  `filmify_report.html` next to the outputs and opens it in the default
  browser. Per clip: before/after thumbnails (embedded as data URIs — the
  report is one self-contained, shareable file), ✓/✗ status with the error
  for failures, fps in → out, duration, file size, and codec. The header
  records the exact settings and look file used, so the report doubles as
  a record of how the dailies were made. `--no-report` opts out.
- Terminal summary line (`5/5 clips ✓ · report: …`).

### Changed
- Batch runs now survive a broken file: it's recorded as failed in the
  report and the run continues, instead of aborting the whole batch. The
  process exits nonzero if any clip failed.
- `probe()` raises instead of exiting, enabling the above.

## [0.6.0] — 2026-06-11

Workflow release: graded dailies and finish-pass paths, both documented.

### Added
- Mezzanine codecs (`--codec prores|dnxhr|h264`): ProRes 422 HQ and DNxHR HQ
  output in .mov with PCM audio, for the batch-then-edit workflow — they
  scrub smoothly in editors and survive the editor's re-export, unlike
  long-GOP h264. h264 remains the default for delivery/finish passes.
  Output extension is codec-aware; a wrong `-o` extension is auto-corrected
  to .mov with a note.
- Project look files: `--save-look myfilm.json` writes the effective
  settings; `--look-file myfilm.json` applies them, with explicit CLI flags
  still overriding. Relative LUT/grain-plate paths resolve against the look
  file's folder so project directories stay portable. This makes the look a
  versionable project asset — shoot day 2, weeks later, gets identical
  treatment.
- README "Workflows" section covering both paths: graded dailies
  (cohesion-first, WYSIWYG editing) and finish pass (single encode
  generation, grain/weave continuous across cuts, look adjustable to the
  end).

### Known limitation
- Internal processing is 8-bit 4:2:0 regardless of output codec; ProRes/
  DNxHR output is a faithful container for it, not a 10-bit pipeline.
  A true 10-bit path is a roadmap candidate.

## [0.5.1] — 2026-06-11

Cross-platform hardening for Windows and macOS.

### Fixed
- Windows LUT paths: drive-letter colons (`C:\luts\film.cube`) were
  double-escaped in the filtergraph and would fail to load. Now correctly
  single-backslash escaped; verified against colon-bearing paths. Paths
  containing a quote character are rejected with a clear error.
- Console output no longer crashes on Windows legacy code pages (cp1252
  etc.) when redirected to a file — non-encodable characters like `°`
  degrade gracefully instead of raising UnicodeEncodeError.
- `--version` reported 0.4.0 in the v0.5.0 release (version string was
  never bumped). The git tag was correct; the string now matches.

### Added
- Tool discovery: ffmpeg/ffprobe are found on PATH first, then next to
  filmify.py, then in the working directory — Windows users can just drop
  `ffmpeg.exe` beside the script. The not-found error now includes install
  commands for Windows (winget) and macOS (brew).

## [0.5.0] — 2026-06-11

### Added
- Compare mode (`--compare`): split-screen output with the original on the
  left half and the graded image on the right, separated by a thin divider
  line. Temporal conform applies to *both* halves so cadence matches and the
  split compares only the look. Output gets a `_compare` suffix and batch
  mode skips compare files on reruns. Pairs with `--preview` for fast look
  dialing.

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
