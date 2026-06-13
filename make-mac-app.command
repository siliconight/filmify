#!/bin/bash
# Build filmify.app — run me ONCE (right-click → Open the first time).
# I create a real Mac app, right here in this folder, that you can then
# double-click like any other program (and drag to your Dock). After this,
# you never need Terminal or a right-click again.
#
# Why this works: an app you build on your own Mac isn't quarantined the way
# a downloaded script is — so filmify.app opens with a normal double-click.

cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
APP="$HERE/filmify.app"

echo
echo "  Building filmify.app in this folder…"

# The app's job: find this folder, then hand off to the silent launcher.
# It lives wherever it's built, so it resolves its own path at run time.
read -r -d '' SRC <<APPLESCRIPT
on run
	set hereAlias to (path to me)
	tell application "Finder" to set hereFolder to (container of hereAlias) as alias
	set herePosix to POSIX path of hereFolder
	do shell script "cd " & quoted form of herePosix & " && /bin/bash ./filmify-launch.sh > /dev/null 2>&1 &"
end run
APPLESCRIPT

rm -rf "$APP"
if ! osacompile -o "$APP" -e "$SRC" 2>/dev/null; then
  echo "  Could not build the app automatically."
  echo "  You can still use filmify by double-clicking START-HERE-MAC.command."
  read -n 1 -s -r -p "  Press any key to close."
  exit 1
fi

# Give the app filmify's own identity so it reads as a real program.
PLIST="$APP/Contents/Info.plist"
if [ -f "$PLIST" ]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleName filmify" "$PLIST" 2>/dev/null
  /usr/libexec/PlistBuddy -c "Add :LSBackgroundOnly bool false" "$PLIST" 2>/dev/null
fi

echo
echo "  Done. There is now a 'filmify' app in this folder."
echo "  Double-click it any time — drag it to your Dock if you like."
echo "  (Terminal is no longer needed.)"
echo
read -n 1 -s -r -p "  Press any key to close."
echo
