#!/bin/bash
# filmify-drop — double-click me, then drag a video file or folder into
# this window and press Return for a fast split-screen preview of the
# film look (original left, graded right).
cd "$(dirname "$0")" || exit 1

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo
  echo "  Python was not found. Install it with:  brew install python3"
  echo "  (or from https://www.python.org/downloads/) and try again."
  echo
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi

echo
echo "  filmify — drag a video file or folder into this window, then press Return:"
echo
read -r -p "  > " RAW
if [ -z "$RAW" ]; then
  echo "  Nothing dropped — closing."
  exit 1
fi
# Terminal pastes the path shell-escaped; expand it the way the shell would.
eval "ARGS=($RAW)"

"$PY" filmify.py "${ARGS[@]}" --compare --preview
echo
read -n 1 -s -r -p "Press any key to close."
echo
