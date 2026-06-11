# filmify

**The feel of film, without the film camera.**

filmify is a lightweight, single-file tool for indie filmmakers. Point it at
your digital footage and it applies the things that make film read as
*cinema*: protected highlights that roll off instead of clipping, 24 fps
motion with a 180° shutter feel, gentle softness, restrained color, halation
glow around bright lights, and organic grain. No NLE, no plugins, no
subscription — just Python and FFmpeg.

## Requirements

- Python 3.8+
- [FFmpeg](https://ffmpeg.org) (`ffmpeg` and `ffprobe`)

Works on Windows, macOS, and Linux. Installing FFmpeg:

```sh
# Windows
winget install ffmpeg
# ...or just drop ffmpeg.exe and ffprobe.exe next to filmify.py

# macOS
brew install ffmpeg

# Linux (Debian/Ubuntu)
sudo apt install ffmpeg
```

filmify finds ffmpeg on your PATH, next to the script, or in the current
folder — whichever comes first.

## Quick start

```sh
python filmify.py myfootage.mp4
```

That's it — you get `myfootage_film.mp4` with the standard look.

Shot on a phone at 60 fps? Conform it to 24 fps with proper motion blur:

```sh
python filmify.py myfootage.mp4 --conform
```

Got a film-stock LUT and a scanned grain plate? Use the real thing:

```sh
python filmify.py myfootage.mp4 --lut kodak_print.cube --grain-plate 35mm_grain.mp4
```

Dialing in a look? `--compare --preview` renders a fast 5-second
split-screen — original on the left, graded on the right:

```sh
python filmify.py myfootage.mp4 --look heavy --weave 1.5 --compare --preview
```

Happy with it? Run the whole shoot day in one go (outputs land in
`shoot_day1/filmified/`; reruns skip already-processed files):

```sh
python filmify.py shoot_day1/ --look heavy --weave 1.5 --conform
```

## Workflows

**1. Graded dailies** — shoot, batch-process, edit the graded clips.

```sh
# dial in the look on one clip, then save it as a project asset
python filmify.py clip01.mp4 --look heavy --weave 1.5 --compare --preview
python filmify.py clip01.mp4 --look heavy --weave 1.5 --conform --save-look myfilm.json

# run every shoot day through the same look, as edit-friendly ProRes
python filmify.py shoot_day1/ --look-file myfilm.json --codec prores
python filmify.py shoot_day2/ --look-file myfilm.json --codec prores
```

Mixed footage (a phone at 60 fps, a mirrorless at 30, drone clips in another
container) comes out as one uniform set: same 24 fps cadence, same codec,
same tonal character, same grain. That uniformity is most of what reads as
"one film" instead of "assembled clips." Use `--codec prores` (Final Cut,
Resolve, Premiere) or `--codec dnxhr` (Resolve, Premiere, Avid) here — they
scrub smoothly in editors and survive the editor's final export. The default
h264 is a *delivery* codec: editing it means your grain gets compressed
twice.

After every run, filmify writes **`filmify_report.html`** next to the
outputs and opens it in your browser: before/after thumbnails per clip,
✓/✗ status, fps in → out, sizes, and the exact settings used. It's a single
self-contained file — send it to a collaborator as "here's how day 2 came
out." `--no-report` to skip it.

**2. Finish pass** — edit the raw footage, export one master, filmify that.

```sh
python filmify.py master_export.mov --look-file myfilm.json
```

One generation of encoding instead of two, grain and weave run continuously
across cuts the way they would on a real print, and the look stays
adjustable until the very end. Best quality; the trade-off is editing
ungraded footage.

The look file is the cohesion mechanism in both: save it once, commit it to
your project folder, and every batch and the finish pass get identical
treatment. Relative LUT/grain-plate paths inside it resolve against the
look file's folder, so the project directory stays portable. Explicit flags
always override the file.

## Presets

| Preset     | Feel                                          |
|------------|-----------------------------------------------|
| `subtle`   | Barely-there. Modern digital cinema finish.    |
| `standard` | Clearly filmic without drawing attention.      |
| `heavy`    | Vintage stock — soft, grainy, faded blacks.    |

```sh
python filmify.py clip.mp4 --look heavy
```

Every component can be overridden individually: `--grain`, `--halation`,
`--soften`, `--saturation`, `--plate-opacity`, `--chroma-soften`, `--weave`,
`--bw`, `--preview`, `--no-curve`,
`--no-vignette`. Use `--dry-run` to print the FFmpeg command it builds
without running it.

## What the pipeline does (in order)

1. **24 fps / 180° shutter conform** (`--conform`) — blends adjacent frames
   from high-fps sources to synthesize natural motion blur, then drops to
   24 fps. This is the single biggest "video vs film" tell.
2. **Softening** — digital is too crisp; a gentle de-sharpen reads as glass.
3. **Gate weave** (`--weave`) — optional slow frame drift, like film moving
   through a projector gate. Layered sine motion, not random jitter.
4. **Filmic tone curve** — S-curve with a soft shoulder. Pure white lands
   below 100%, so highlights compress instead of blowing out. Blacks are
   lifted a hair, like a print.
5. **Film-stock LUT** (optional) — your `.cube` LUT supplies the color
   character; filmify steps out of the way and skips its own split tone.
6. **Color discipline** — mild desaturation, warm highlights, faintly cool
   shadows. Restrained on purpose; skin stays natural.
7. **Halation** — bright areas glow softly red-orange instead of clipping,
   the way light bounces inside a real film base.
8. **Grain** — a real scanned grain plate if you have one (looped and
   overlay-blended), otherwise synthesized temporal grain weighted to luma
   so it reads as silver grain, not sensor noise.
9. **Vignette** — slight corner falloff, like a lens.

Output is encoded with `x264 -tune grain` so the encoder doesn't smooth the
texture back out.

## What filmify can't do

It finishes the look — it can't recover what the camera threw away. The
biggest wins still happen on set:

- **Expose to protect highlights** (or shoot a log/flat profile and grade).
  Film forgives overexposure; digital does not. Once whites clip, no curve
  brings them back.
- **Light intentionally** — bad lighting reads as amateur faster than any
  camera choice, and over-lighting is the classic tell. Contrasty, stylish
  lighting usually means *fewer* fixtures: the sun, practicals already in
  the location, a lamp in frame. Free.
- **Shoot 24 fps with a 180° shutter in camera** when your rig allows it.
- **Adapt vintage glass.** A cheap adapted lens from the '70s gives you
  optical softness and character no filter or post process matches.
- **Spend on sound.** Audiences forgive soft images; they do not forgive
  bad audio. If you spend money anywhere, spend it there.
- **Shoot fewer, more deliberate takes.** Film's look came partly from its
  cost forcing intention. The discipline is free.
- **No colorist? Go B&W** (`--bw`). It reads as deliberate, not unfinished.

## Versioning

Releases follow SemVer and are tagged in git. See [CHANGELOG.md](CHANGELOG.md).

## License

Apache-2.0
