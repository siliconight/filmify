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

# The app's job: remember where filmify lives (this folder) and hand off to
# the silent launcher. The repo path is baked in at build time, so the app
# keeps working even after you move it to /Applications.
read -r -d '' SRC <<APPLESCRIPT
on run
	set repoDir to "HERE_PLACEHOLDER"
	do shell script "cd " & quoted form of repoDir & " && /bin/bash ./filmify-launch.sh > /dev/null 2>&1 &"
end run
APPLESCRIPT
SRC="${SRC/HERE_PLACEHOLDER/$HERE}"

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

# Build the app icon from the bundled PNG, locally (iconutil is Mac-only,
# which is why we generate the .icns here rather than shipping one).
ICON_PNG="$HERE/filmify_icon_1024.png"
if [ -f "$ICON_PNG" ] && command -v iconutil >/dev/null 2>&1; then
  ICONSET="$(mktemp -d)/filmify.iconset"
  mkdir -p "$ICONSET"
  for sz in 16 32 64 128 256 512; do
    sips -z $sz $sz "$ICON_PNG" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null 2>&1
    sips -z $((sz*2)) $((sz*2)) "$ICON_PNG" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1
  done
  if iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/applet.icns" 2>/dev/null; then
    touch "$APP" 2>/dev/null   # nudge Finder to refresh the icon
  fi
  rm -rf "$(dirname "$ICONSET")"
fi

echo
echo "  Done. There is now a 'filmify' app in this folder."

# Offer to place it in Applications so it behaves like any installed app.
osascript <<INSTALL >/dev/null 2>&1
try
	display dialog "filmify.app is built. Move it to your Applications folder so it shows up with your other apps?" buttons {"Keep it here", "Move to Applications"} default button 2 with title "filmify" with icon note
	if button returned of result is "Move to Applications" then
		do shell script "ditto " & quoted form of "$APP" & " /Applications/filmify.app && rm -rf " & quoted form of "$APP"
		display dialog "filmify is now in your Applications folder. Open it from Launchpad or Applications any time — drag it to your Dock if you like." buttons {"Great"} default button 1 with title "filmify" with icon note
		tell application "Finder" to reveal (POSIX file "/Applications/filmify.app")
	end if
end try
INSTALL

echo "  Double-click filmify any time — drag it to your Dock if you like."
echo "  (Terminal is no longer needed.)"
echo
read -n 1 -s -r -p "  Press any key to close."
echo
