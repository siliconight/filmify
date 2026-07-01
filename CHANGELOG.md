# Changelog

All notable changes to filmify are documented here.
Versioning follows [SemVer](https://semver.org).

## [0.30.2] — 2026-07-01

### Fixed
- **The Mac `START-HERE-MAC.command` launcher was broken.** Its two launch
  lines ran `"$PY" filmify.py …` but `PY` was never assigned, so it expanded
  to nothing and double-clicking the launcher did nothing. Now calls `python3`
  directly, matching the sibling launchers (`filmify-drop.command`,
  `filmify-launch.sh`) that already did the right thing.

### Changed
- **Release hygiene.** Removed the two stale `filmify-mac.zip` /
  `filmify-windows.zip` copies that were committed at the repo root. The real
  release artifacts are built fresh into the git-ignored `dist/` by
  `build-packages.py` and belong on GitHub Releases; the root copies were dead
  weight. Both names are now git-ignored so they can't creep back in.
- **`build-packages.py --clean`.** New flag that strips generated cruft
  (`dist/`, `__pycache__/`, `*.log`, `*_report.html`, `sweep_*/`, smoke temp
  files, stale root zips) from a working tree without touching source or test
  footage — so a dev tree returns to a clean, shippable state.

### Tests / CI
- **Tests are now pytest-discoverable.** `test_filmify.py` and
  `test_panel_ui.py` expose `test_*` entry points (and still run as scripts).
  The panel test now `pytest.skip`s cleanly when no browser is present instead
  of silently passing.
- **New `test_launchers.py`.** Shell-lint (`bash -n` + shellcheck) plus a
  targeted guard for the `$PY` bug class: any launcher that runs an interpreter
  variable must actually assign it. Note that guard is load-bearing —
  shellcheck suppresses SC2154 for uppercase names and `bash -n` sees valid
  syntax, so neither would have caught the original bug on their own.
- **CI hardening.** Job- and step-level `timeout-minutes` on every leg; the
  panel subprocess now launches in its own process group and is torn down as a
  tree (so orphaned ffmpeg workers can't hang the runner); all setup/build
  subprocesses have explicit timeouts; a new `lint` job runs shellcheck +
  `bash -n` on the launchers.

## [0.30.1] — 2026-06-13

### Changed
- Moved the `nineties` preset out of the LOOK (INTENSITY) dropdown and into
  the Styles gallery, where era/aesthetic presets belong. The dropdown is
  once again a clean intensity ladder (subtle / standard / heavy) and the
  gallery is the front door for the 1990s look — a more prominent home with
  a live thumbnail on your own footage. Mechanically `nineties` stays a base
  look (it carries a custom tone curve and warmth, which styles can't hold);
  it's now hidden from the dropdown but still selectable by the style and via
  `--look nineties` on the CLI. The style also adds a gentle gate weave for
  90s mechanical-35mm life. Browser-verified (Playwright): gallery tile
  present, dropdown clean, clicking the tile resolves to the nineties look.

## [0.30.0] — 2026-06-13

### Added
- A `nineties` look — selectable in the panel dropdown as a main preset, and
  on the CLI (`--look nineties`). Modelled on the 1990s Spielberg / Janusz
  Kaminski theatrical-drama signature: strong, early-triggered halation so
  bright windows and practicals bloom; a compressed highlight shoulder so
  brights go milky instead of clipping; diffusion softness; a restrained,
  silvery palette with skin kept warm; print-stock midtone contrast; fine
  35mm grain. Frame-verified by rendering a window+skin test and inspecting
  the bloom, rolloff, and skin response. It's a grounded starting point, not
  a literal match — most of the Spielberg look is lighting (backlight, haze,
  blown windows) that happens before any post tool sees the frame; this leans
  footage toward that era rather than conjuring it. Tune the halation slider
  down if the bloom is too strong on a given clip.

## [0.29.1] — 2026-06-13

### Fixed
- **Dragging a video onto the import zone did nothing useful** — it opened the
  file picker instead of loading the dropped file. The drop handler read the
  dropped file's disk path, but browsers never expose that (security), so the
  check always failed and fell through to the picker. Since the server needs a
  real path to process the file (and a browser won't give one), a drop now
  honestly *is* a shortcut to the picker — and the zone says "Drop a video
  here, or click to browse" so the behavior matches the label. The whole zone
  is clickable too. Verified in a real browser (drop and click each open the
  picker exactly once, no double-fire).

## [0.29.0] — 2026-06-13

### Added
- A `vision-500t` look (CLI: `--look vision-500t`) — a tungsten-negative
  starting point modelled on documented Kodak VISION 500T characteristics
  (warm 3200K balance, restrained flesh-to-neutral saturation, clean highlight
  rolloff, slightly coarser grain, moderate halation). Verified by rendering a
  highlight+skin test frame and inspecting it. NOT in the panel dropdown yet —
  CLI-only for testing before committing the UI to stock presets. A grounded
  starting point, not a "Sopranos button": stock is only part of that look,
  lighting and lensing (which no post tool supplies) are the rest.

## [0.28.0] — 2026-06-13

### Added
- `sweep.py`: renders one clip across a parameter's range (off / DEFAULT /
  heavy) into `sweep_<param>/`, default marked in the filename — the visual
  artifact for judging whether a starting point is close enough and for
  showing testers.

### Verified (no code change)
- Log curves audited against manufacturer specs: S-Log3 matches Sony's
  Technical Summary (18% gray to code 420); V-Log matches Panasonic's
  Reference Manual constants. Both confirmed by round-trip math.
- Halation default audited against documented film optics: red-orange tint,
  highlight-threshold trigger, soft bloom, conservative intensity all match.

## [0.27.1] — 2026-06-13

### Fixed
- Help "?" chips on sliders and checkboxes now actually work (verified in a
  real browser). The chip opened the popover, then the same click bubbled to
  the document dismiss handler and closed it instantly. The chip now stops its
  own click. Two earlier attempts fixed chip creation, which was never broken.

### Added
- `test_panel_ui.py`: a headless-browser (Playwright) test that clicks each
  help chip and asserts the popover opens, dismisses, and switches. Wired into
  CI so a machine clicks the buttons on every push.

## [0.27.0] — 2026-06-13

### Added
- Windows now auto-installs Python (official python.org per-user installer,
  consent flow mirroring FFmpeg). Both platforms now fully self-bootstrap from
  the zip: download, double-click, everything else automatic.

## [0.26.0] — 2026-06-13

### Added
- Regression guard: `test_filmify.py`, a fast smoke test to run before every
  push. It checks `__version__` matches the CHANGELOG (the bug that shipped
  wrong metadata for three releases), that every style builds a filtergraph,
  that 8-bit and 10-bit both render and stay neutral (the magenta bug), that
  the panel serves and previews, and that the packages assemble with the
  clean layout. Catches most of the regressions we've actually hit.
- GitHub Actions workflow (`.github/workflows/smoke-test.yml`) running the
  smoke test on Linux, macOS, and Windows on every push — so launcher and
  platform code at least gets exercised on real OSes, even though CI can't
  click a dialog or drive a GPU.
- `RELEASE-CHECKLIST.md`: the human-only checks (native pickers surfacing,
  GPU encode, app/shortcut building) that automation can't cover.

## [0.25.0] — 2026-06-13

The "dial it in, process the whole movie, walk away" release.

### Added
- **Batch a whole folder from the panel** — a "Process whole folder…" button
  applies your exact current look to every video in a folder. Results land in
  a new timestamped `filmify_YYYY-MM-DD_HHMM` folder next to the source, so
  originals are never touched and every run is its own dated set. Set it and
  walk away.
- **Batch progress** — an overall bar plus "clip 7 of 43 — name (62%)", and a
  Show-in-folder button when the whole batch finishes. You can leave and check
  back to see exactly where it is.
- **Shot-matching toggle** in the panel (was CLI-only): measures every clip
  and nudges each toward a common exposure/white balance before the look, so
  mixed cameras and lighting come out cohesive across the movie.
- **Parameter help** — a "?" next to every control opens a plain-language
  explanation in industry-standard terms (what halation is, what gauge means,
  why you'd soften, etc.). Click anywhere to dismiss.

## [0.24.0] — 2026-06-13

### Added
- Hardware-accelerated H.264 encoding: filmify now detects and uses a GPU
  encoder when one is actually present — NVENC or Quick Sync on Windows,
  VideoToolbox on Mac — for much faster full renders on long clips. Detection
  is a real 1-frame probe-encode (an encoder being listed doesn't mean the
  machine can run it), cached per session, with automatic fallback to
  software libx264. `--no-hwaccel` forces software. Prints "encode: hardware
  (…)" when active.
- Software encodes now pass `-threads 0` so libx264 uses all cores.

### Why not a full rewrite (C++/C#)?
- filmify is an orchestrator: FFmpeg (optimized C with SIMD) does ~all the
  actual pixel work. Rewriting the thin Python layer around it would speed up
  the part that isn't the bottleneck while sacrificing the single-file,
  zero-build, runs-anywhere property and reintroducing the signing/distribution
  walls we worked around. The real speed levers are encoder choice and
  settings — addressed here — not the host language.

## [0.23.2] — 2026-06-13

### Added
- Name your export: a "Save the film as" field in the panel. Defaults to
  `<yourclip>_film`; whatever you type is sanitized of illegal characters.
- No more silent overwrites: if a file with the target name already exists,
  filmify appends `-2`, `-3`, … instead of replacing it.

### Fixed
- "Show in folder" not working on Windows: explorer was being launched with
  the no-window flag (which suppressed the very window it opens) and loose
  path quoting. It's now called directly with a properly quoted, backslashed
  path and explorer's quirky exit code ignored.

## [0.23.1] — 2026-06-13

### Fixed
- File/folder picker still opening behind the browser on Windows: the
  TopMost owner form alone wasn't winning the foreground. Now uses the
  Win32 SetForegroundWindow + BringWindowToTop APIs on an off-screen
  topmost owner to pull the dialog to the front. The waiting message also
  now points to the taskbar in case Windows still refuses the foreground
  grab (it can, by design).

## [0.23.0] — 2026-06-13

### Added
- Render progress bar: the panel now shows a live progress bar and
  percentage while a full clip renders, instead of a static "rendering full
  clip…". Parsed from ffmpeg's own `-progress` output against the clip
  duration, so it reflects real work done. The Render button disables during
  the render and the bar fills to 100% on completion before the
  "Show in folder" banner appears.

## [0.22.1] — 2026-06-13

### Fixed
- **File/folder pickers opening behind the browser:** on a fullscreen
  browser, clicking "Choose a video…" or "Save to…" opened the native
  dialog hidden behind the window, so it looked like nothing happened. The
  dialogs are now forced to the foreground — Windows via a TopMost owner
  form (and -STA PowerShell), Mac via a System Events activate. The import
  message also now says "opening file picker… (check for the dialog
  window)" so it's clear to look for it.

## [0.22.0] — 2026-06-13

Clean, user-facing downloads — one obvious thing to click.

### Added
- Per-OS packages: `filmify-mac.zip` and `filmify-windows.zip`, each
  unzipping to a folder that shows just **Start filmify** and a Read Me —
  all the machinery (filmify.py, launchers, icon, ffmpeg) is tucked into an
  `app-files/` subfolder the user never needs to open. Linked at the top of
  the README so non-technical users grab only the one for their OS.
- `build-packages.py`: regenerates both zips from the repo, reading the
  current version automatically. Run after each release. Executable bits on
  the Mac `.command` are preserved through zipping (verified).

### Note
- The flat repo layout stays as-is for development/GitHub; the clean
  packages are built from it. The two zips are committed so they're directly
  downloadable and can be attached to GitHub Releases.

## [0.21.0] — 2026-06-13

Export clarity — knowing where your finished file went.

### Added
- "Show in folder" button on the render-done banner: opens Finder/Explorer
  with the finished file highlighted (native reveal — `open -R` on Mac,
  `explorer /select,` on Windows). The fix for "okay… where did it go?"
- The done banner now reads "saved: <full path>", not just the filename.
- "Save to…" destination picker: choose where renders go (native folder
  dialog), shown live near the Render button as "saves to: <folder>".
  Defaults to next to your clip, as before.
- Destination is stated *before* you render, not just after — no surprise
  about where the file lands.

## [0.20.1] — 2026-06-13

### Fixed
- **Console-window storm on Windows:** every ffmpeg/ffprobe call spawned a
  visible cmd window, so dragging a slider in the panel flashed a window per
  preview frame. All subprocess calls now route through a wrapper that sets
  CREATE_NO_WINDOW on Windows — no flashing, on slider drags or anywhere
  else.
- **Version string was stuck at 0.17.0:** the v0.18–0.20 bumps silently
  missed (each edit targeted a string the previous miss had left stale), so
  `--version` and the processed-file metadata under-reported. Corrected, and
  the cause noted so it doesn't recur.

## [0.20.0] — 2026-06-13

Windows parity: a real app icon and a clean, console-free launch.

### Added
- `Make filmify app.bat`: run once and it creates a **filmify** shortcut —
  with the app icon — on the Desktop and in the Start menu (pin it to the
  taskbar if you like). The Windows analog of the Mac's locally-built app:
  built on the user's own machine, so it's trusted. From then on it's just
  click the icon.
- `filmify.ico`: the logo as a proper multi-size Windows icon (16–256 px),
  shipped in the repo (unlike the Mac .icns, .ico generates cleanly
  cross-platform so no build step is needed).
- `filmify-quiet.vbs`: launches everything fully windowless — no console
  flash at all, matching the Mac's silent launch.

### Changed
- The Windows launcher is now panel-first, like the Mac (v0.19): it opens
  straight to the import panel where you pick or drop a clip, instead of
  pre-picking a file and quitting on cancel. A dragged file or folder still
  works as a shortcut.

### Note
- The one unavoidable Windows prompt is SmartScreen ("Windows protected
  your PC") on first run of a downloaded file — click **More info → Run
  anyway**, once. Removing it entirely needs a code-signing certificate
  (~$200–400/yr), the Windows equivalent of Apple notarization; building
  the shortcut locally is the free workaround, same philosophy as the Mac.

## [0.19.0] — 2026-06-13

### Fixed
- **10-bit magenta bug (the pink previews):** the v0.9 10-bit vignette used
  a luma-multiply workaround built on the wrong assumption that the vignette
  filter is 8-bit-only — it mishandled the YUV chroma planes and shifted
  neutrals to magenta. Every 10-bit style (anamorphic, epic, blockbuster)
  was affected, which is why those gallery cards rendered pink. The vignette
  runs fine at 10-bit in RGB; the workaround is gone. Verified: 10-bit gray
  now renders (143,133,126), matching the 8-bit baseline, vs the broken
  (254,132,255).

### Changed
- **Panel-first flow:** `--ui` now opens the control panel immediately, with
  an import screen — a drop zone and a "Choose a video…" button — instead of
  requiring a clip up front and quitting if you didn't pick one. Import a
  clip from inside the panel (native file picker, or drag-and-drop where the
  browser exposes the path) and editing begins; the server swaps the active
  clip with no restart. The Mac app and launchers can now open straight to
  the panel.

## [0.18.2] — 2026-06-12

### Added
- After building filmify.app, the Mac builder offers to move it into
  /Applications (native dialog) so it lives with the user's other apps —
  Launchpad, Spotlight, Dock — as close to an installer as is possible
  without a paid Apple Developer account. The app's repo path is now baked
  in at build time, so it keeps working after the move.
- Logo at the top of the README, and documented the build-and-install flow.

### Note
- A true double-click `.dmg`/`.pkg` installer requires Apple notarization
  (a paid Developer account); without it, downloaded installers hit
  Gatekeeper's strictest block. The locally-built app deliberately
  sidesteps that — it's never quarantined — and the move-to-Applications
  step gives the installed-app feel for free.

## [0.18.1] — 2026-06-12

### Added
- App icon: `make-mac-app.command` now builds a proper `.icns` from the
  bundled `filmify_icon_1024.png` (via the Mac-native sips + iconutil) and
  assigns it to filmify.app, so the Dock/Finder show the real logo — the
  film-strip-into-developing-tray mark. Generated locally, same as the app.
- The control panel is branded too: the logo is the browser-tab favicon and
  sits in the panel header.

## [0.18.0] — 2026-06-12

Mac-first "just works" release: a real app icon, no Terminal.

### Added
- `make-mac-app.command`: run once (right-click → Open) and it builds a
  native **filmify.app** locally via osacompile — no Xcode, no Script
  Editor, no $99 developer account. Because the app is built on the user's
  own Mac it isn't quarantined, so every launch afterward is a clean
  double-click (and it's Dock-draggable). The one unavoidable right-click
  is on the builder, once.
- `filmify-launch.sh`: the engine behind the app. All first-run setup runs
  through native macOS dialogs and notifications — Python (via Apple's own
  installer prompt), FFmpeg consent and download — with no Terminal text to
  read. Then a native file picker, then the panel.
- Panel auto-shutdown: when launched without a terminal (the app), the
  server has no Ctrl+C, so the page sends a heartbeat and the server exits
  on its own ~30s after the browser tab closes. Verified: stays up while
  pinged, shuts down ~50s after pings stop.

### Changed
- Windows panel launch is now windowless (`pythonw` when available), so the
  console no longer lingers behind the browser.

## [0.17.0] — 2026-06-12

Forum-sourced authenticity pass — the film qualities cinematographers cite
that filmify wasn't doing.

### Added
- Skin-tone protection (on by default): desaturation now pulls non-skin
  hues the full amount and the red-yellow range only ~35%, so faces stay
  alive while the frame calms down. Fulfills the original "focus on skin
  tones" goal. Verified: a skin swatch holds saturation at 132 vs 91
  unprotected. `--no-protect-skin` for the old global behavior.
- Mid-frequency presence (`--presence`, on by default per look): wide-radius
  low-amount local contrast — the texture "pop" that counters digital's
  flat-gray-veneer complaint, without edge sharpening.
- Density flicker (`--flicker`): subtle irregular frame-to-frame exposure
  variance from layered incommensurate sines (not a strobe). Folded into
  home-movie, super8, newsreel.
- Corner softness (`--corner-soften`): field curvature — sharp center,
  softer corners, like vintage glass; the post-feasible cousin of the
  "everything's in focus" complaint. Applied before grain so grain stays
  edge-to-edge sharp.
- Aged print (`--age`): procedural dust specks plus an occasional wandering
  vertical scratch that only appears for a moment every few seconds.
  Strictly opt-in; built into super8 and newsreel.

### Fixed
- `--presence` initially used an unsharp matrix (23) past the filter's safe
  ceiling, which errored out; capped at 13.

## [0.16.0] — 2026-06-12

FTUE round two: double-click → pick → done, on both platforms.

### Added
- Native file pickers: double-clicking either launcher with nothing
  dragged now opens the OS's own file dialog (osascript `choose file` on
  Mac, OpenFileDialog via PowerShell on Windows; Cancel offers a folder
  picker for batching). Drag-and-drop — and the Mac drag-into-Terminal
  trick — are no longer required skills.
- Windows FFmpeg bootstrap, matching the Mac one from v0.10: missing
  FFmpeg triggers a consent prompt, then a PowerShell download of the
  official gyan.dev release-essentials build (the Windows build linked
  from ffmpeg.org), extracted next to the script, execution-verified.
- Launchers renamed to `START-HERE-WINDOWS.bat` and
  `START-HERE-MAC.command` — the folder listing is now the instructions.
- First-open guide strip in the panel (① style → ② sliders → ③ save →
  ④ render), dismissible and remembered.
- A bold download link at the top of the README pointing at the
  latest-archive zip, so non-developers never have to find GitHub's
  Code button.

### Fixed
- The Mac launcher never actually received the v0.13 "open the panel"
  routing — a partial edit failure shipped undetected, so from v0.13 to
  v0.15 it still ran the one-shot preview while the changelog claimed
  otherwise. It now routes file → panel, folder → batch, as documented.

## [0.15.0] — 2026-06-12

### Added
- Six new styles, now built on the print-stock engine: `blockbuster`
  (neutral stock, Scope, 10-bit), `western` (warm stock, Scope, heavy),
  `horror` (cool stock, desaturated), `wedding` (warm stock, soft),
  `super8` (16mm, 4:3, leaks, weave, heavy grain), `newsreel` (B&W 16mm,
  4:3, weave). Eleven styles total.
- Visual preset gallery in the panel: the style dropdown is replaced by a
  strip of clickable cards, each showing YOUR clip rendered with that style
  (lazy-loaded 240px previews at the current scrub position). Click a card
  to apply it; touching any slider deselects the card so it's clear you've
  gone custom.
- Processed-file proof, three ways: (1) every output now carries container
  metadata — `comment: processed with filmify <version> | <settings>` —
  readable in VLC, MediaInfo, or ffprobe, so a file identifies itself
  forever; (2) the panel's render-done state shows a green confirmation
  banner with the output name and swaps the preview to a frame decoded
  from the finished file (not a simulation of it); (3) the existing
  `_film` suffix and HTML report remain.

## [0.14.0] — 2026-06-12

The prestige release: the three post-side gaps between filmify output and a
prestige finishing pass.

### Added
- Print-stock color engine (`--print-stock neutral|warm|cool`): a generated
  3D LUT from a subtractive density model — per-channel S-curves in
  log-exposure space plus interlayer crosstalk, the cross-channel bend that
  "graded through film" actually means. Mid-gray verified to stay mid
  (0.45 → 0.52), shadows gain print contrast (0.18 → 0.14), highlights stay
  protected (1.0 → 0.95), all channels monotonic. Replaces the built-in
  curve and split tone when active; your `--lut` still overrides it. Also
  selectable in the panel.
- Grain v2: synthesized grain now has PHYSICAL SCALE — generated at
  gauge-dependent reduced resolution and scaled up into soft clumps
  (16mm visibly coarse, 70mm near-invisible fine at the same strength),
  and weighted into the midtones through a luma mask the way negative
  stock wears its grain; highlights stay cleaner than shadows. Grain
  plates are unaffected.
- Batch shot matching (`--match`): a measurement pass samples every clip's
  average luma and chroma, computes the batch median, and applies a gentle,
  clamped exposure/white-balance nudge per clip before the look — the
  colorist's first hour, automated. Verified: a deliberately mismatched
  batch went from a luma spread of 45.7 to 5.6.

## [0.13.0] — 2026-06-12

The smoothness release.

### Added
- HDR auto-development: phones default to HLG/PQ recording, which a Rec.709
  pipeline renders washed and wrong. filmify now detects HDR transfer
  characteristics at probe time and tone-maps to Rec.709 automatically
  (zscale + hable), with a plain note in the output. `--no-tonemap` opts
  out; builds without zscale get a clear warning instead of silent bad
  color. This was the most likely silent first-contact failure for
  phone-footage users.
- Incremental batch: outputs that already exist are skipped with a per-file
  note and a summary line — re-running a shoot-day folder only renders new
  clips. `--force` redoes everything.
- Panel look management: a "Load a saved look" dropdown (scans the clip's
  folder for filmify look files) and a save-as name field, closing the loop
  between the panel and the project-asset system.

### Changed
- Drop launchers now open the control panel for a single clip (the panel
  was previously unreachable without a terminal); a dropped folder still
  runs the batch split-screen preview.
- Panel previews scale to proxy resolution at the FRONT of the filter
  chain, so every filter runs at proxy size: the full look stack on 4K
  source now previews in about a second. Full renders are untouched.
- ffmpeg console output reduced to errors + progress; the RGB blend stages
  were producing harmless but noisy swscaler conversion warnings on every
  render.

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
