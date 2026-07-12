# Changelog

All notable changes to filmify are documented here.
Versioning follows [SemVer](https://semver.org).

## [0.44.0] — 2026-07-11

### Changed
- **The photochemical film chain is now filmify's default engine — in the
  CLI and in the panel.** `python filmify.py clip.mp4` develops through the
  virtual negative → printer lights → print stock chain, with silver-halide
  density grain and linear-light halation. This lands after the chain was
  validated on a real machine with real footage.
  - **Engine resolution instead of a blind default.** An explicit
    `--pipeline` always wins; a `--style` selects its own engine (every
    style now declares one); a look file declares its engine (schema 2);
    classic-only options (`--bw`, `--leak`, `--flare`, `--age`, `--look`,
    `--saturation`, a legacy `--print-stock`, …) auto-select the classic
    engine **with a printed note, never silently**; otherwise:
    photochemical. HDR sources auto-fall to the classic tonemap path with a
    note (the film chain doesn't take HDR yet) unless the film engine was
    explicitly forced, which stays a clear error.
  - **The panel drives both engines.** A new Engine selector defaults to
    film (photochemical): negative stock, print profile, printer lights
    (R,G,B), and the opt-in lens vignette are panel controls now; classic-
    only controls hide in film mode and return in classic mode. Previews,
    full renders, and folder batches all run through the selected engine,
    and a bad film setting reports in the panel instead of killing the
    server.
  - **Film styles lead the gallery**: `film` (the chain at its defaults),
    `film-16mm` (smaller gauge, more grain), `film-scope` (2.39:1 with a
    touch of lens softness, 10-bit). Classic styles remain and still work —
    clicking one simply selects the classic engine, and `--style nineties`
    et al. keep working from the CLI with an auto-route note.
  - **Saved looks are schema 2**: a look file now records which engine it
    belongs to and round-trips it. Schema-1 files (no version field) load
    exactly as before — classic — even if a stray `pipeline` key appears
    in one. `--save-look` works in photochemical mode now.
  - Conflicts are errors, not surprises: `--style noir --pipeline
    photochemical` refuses plainly rather than half-applying a classic
    recipe to the film chain.
- Panel defaults follow the film chain's own defaults (grain 7,
  halation 0.33).

## [0.43.0] — 2026-07-11

### Changed
- **The panel is monochrome — black, white, and grays only.** Grading-suite
  discipline: any hue in the chrome biases the eye's read of the footage,
  and the footage is the whole point. The orange accents and the
  green/red status colors are gone; selection reads through a white border
  and weight instead of color. The render report follows the same rule.

### Fixed
- **Dropping a video onto the panel now actually loads it.** A browser
  never reveals a dropped file's disk path (security), so previously a drop
  just bounced to the file picker — which read as broken. Now the page
  streams the dropped file's bytes to the local server, which writes a
  working copy and loads that, with live copy progress. (The copy is the
  unavoidable cost of the browser sandbox; clicking to browse still loads
  the original in place with no copy.) An empty drop still falls back to
  the picker.
- **Changing parameters mid-export no longer disturbs the export.** Every
  slider move fires a live-preview render; during an export that meant a
  second ffmpeg fighting the running one for the CPU/GPU encoder. Previews
  now pause while a render or batch is in flight (the panel says so, and
  notes that your changes don't affect the running export) and refresh the
  moment it finishes. The server also refuses preview requests during an
  export, so a stale page can't disturb one either.

### Verified
- Preset tiles were already stateless — clicking a style applies its full
  defaults (aspect ratio included), your tweaks never modify the preset,
  and re-clicking the tile restores everything. Now pinned by browser
  tests so it stays that way: 19 Playwright checks green, including drop
  upload, the export guard, preset restore, and a no-hue check on the
  chrome.

## [0.42.3] — 2026-07-11

### Fixed
- **Rotated video (portrait phone clips) renders instead of failing.** The
  first bug found by real-machine testing: portrait phone footage is coded
  landscape plus a display-rotation entry, ffprobe reports the coded size,
  but ffmpeg autorotates on decode — so every plate filmify generated
  (grain, halation) was sized to the wrong orientation and the graph died
  with a blend size mismatch ("First input link top parameters do not
  match…", exit code 4294967274 on Windows) in every pipeline. The probe
  now reads the rotation (displaymatrix side data or the legacy rotate
  tag) and reports the decoded orientation, so all graphs build at the
  size the frames actually arrive in. Output is upright, rotation baked
  into pixels. Regression-tested in both pipelines, and verified against
  both ffmpeg 6.1 and current ffmpeg master.

## [0.42.2] — 2026-07-11

### Fixed
- **Failed renders now tell you why.** Previously a render failure said
  "ffmpeg exited with code N (see console output above)" while the panel
  path piped ffmpeg's stderr to nowhere — there was nothing above to see.
  First real-machine testing hit exactly this: five different renders, one
  useless message. Now filmify streams ffmpeg's stderr through live (the
  progress line still updates) while keeping the tail, and on failure
  prints which ffmpeg binary ran, the last lines it said, and — if it said
  nothing at all — the most likely cause (a broken ffmpeg.exe or the
  Windows Store alias stub shadowing a real one on PATH). The panel's
  error message now carries the real reason instead of pointing at a
  console that may not exist.

## [0.42.1] — 2026-07-11

### Changed
- **The photochemical vignette is opt-in, not forced.** 0.42.0 applied the
  projection-lens vignette by default (inheriting the legacy pipeline's
  semantics); that was the wrong call — the develop chain is film physics,
  and corner falloff is a *lens* artifact, not something the film process
  produces. Default photochemical output leaves corners alone again
  (identical framing to 0.41.0). Lens character is now an explicit choice:
  a new `--vignette 0-1` strength flag enables it, mapping to a
  gentle-to-strong lens angle. In the legacy pipeline the same flag
  overrides the preset's vignette (`--vignette 0` disables, same as
  `--no-vignette`; unset keeps preset behaviour, so nothing changes for
  existing looks).

## [0.42.0] — 2026-07-11

### Changed
- **The photochemical chain is now filmify's main path — camera → develop →
  projection — and the surrounding stages follow around it at their
  physical positions.** The develop core (virtual negative, linear-light
  halation, density-space silver-halide grain, printer lights, print stock)
  is unchanged; what's new is that the rest of filmify's character now runs
  *around* it instead of being blocked:
  - **Camera/lens stages, before the negative sees light:** `--ratio`
    framing and `--conform` (already wired) are joined by `--soften` — lens
    diffusion happens through glass, so it precedes exposure.
  - **Projection/presentation stages, on the finished print:** `--weave`
    (gate transport), `--flicker` (lamp/print breathing), and the
    projection-lens **vignette — now on by default** in photochemical mode
    like everywhere else in filmify (`--no-vignette` to disable). Physical
    order: transport → lamp → lens. Debug stages (`--debug-stage`) skip
    projection — a negative on a light table doesn't weave.
  - Legacy knobs that *approximate* what the develop core now does
    physically (tone curve, colour discipline, overlay grain plates) are
    replaced, not ported; the remaining not-yet-wired knobs (leak, flare,
    age, presence, corner-soften, B&W) still announce themselves plainly
    and will land at their physical stages (leak/flare belong in exposure,
    age at presentation, B&W as a mono stock profile).
  - `--dump-pipeline` shows the camera and projection stages around the
    develop chain.
- Note for A/B against 0.41.0 renders: photochemical output now has the
  default vignette — corners are slightly darker. `--no-vignette` restores
  the 0.41.0 framing exactly.

### Why
- One sentence: what 0.36–0.41 built isn't a mode, it's the develop stage —
  the physics core — and the rest of filmify (camera character in front,
  projector character behind) composes around it. This release makes that
  architecture real; wiring the preset gallery and panel to it (and
  eventually flipping the default pipeline) follows once the chain is
  validated on real machines.

## [0.41.0] — 2026-07-11

### Changed
- **Photochemical colour holds saturation.** Tested on real footage, the
  print chain was over-desaturating — two crosstalk matrices in series (the
  negative's `sensitivity_matrix` and the print's `printer_matrix`) multiply,
  so their combined channel-bleed crushed saturated colours (a warm
  candlelit frame lost ~46% of its saturation; skin and mildly-coloured
  scenes were closer to right). Both matrices are tightened toward the
  identity — less inter-layer crosstalk, which is also truer to how good
  colour negative behaves (the orange mask and inter-image effects preserve
  colour separation rather than muddying it). Result on the test stills:
  whole-frame saturation retention rose from ~83% to ~92% on a daylight
  frame and from ~54% to ~60% on a heavily-saturated candlelit frame — the
  remaining rolloff on near-clipping colours is the print shoulder behaving
  as film should. Neutral gray still prints perfectly neutral (the
  per-channel printer-light calibration re-balances around the new
  matrices), so there's no colour cast.

## [0.40.1] — 2026-07-11

### Fixed
- **Grain no longer produces "rainbow" colour speckle.** The v0.40.0
  decorrelated-colour grain, tested on real footage, put independent R/G/B
  noise on different pixels — which reads as saturated colour confetti
  (digital-compression sparkle), not silver halide. Corrected to how film
  actually behaves: grain is dominated by *luminance*, with only a faint
  chroma component. The base grain is now one luminance field replicated
  across all three channels (neutral by construction — zero colour speckle),
  with a separate, coarse, low-amplitude chroma field added at a small
  weight for subtle dye-cloud variation. Multi-scale crystals and
  shadow-weighting are unchanged. New profile knobs `chroma_weight` (how
  much colour grain) and `grain_saturation` (residual-chroma clamp) tune it;
  defaults are deliberately conservative toward neutral for clean skin.

## [0.40.0] — 2026-07-11

### Changed
- **Silver-halide grain rebuild — the density-space grain is now modeled on
  real film physics, not a single noise field.** Grain placement was already
  correct (a perturbation of the negative density, printed through the
  stock, not an overlay); this rebuilds its *character* so it reads as
  emulsion rather than digital noise. Four physical properties, each
  measured in the test suite:
  - **Multi-scale crystals.** Real grain has a crystal size distribution —
    many fine grains plus sparser large ones — so the field is now a *sum*
    of noise scales (a fine high-frequency layer + a coarse low-frequency
    layer), not one blurred noise plate. A single scale is the giveaway of
    synthetic grain; the coarse layer survives 4x downsampling where
    single-frequency noise would wash out.
  - **Shadow-weighted, not mid-peaked.** Grain is strongest where the
    negative is thin (low density = scene shadow) and quiets in the dense
    highlights — relative density fluctuation is largest at low density, and
    the faster/larger crystals live in the shadow-sensitive toe. The old
    curve peaked in the mids; the new one rises toward the toe, matching how
    real footage looks (grainiest in shadows, cleanest in highlights).
  - **Decorrelated colour.** Colour negative has three independent R/G/B
    emulsion layers, each with its own grain, so chroma grain is not tinted
    luma. Grain is now built as three separate noise fields (per-layer
    seeds) merged per-channel, with only a small shared component modeling
    the common base/scatter. Blue (fastest layer, largest crystals) is the
    grainiest channel, red the finest.
  - **Amplitude in granularity units.** Per-layer strength derives from the
    profile's RMS granularity (the standard diffuse-RMS-density measure),
    so the 0-20 intensity and the gauge scaling track a real density
    fluctuation instead of an arbitrary slider.
  - Profile `grain` block reworked accordingly (`rms_granularity`,
    `crystal_scales`, `density_amplitude_curve`, `layer_correlation`),
    replacing the old `fine_scale`/`cloud_scale`/`channel_strength`/
    mid-peaked `density_curve`.

### Notes
- The grain graph is heavier: photochemical render time with grain roughly
  doubles (still an unattended-batch tool — "dial in, process, walk away").
  A future `--grain-quality` lever can trade fidelity for speed if needed.
- Legacy pipeline and halation are unchanged. All photochemical invariants
  still hold (neutral base, printer-light isolation, exact-shadow halation);
  the grain neutrality/isolation tests render grain-off, and grain has its
  own tests for the four properties above.

## [0.39.0] — 2026-07-11

### Added
- **Halation ships — composited in linear light (Milestone 2 complete).**
  With `--pipeline photochemical`, a bright highlight now blooms into its
  surroundings the way film does: light reflects off the film base and
  re-exposes the emulsion nearby. It runs at its physical stage — an
  exposure spread *before* the negative curve — so the negative then
  compresses and tints the halo automatically: a blown highlight blooms
  hard, a mid highlight barely. That asymmetry isn't coded; it falls out
  of the characteristic curve. The halo carries the stock's (red-biased)
  halation color via the profile matrix. `--halation` scales the profiled
  strength (1 = as profiled, 0 off); on by default.
- **Decoupled-halo architecture.** Halation and the negative's shadow
  detail want opposite encodings — the halo must add in *linear* light,
  the negative curve must see *log* to resolve shadows, and one uniform
  3D LUT can't serve both (a linear grid collapses mid-gray-and-below into
  a handful of nodes). filmify now develops the base image through the
  exact fused negative LUT (shadows perfect) and builds the halo as a
  separate linear-light layer — threshold, blur, stock-matrix color — that
  is merged back *only where it's nonzero*, via a halo-presence mask. The
  linear encoding therefore never touches a clean-shadow pixel, so the
  bloom is physically correct and shadows stay exact. Verified: the bloom
  bleeds past a highlight edge while far clean shadow is byte-for-byte the
  halation-off development.
- New LUT generators (`lut_generation.py`): a linear-mode exposure LUT
  (`linear=True`, with an above-white headroom ceiling so the halo has
  room to add) and a stock-independent `log_shaper_lut` that re-encodes the
  linear halo frame to scene-log for the response LUT. Both cached and
  deterministic like the rest.
- `--dump-pipeline` now shows the linear-light halation stages; the WIP
  `--experimental-halation` flag is gone (halation is a first-class stage).

### Notes
- Legacy pipeline untouched; halation-off photochemical output is
  unchanged from 0.38.0. All existing tests green; the halation bloom test
  that was `xfail` in 0.38.0 now passes.

## [0.38.0] — 2026-07-11

### Added
- **Photochemical grain lives in the negative (Milestone 2, part 1).** With
  `--pipeline photochemical`, grain is now a density perturbation on the
  developed virtual negative — injected between the negative and print LUTs,
  in the density domain — not an overlay on the finished image. It is
  masked by a per-stock density curve (a small generated 3D LUT), so the
  mids wear grain while D-min and D-max stay quieter, the way film does;
  the print stock then sees the grained negative and carries it through.
  Luma noise refreshes every frame, chroma noise is coarser and temporally
  averaged so color grain reads as dye clouds rather than fizz.
  `--grain 0-20` tunes it (0 disables, ~7 default); `--gauge` scales both
  amplitude and clump size (16mm coarser, 70mm finer). Verified temporal,
  mean-stable (grain doesn't shift exposure), and density-masked.
- **Split-negative scaffolding for halation.** The negative LUT can now
  split into an exposure LUT (source → scene-log exposure) and a response
  LUT (scene-log exposure → density) around an exposure-space frame, so a
  spatial effect like halation can run at its physical stage — before the
  characteristic curve. Composition is byte-exact: response∘exposure
  reproduces the fused negative LUT, so the split never disturbs the base
  image. Groundwork for the next release.

### Known limitations
- **Halation is experimental and off by default.** It belongs in exposure
  space before the negative curve, and the split-negative path above is
  ready for it, but a faithful halo has to be composited in *linear light*
  (adding light in a log domain under-blooms) — that needs a linear↔log
  shaper in the graph, which lands in a later milestone. `--experimental-
  halation` enables the current work-in-progress path (safe — it uses
  additive compositing, which ffmpeg computes correctly on planar formats,
  unlike `blend=screen`, which it does not — so the base image and far
  pixels are untouched; only the bloom itself is weak). Without that flag,
  `--halation` is politely ignored in photochemical mode with a note.

### Notes
- Found and worked around an ffmpeg bug: `blend=all_mode=screen` on 16-bit
  integer planar (`gbrp16le`) miscomputes badly (screen of gray over black
  returns near-white). The photochemical chain uses `addition`, `grainmerge`
  and `maskedmerge`, all of which are correct on that format.
- Legacy pipeline untouched; all existing tests green.

## [0.37.0] — 2026-07-10

### Added
- **The photochemical pipeline renders (Milestone 1).** `--pipeline
  photochemical` now processes footage through the simulated film chain:
  source → scene-linear light → virtual camera negative (per-layer
  characteristic curves, stock sensitivity matrix) → the normalized
  negative-density intermediate → printer lights → virtual print stock →
  projection → screen. Two generated, cached 3D LUTs carry the chemistry
  (`lut_generation.py`, new); the frame between them is literally the
  negative — which is where grain gets injected next milestone.
  - **Printer timing, like a real lab.** At LUT generation the printer is
    calibrated per channel (bisection against the print curve) so an
    18%-gray scene prints to a neutral mid on screen — the negative's
    per-channel base densities are neutralized by the printer, not hidden
    in the curves. `--printer-lights R,G,B` offsets around that calibrated
    25,25,25 neutral in profile-defined light points; more light in a
    channel prints denser, i.e. LESS of that color, exactly like a timer.
  - `--negative-stock` selects the virtual negative (`modern_500t` for
    now); `--print-stock` selects the virtual print profile
    (`neutral_release`) when the photochemical pipeline is active.
  - **Log develops into the negative, not into a display image.**
    `--input-log slog3|vlog|cineon` in photochemical mode decodes straight
    to scene-linear exposure inside the negative LUT — the whole point of
    the architecture.
  - **Stage inspection:** `--debug-stage negative-density` renders the
    normalized density record; `--debug-stage negative-preview` shows the
    negative as transmitted light. `--dump-luts` copies the generated
    `.cube` files next to you; `--dump-pipeline` prints the ordered stage
    list and which LUT carries each transform.
  - LUTs cache under the platform cache directory, keyed by a content hash
    of everything that matters (profiles, lights, transfer, size,
    generator version) and nothing that doesn't; regeneration is
    byte-identical. 65³ generation is well under a second.
  - Guard rails: legacy-only knobs (grain, halation, weave, styles, look
    files…) are loudly listed as ignored rather than silently dropped —
    each returns at its physical stage in later milestones. Schema-1 look
    files, `--save-look`, `--compare`, the panel, and HDR sources are
    blocked in photochemical mode with pointers to what to use instead.
    Flag validation runs before any file checks, so a typo'd stock name
    says so instead of hiding behind "file not found".
  - Tests: generated-LUT validity and cache determinism, a full-chain
    ffmpeg ramp render asserting monotone, neutral output with mid-gray
    anchored on screen, printer-light channel isolation, and a
    density-is-not-`1-RGB` check (TDD acceptance 27.1 / 27.3 as code).
  - The legacy pipeline is untouched: identical filtergraphs, identical
    output, all existing tests green.

## [0.36.0] — 2026-07-10

### Added
- **The photochemical pipeline's foundation (Milestone 0).** filmify is
  headed toward processing footage through a simulated photochemical chain —
  virtual negative, laboratory development, printer lights, print stock —
  instead of layering effects over a finished image. This release lays the
  ground without changing a single rendered pixel:
  - `--pipeline legacy|photochemical`: the pipeline is now an explicit,
    reported choice. `legacy` (the default) is the current chain, unchanged.
    Selecting `photochemical` exits with a clear not-ready message — it will
    become renderable in coming releases, stage by stage.
  - `photochemical.py`: density mathematics (optical density ↔
    transmittance), normalized scene-log exposure encoding, monotone-cubic
    characteristic-curve interpolation with hard no-overshoot guarantees,
    a stock-profile JSON schema with a validation CLI
    (`python photochemical.py --validate my_stock.json`), deterministic
    content fingerprints (the future LUT-cache key), and two generic
    built-in placeholder profiles (`modern_500t` negative,
    `neutral_release` print — descriptive names, deliberately not claims
    about any commercial stock). Stdlib only, like everything filmify ships.
  - `test_photochemical.py`: unit tests locking the invariants — density
    round trips across 0–5D, curve monotonicity/bounds/finiteness, schema
    validation catches broken profiles, fingerprints are deterministic and
    order-independent, and schema-version-1 look files keep selecting the
    legacy pipeline (`pipeline` is structurally barred from `LOOK_KEYS`
    until versioned look schema v2 lands). Wired into CI on all three OSes.
  - The render report now identifies the pipeline (shown only once a
    non-legacy pipeline is in play, so today's reports are unchanged).
  - `photochemical.py` ships inside both user packages.

## [0.35.3] — 2026-07-02

### Fixed
- **Aged Print no longer draws a fixed line down the centre of the frame.** The
  aged-print scratch was authored to wander within a +/-120px band centred on
  the middle and gated to a brief flash every ~9 s; but the wander term is 0 at
  t=0, so the panel's preview frame froze the scratch dead-centre with its
  visibility gate open -- a 2px line straight down the middle that read as the
  A/B-split divider rather than film damage. The scratch now wanders in the
  left-of-centre region (never crossing the middle) and is phased so the t=0
  preview frame is clean; it flashes briefly, off-centre, during playback as
  intended. Also removed the old wide-canvas crop, whose x expression could
  drift out of bounds.

## [0.35.2] — 2026-07-02

### Fixed
- **Windows CI: the shell-launcher lint now uses a bash that can actually
  lint, instead of failing on the WSL stub.** The Windows runner has Git for
  Windows installed, but `shutil.which("bash")` resolves to
  `C:\Windows\System32\bash.exe` first -- the WSL launcher, which with no
  distro exits nonzero with its message on stdout and empty stderr (the exact
  failure in the logs) regardless of input. That's why fixing the *input*
  (0.34.1 CRLF-normalize, 0.34.2 feed-bytes) never helped. The test now probes
  candidate bashes and falls back to Git-Bash (located from `git`), giving
  Windows real shell-syntax coverage; it skips only if no bash on the runner
  can lint at all. Supersedes 0.35.1's probe-and-skip, which would have gone
  green by skipping rather than actually linting.
- **Launchers are read as bytes, not cp1252 text.** All three mac launchers
  contain UTF-8 (em dash, ellipsis, arrow); `f.read_text()` decodes them under
  the process locale, which is cp1252 on Windows and would mangle them before
  linting. Reading raw bytes and normalizing line endings on bytes feeds
  Git-Bash exactly what's on disk. The interpreter-guard test now reads UTF-8
  explicitly for the same reason. All bash calls are timeout-guarded.

## [0.35.1] — 2026-07-02

### Fixed
- **Windows CI: shell-launcher lint no longer fails on a bash that can't
  lint.** The 0.34.1 (CRLF normalize) and 0.34.2 (feed bytes) fixes both
  targeted the *input* to `bash -n`, but the input was never the problem: the
  original failure had empty stderr, which CRLF never produces. On the runner,
  `shutil.which("bash")` resolves to a bash that exits nonzero with its message
  on stdout (a WSL stub with no distro, or a shim) regardless of input. The
  test now sanity-probes bash on a trivial script first and skips — with a
  printed diagnostic naming the resolved bash and its version — when it can't
  lint. Real syntax-error coverage remains on the macOS and Linux jobs, and
  genuine errors still fail there. Calls are timeout-guarded so a stub that
  hangs can't stall CI.

## [0.35.0] — 2026-07-02

### Changed
- **Panel controls now lead with the basics.** The two most-used fine-tune
  sliders after picking a style — plus Look, Gauge, Aspect ratio, Grain,
  Halation, Soften and Saturation — stay visible, while the eight esoteric
  texture/optics sliders (chroma soften, gate weave, light leak, anamorphic
  flare, presence, density flicker, corner softness, aged print) and the
  color/source controls (log develop, print stock, LUT, grain plate) collapse
  into two "advanced" disclosures. A first-timer sees a short, legible panel;
  the full control surface is one click away and nothing was removed. (The
  style gallery and per-control "?" help were already there — this just stops
  the sliders from burying them.)

### Fixed
- **`super8` and `newsreel` styles now apply their 1.33 crop in the panel.**
  Both set a 1.33 (4:3) aspect ratio, but the panel's ratio dropdown had no
  1.33 option, so selecting either style silently left the frame uncropped.
  Added the 1.33 option; the styles now round-trip through the UI.
- **The CLI no longer crashes on its own status output under a legacy Windows
  code page.** `main()` prints a few non-ASCII glyphs (the done check, a batch
  arrow, an ellipsis); on cp1252 those raised `UnicodeEncodeError` the moment
  stdout was redirected or piped, killing the render at the summary line.
  stdout/stderr are now reconfigured to UTF-8 with `errors="replace"`, so
  output degrades gracefully instead of taking the render down. Same class of
  bug fixed in the test suite in 0.34.2, now closed in the shipping tool.

## [0.34.2] — 2026-07-02

### Fixed
- **Windows CI died the instant the suite went green.** The smoke summary
  printed `all green ✓`, and on a cp1252 console (which is what a redirected
  Windows runner gets) the `✓` can't be encoded, so `print()` raised
  `UnicodeEncodeError` *after* all 36 checks had already passed. The victory
  line is now pure ASCII, and `test_filmify.py` reconfigures stdout to UTF-8
  (`errors="replace"`) at import so no stray glyph can ever sink a green run.
- **Windows CI failed `bash -n` on the shell launchers — the CRLF fix was
  being undone on the way to bash.** `test_shell_launchers_parse` normalizes
  each launcher to LF, then fed it to `bash -n` on stdin with `text=True`. But
  `text=True` wraps stdin in a `TextIOWrapper` whose default newline handling
  translates every `\n` back to `os.linesep` *on write* — i.e. it re-inserted
  `\r\n` on Windows, so Git-Bash choked on the carriage returns. The script is
  now fed as raw UTF-8 **bytes**, byte-identical to the LF stream macOS already
  parses clean, so no re-translation can happen.
- **macOS CI failed `normalize: non-709 primaries engages`.** The check
  asserted a zscale-specific output substring, but Homebrew's ffmpeg is built
  without libzimg, so it has no `zscale` filter. Remapping primaries genuinely
  requires zimg, so on that build `source_normalize()` correctly leaves a
  limited-range clip alone rather than faking a conversion it can't do — which
  is exactly what the check now asserts, keyed on `has_filter("zscale")`, so it
  verifies the real per-build contract on both zimg and non-zimg ffmpeg.

## [0.34.1] — 2026-07-01

### Fixed
- **Every real render crashed at the report step.** Two CSS rules inside the
  `write_report()` f-string (`#helppop{…}` and `.hq{…}`) used single braces
  where every neighbouring rule uses doubled `{{ }}`, so Python read them as
  replacement fields and `main()` raised `NameError: name 'display' is not
  defined` right after "done." The smoke suite missed it because it calls
  `render()` directly and never hits `main()`/`write_report()`. Braces doubled;
  a new smoke check now exercises `write_report()` on a real result.
- **CI hung for 10 minutes on macOS and Linux.** The panel banner
  (`filmify panel: <url>`) was printed without `flush`, so on a non-TTY runner
  it sat block-buffered and the test's readiness `readline()` blocked forever
  waiting for a line that never arrived (the 20s guard couldn't fire from
  inside a blocking read). The banner now flushes, the panel child launches
  unbuffered (`-u`), and the readiness wait reads on a background thread so the
  deadline is always enforced. Windows was unaffected and already passed.
- **Windows CI failed `bash -n` on the shell launchers.** A CRLF checkout made
  Git-Bash choke on stray carriage returns. `.gitattributes` now pins `*.sh` to
  LF (it already pinned `*.command`), and `test_shell_launchers_parse`
  normalizes line endings before parsing so a CRLF checkout can't cause a false
  failure while still catching genuine syntax errors.
- **Scratch launchers were committed by accident.** `filmify-drop.bat`
  (non-ASCII em-dash → failed the .bat ASCII check) and `filmify-drop.command`
  were local scratch swept in by `git add -A`. They're now git-ignored.
- **Panel previews are bounded.** `preview_jpeg()`'s single-frame ffmpeg call
  gained a 90-second timeout so a stalled preview surfaces an error instead of
  hanging the panel thread.

## [0.34.0] — 2026-07-01

### Changed
- **Edge-aware halation.** Real halation is a red-orange halo scattering back off
  the film base *around* bright objects — strongest just outside a highlight's
  edge, not a flat bloom over the whole bright area. The highlight is now spread,
  most of the sharp core subtracted back out, and the leftover fringe tinted and
  screened — so speculars get a glowing edge instead of a washed bright patch. A
  little core glow is kept so large highlights still bloom.
- **Luma / chroma grain separation.** Silver (luma) grain and dye-cloud (chroma)
  grain are physically different layers, and now render that way: luma grain
  stays fine and dances every frame; chroma grain is coarser (a chroma-only blur
  on the grain plate) and temporally averaged, so it reads as soft colour clouds
  instead of per-pixel chroma fizz.
- **Grain continuity.** The chroma grain's temporal averaging locks frame-to-frame
  continuity, which is what stops grain from boiling. (Grain was already
  byte-deterministic across renders, so matched shots and re-renders stay
  consistent.)

### Added
- **Compression-aware defaults.** `probe()` now reads bitrate and derives
  bits-per-pixel. On a heavily-compressed source (low bpp — a streaming rip, an
  old phone clip) filmify eases preset grain back and leans a little harder on
  chroma softening, so it doesn't amplify the existing macroblocking or waste
  grain that a re-encode would destroy. Only touches preset grain (an explicit
  `--grain` is respected); disable with `--no-compression-adapt`.

## [0.33.0] — 2026-07-01

### Added
- **`sweep.py --validate` — reference validation for the default look.** Renders
  a controlled synthetic set (neutral gray card, three skin tones, a highlight
  patch, a shadow patch, and a night-practical frame), measures the properties
  that actually matter, and leaves two artifacts behind:
  - a **before/after contact sheet** (`references/filmify_references_<ver>.png`)
    so you can *see* the whole set at a glance, and
  - a **version-tagged stats JSON** (`references/filmify_reference_stats_<ver>.json`)
    you can diff between releases to catch drift.
  Pass a real clip to fold it into both. Metrics: neutral cast, skin-hue drift,
  saturation kept, highlight/shadow clipping, and luma drift — each gated only
  on the references where it's meaningful (a skin swatch's hue, a gray card's
  cast), so a PASS/WARN table you can trust.
- Clipping is measured in tv-range (pinned near 235 / 16, not 255 / 0) on a
  centre crop, so the intentional vignette's corner falloff is never mistaken
  for crushed shadow or blown highlight detail.
- Cross-platform contact-sheet labels (Win/mac/Linux font discovery, graceful
  fallback to an unlabelled sheet if no system font is found).

### Housekeeping
- `references/` is git-ignored and cleaned by `build-packages.py --clean`.
- Smoke suite gained a cheap structural guard for the validation scaffold.

## [0.32.0] — 2026-07-01

### Added
- **Colour management — a look is only as good as the input transform.**
  `probe()` now reads `pix_fmt`, `color_range`, `color_space`, and
  `color_primaries` alongside the transfer, so filmify knows what it's actually
  being handed.
- **Conditional source normalize (before the look).** Full-range (PC/JPEG)
  levels and non-709 primaries (BT.2020 SDR, SD 601/170M) are corrected to
  Rec.709 limited *before* the curve/halation/grain run, so the look always
  lands on a standard image instead of clipped or mis-primaried footage. This
  is strictly conditional: a normal Rec.709 SDR clip has **nothing** inserted —
  it passes through pixel-for-pixel unchanged. Uses `zscale` when present.
- **`--input-range auto|full|limited`.** Override level-range detection for
  files that are mistagged or carry no range tag.
- **Output colour metadata.** Renders are now tagged Rec.709 / bt709 / limited
  — exactly what the pipeline produces — so players and editors interpret them
  correctly instead of guessing. Previously the file shipped colour-unspecified.

### Changed
- **HDR tone-map now interprets the source explicitly.** The HLG/PQ → Rec.709
  tone-map declares the source transfer, primaries, matrix, and range to
  `zscale` (from the probe) rather than relying on inference from container tags
  that phones frequently omit — so HDR conversion is correct, not a guess.

## [0.31.0] — 2026-07-01

### Added
- **A new `clean` look — now the default.** The gentlest rung on the intensity
  ladder and the new starting point for `python filmify.py clip.mp4` and the
  panel: fine grain (3), minimal softness, low halation on only the brightest
  speculars, a whisper of warmth, a near-linear curve with a soft highlight
  shoulder, and skin protected in the colour stage. The design goal is "nobody
  notices the effect, but everyone feels the footage is less digital" — filmify
  as finishing polish, not a filter. Heavy grain, leaks, scratches, weave, and
  flare stay exactly where they were: opt-in styles.
- **`sweep.py --check`** — a "too much film effect" guard. Renders a clip (or
  synthetic neutral-gray + colour-bars references if you don't pass one) through
  the clean default and reports whether it stayed gentle: luma drift, global
  colour wash, and how much of the original saturation survived, each as
  PASS/WARN against premium-default thresholds. Non-zero exit if anything warns.

### Changed
- **The intensity ladder is now `clean → subtle → standard → heavy`.** `clean`
  is the default; the other three are explicit opt-ins for more film.
- **`standard` dialled back a notch.** Since it's no longer the silent default
  but a deliberate "I want it clearly filmic" choice, it's slightly gentler:
  soften 0.55 → 0.50, halation 0.33 → 0.28, grain 7 → 6, chroma-soften 1.2 →
  1.0, presence 0.30 → 0.26, plus a marginally softer tone curve. `subtle` and
  `heavy` are unchanged. Note styles built on `standard` (`anamorphic`,
  `blockbuster`) inherit the gentler numbers.
- **Panel and CLI defaults kept in lockstep.** The panel's initial slider
  positions (which are set from HTML, not the JS defaults) and the JS reset
  baseline were both synced to `clean`, so the UI and `--look` no longer drift.

### Tests
- Smoke test now builds a filtergraph for every LOOK (not just every style),
  so the `clean` default is covered by CI.

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
