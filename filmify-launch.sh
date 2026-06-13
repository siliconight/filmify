#!/bin/bash
# filmify-launch.sh — the engine behind filmify.app. Does everything through
# native macOS dialogs (no Terminal text the user has to read), then opens
# the control panel in the browser. Also runnable on its own.

cd "$(dirname "$0")" || exit 1

dialog() {  # $1 = message, $2 = icon (note|stop)
  osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with icon ${2:-note} with title \"filmify\"" >/dev/null 2>&1
}
ask() {     # $1 = message -> returns 0 if user clicked the affirmative button
  osascript -e "display dialog \"$1\" buttons {\"Not now\", \"Continue\"} default button 2 with icon note with title \"filmify\"" 2>/dev/null | grep -q "Continue"
}

# ---- Python ----------------------------------------------------------------
if ! python3 --version >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    dialog "macOS needs to install a small set of tools (this includes Python) before filmify can run.\n\nClick OK, then click Install in the macOS dialog that appears. When it finishes, open filmify again." note
    python3 --version >/dev/null 2>&1   # triggers Apple's installer dialog
  else
    dialog "Python wasn't found. Install it from python.org/downloads, then open filmify again." stop
  fi
  exit 1
fi

# ---- FFmpeg ----------------------------------------------------------------
have() { [ -x "./$1" ] || command -v "$1" >/dev/null 2>&1; }
fetch() {  # $1 tool, $2 url
  curl -fSL -o "/tmp/filmify_$1.zip" "$2" >/dev/null 2>&1 || return 1
  unzip -oq "/tmp/filmify_$1.zip" "$1" -d . 2>/dev/null || unzip -oq "/tmp/filmify_$1.zip" -d . 2>/dev/null
  rm -f "/tmp/filmify_$1.zip"
  chmod +x "./$1" 2>/dev/null
  command -v xattr >/dev/null 2>&1 && xattr -dr com.apple.quarantine "./$1" 2>/dev/null
  "./$1" -version >/dev/null 2>&1
}
if ! have ffmpeg || ! have ffprobe; then
  if [ "$(uname -m)" = "arm64" ]; then
    FF="https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip"
    FP="https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffprobe.zip"
  else
    FF="https://evermeet.cx/ffmpeg/getrelease/zip"
    FP="https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
  fi
  if ! ask "filmify needs FFmpeg, the free video engine (about 70 MB, downloaded once and kept in this folder). Download it now?"; then
    exit 1
  fi
  # Progress lives in a tiny Terminal-free spinner dialog isn't feasible in
  # pure osascript, so we show a heads-up and download quietly.
  osascript -e 'display notification "Downloading FFmpeg — this can take a minute." with title "filmify"' 2>/dev/null
  ok=1
  have ffmpeg  || fetch ffmpeg  "$FF" || ok=0
  have ffprobe || fetch ffprobe "$FP" || ok=0
  if [ "$ok" = "0" ]; then
    dialog "FFmpeg download failed. Check your internet connection and open filmify again, or install it with: brew install ffmpeg" stop
    exit 1
  fi
fi

# ---- Pick a clip and launch the panel --------------------------------------
PICK=$(osascript -e 'try' \
  -e 'POSIX path of (choose file with prompt "filmify — choose a video clip (Cancel to pick a folder of clips)")' \
  -e 'end try' 2>/dev/null)
if [ -z "$PICK" ]; then
  PICK=$(osascript -e 'try' \
    -e 'POSIX path of (choose folder with prompt "filmify — choose a folder of clips to batch")' \
    -e 'end try' 2>/dev/null)
fi
[ -z "$PICK" ] && exit 0

PY=python3
if [ -d "$PICK" ]; then
  # Folder: batch the whole thing, then show the report (no panel)
  osascript -e 'display notification "Processing your clips… the report opens when done." with title "filmify"' 2>/dev/null
  "$PY" filmify.py "$PICK" --compare --preview >/dev/null 2>&1
else
  # Single clip: open the control panel. run_ui opens the browser itself.
  "$PY" filmify.py "$PICK" --ui >/dev/null 2>&1
fi
