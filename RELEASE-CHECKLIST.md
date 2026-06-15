# Pre-release checklist

The smoke test (`test_filmify.py`, run automatically by CI on every push)
covers the machine-checkable things: version consistency, every style builds,
8-bit and 10-bit render without a color cast, the panel serves, and the
packages assemble cleanly on Linux/macOS/Windows.

These remaining items **cannot** be automated — they need a real machine, a
display, and in some cases a GPU. Run through them before publishing a release.

## Mac
- [ ] `make-mac-app.command` builds `filmify.app` with the correct icon
- [ ] Double-clicking the app opens the panel (after the one-time right-click → Open)
- [ ] "Move to Applications" works and the app still launches from there
- [ ] File picker ("Choose a video…") appears **in front** of the browser
- [ ] "Save to…" folder picker appears in front
- [ ] "Show in folder" reveals the finished file in Finder
- [ ] If on Apple Silicon: FFmpeg auto-download fetches the arm64 build

## Windows
- [ ] `Make filmify app.bat` creates the Desktop + Start-menu shortcut with icon
- [ ] Shortcut launches the panel with **no console window** flashing
- [ ] File picker appears **in front** of the browser (not hidden behind)
- [ ] "Save to…" folder picker appears in front
- [ ] "Show in folder" opens Explorer with the file selected
- [ ] FFmpeg auto-download works on a machine without FFmpeg installed
- [ ] If a GPU is present: a full render prints "encode: hardware (...)" and is fast

## Both
- [ ] Drag-and-drop a clip onto the import zone loads it
- [ ] Render shows a moving progress bar, not a frozen "rendering…"
- [ ] "Process whole folder…" batches a folder into filmify_<timestamp>/
- [ ] Batch progress shows "clip N of M"
- [ ] A processed file's metadata shows the correct version
      (`ffprobe -show_entries format_tags=comment <file>`)
- [ ] The two README download links resolve to the current packages

## Publishing
- [ ] `python test_filmify.py` is green locally
- [ ] `python build-packages.py` run; `filmify-mac.zip` / `filmify-windows.zip` refreshed at repo root
- [ ] CHANGELOG top entry matches `__version__`
- [ ] Commit, tag `vX.Y.Z`, push with `--tags`
- [ ] GitHub release updated: tag, both zips attached, description current
