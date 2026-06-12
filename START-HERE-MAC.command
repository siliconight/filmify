#!/bin/bash
# filmify-drop — double-click me. First run sets everything up:
#   * If Python is missing, macOS's own install dialog appears — click
#     Install, wait, then double-click me again.
#   * If FFmpeg is missing, I offer to download the official static build
#     for your Mac (Intel: evermeet.cx — the build linked from ffmpeg.org;
#     Apple Silicon: ffmpeg.martin-riedl.de) right next to this script.
# After that: drag a video file or folder into this window, press Return,
# and you get a fast split-screen preview (original left, film look right).

cd "$(dirname "$0")" || exit 1

pause_exit() {
  echo
  read -n 1 -s -r -p "Press any key to close."
  echo
  exit "${1:-0}"
}

# ---- Python ----------------------------------------------------------------
if ! python3 --version >/dev/null 2>&1; then
  echo
  if command -v python3 >/dev/null 2>&1; then
    # Stock macOS: the python3 shim exists and the failed call above has
    # just triggered Apple's signed "install command line developer tools"
    # dialog. That install includes Python.
    echo "  macOS is asking to install its command line developer tools"
    echo "  (that includes Python — it's Apple's own installer)."
    echo
    echo "  Click Install in the dialog, wait for it to finish,"
    echo "  then double-click filmify-drop again."
  else
    echo "  Python was not found. Install it from:"
    echo "      https://www.python.org/downloads/"
    echo "  then double-click filmify-drop again."
  fi
  pause_exit 1
fi

# ---- FFmpeg ----------------------------------------------------------------
have_tool() { [ -x "./$1" ] || command -v "$1" >/dev/null 2>&1; }

fetch_tool() {  # $1 = tool name, $2 = url, $3 = source label
  echo "  downloading $1 from $3 ..."
  if ! curl -fSL --progress-bar -o "/tmp/filmify_$1.zip" "$2"; then
    echo
    echo "  Download failed. Check your internet connection, or install"
    echo "  FFmpeg yourself (https://ffmpeg.org) and run me again."
    pause_exit 1
  fi
  unzip -oq "/tmp/filmify_$1.zip" "$1" -d . || unzip -oq "/tmp/filmify_$1.zip" -d .
  rm -f "/tmp/filmify_$1.zip"
  chmod +x "./$1" 2>/dev/null
  command -v xattr >/dev/null 2>&1 && xattr -dr com.apple.quarantine "./$1" 2>/dev/null
  if ! "./$1" -version >/dev/null 2>&1; then
    echo "  $1 downloaded but won't run on this Mac — please install FFmpeg"
    echo "  yourself (https://ffmpeg.org) and run me again."
    pause_exit 1
  fi
}

if ! have_tool ffmpeg || ! have_tool ffprobe; then
  if [ "$(uname -m)" = "arm64" ]; then
    FF_URL="https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip"
    FP_URL="https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffprobe.zip"
    SRC="ffmpeg.martin-riedl.de (Apple Silicon static build)"
  else
    FF_URL="https://evermeet.cx/ffmpeg/getrelease/zip"
    FP_URL="https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
    SRC="evermeet.cx (the macOS build linked from ffmpeg.org)"
  fi
  echo
  echo "  filmify needs FFmpeg (the free, open-source video engine)."
  echo "  I can download the official static build for your Mac from:"
  echo "      $SRC"
  echo "  It will be saved next to this script — nothing is installed"
  echo "  system-wide."
  echo
  read -r -p "  Download now? [Y/n] " yn
  case "$yn" in
    [Nn]*) echo "  OK — install FFmpeg yourself and run me again."; pause_exit 1 ;;
  esac
  have_tool ffmpeg  || fetch_tool ffmpeg  "$FF_URL" "$SRC"
  have_tool ffprobe || fetch_tool ffprobe "$FP_URL" "$SRC"
  echo "  FFmpeg ready."
fi

# ---- Pick the input ----------------------------------------------------------
PICK=""
if command -v osascript >/dev/null 2>&1; then
  # Native macOS file picker — no dragging, no typing
  PICK=$(osascript -e 'try' \
    -e 'POSIX path of (choose file with prompt "filmify — choose a video clip (Cancel to pick a folder of clips instead)")' \
    -e 'end try' 2>/dev/null)
  if [ -z "$PICK" ]; then
    PICK=$(osascript -e 'try' \
      -e 'POSIX path of (choose folder with prompt "filmify — choose a folder of clips to batch")' \
      -e 'end try' 2>/dev/null)
  fi
  if [ -z "$PICK" ]; then
    echo "  Nothing chosen — closing."
    pause_exit 0
  fi
else
  # No osascript (non-macOS shell): fall back to drag-into-window
  echo
  echo "  filmify — drag a video file or folder into this window, then press Return:"
  echo
  read -r -p "  > " RAW
  [ -z "$RAW" ] && { echo "  Nothing dropped — closing."; pause_exit 1; }
  eval "ARGS=($RAW)"
  PICK="${ARGS[0]}"
fi

if [ -d "$PICK" ]; then
  # Folder: batch a fast split-screen preview of every clip
  "$PY" filmify.py "$PICK" --compare --preview
  pause_exit 0
else
  # Single clip: open the control panel (close this window to stop it)
  echo
  echo "  Opening the filmify panel in your browser."
  echo "  Keep this window open while you work; close it when you're done."
  echo
  "$PY" filmify.py "$PICK" --ui
  pause_exit 0
fi
