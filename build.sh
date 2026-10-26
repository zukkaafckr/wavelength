#!/bin/bash
# Installs Atticus: builds Atticus.app, starts it at login, and (re)starts it now. Run it again after any change.
# ./build.sh                  install + start the dev build (~/Applications/Atticus.app, com.atticus.app)
# ./build.sh --package OUTDIR  build only OUTDIR/Wavelength.app (com.wavelength.app), self-contained with its own runtime; installs and starts nothing
set -e
PACKAGE=""
if [ "$1" = "--package" ]; then
  [ -n "$2" ] || { echo "usage: build.sh --package OUTDIR"; exit 1; }
  mkdir -p "$2"; PACKAGE=$(cd "$2" && pwd)
fi
cd "$(dirname "$0")"
VERSION=$(tr -d '\n' < VERSION)
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid VERSION: $VERSION"; exit 1; }
IFS=. read -r VERSION_MAJOR VERSION_MINOR VERSION_PATCH <<< "$VERSION"
(( VERSION_MINOR < 1000 && VERSION_PATCH < 1000 )) || { echo "VERSION components must be below 1000"; exit 1; }
BUILD=$((VERSION_MAJOR * 1000000 + VERSION_MINOR * 1000 + VERSION_PATCH))
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || { echo "Atticus needs macOS 26 or later (it uses Apple's new on-device speech)."; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "Needs Apple's command line tools. Run: xcode-select --install   then run ./build.sh again."; exit 1; }
command -v python3 >/dev/null || { echo "Atticus needs Python 3. Install it, then run ./build.sh again."; exit 1; }
[ -n "$PACKAGE" ] || command -v claude >/dev/null || [ -x ~/.local/bin/claude ] || echo "Note: Claude Code is not installed yet. Atticus's setup window can install it, or you can pick Devin or Pi."
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
# A compiler error must leave the installed app and its resources alone.
swiftc -O -target "$(uname -m)-apple-macos26.0" Atticus.swift -o "$STAGE/Atticus"
APP=~/Applications/Atticus.app   # in Applications so System Settings can list it for permissions
BUNDLE_ID=com.atticus.app; SOURCE=$(pwd)
if [ -n "$PACKAGE" ]; then APP="$PACKAGE/Wavelength.app"; BUNDLE_ID=com.wavelength.app; SOURCE=""; rm -rf "$APP"; fi   # a package has no source folder to update from
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/ui"
cp atticus.py zuka_commands.py zuka_more.py "$APP/Contents/Resources/"
cp ui/*.html ui/*.js "$APP/Contents/Resources/ui/"
cp ui/AppIcon.icns "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
<key>CFBundleName</key><string>Wavelength</string>
<key>CFBundleDisplayName</key><string>Wavelength</string>
<key>CFBundleExecutable</key><string>Atticus</string>
<key>CFBundleVersion</key><string>$BUILD</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>AtticusSource</key><string>$SOURCE</string>
<key>LSUIElement</key><true/>
<key>CFBundleURLTypes</key><array><dict><key>CFBundleURLName</key><string>Wavelength</string><key>CFBundleURLSchemes</key><array><string>wavelength</string></array></dict></array>
<key>NSMicrophoneUsageDescription</key><string>Wavelength listens when you use its shortcut or microphone button.</string>
<key>NSAppleEventsUsageDescription</key><string>Wavelength controls apps like Finder, Chrome and Music when you ask it to.</string>
<key>NSCalendarsFullAccessUsageDescription</key><string>Wavelength reads your calendar, adds events you request, and asks before moving or deleting existing events. Calendar details are sent to your chosen AI model.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Wavelength turns your words into text on this Mac.</string>
</dict></plist>
P
mv "$STAGE/Atticus" "$APP/Contents/MacOS/Atticus"
if [ -n "$PACKAGE" ]; then
  # Self-contained: portable Python + voice model + voice scripts go inside the app, so the Mac needs nothing installed.
  packaging/make-runtime.sh "$APP/Contents/Resources/runtime"
  cp packaging/managed.json "$APP/Contents/Resources/managed.json"   # the owner's fixed settings: users see and change only user settings
  # Every Mach-O inside the runtime gets its own ad hoc signature, then the whole app is sealed once, after everything is copied.
  find "$APP/Contents/Resources/runtime" -type f \( -perm -u+x -o -name '*.so' -o -name '*.dylib' \) -print0 |
    while IFS= read -r -d '' f; do file -b "$f" | grep -q Mach-O && codesign --force -s - "$f" 2>/dev/null; done || true
  codesign --force --deep -s - "$APP"
  echo "Packaged: $APP"
  exit 0
fi
# With a code-signing identity named "Atticus Local Signing" in the keychain, macOS keeps permissions across
# rebuilds and auto-updates; ad hoc signing would ask for every permission again after each one. So make it once.
ID=$(security find-identity -p codesigning | awk '/Atticus Local Signing/{print $2; exit}')
if [ -z "$ID" ]; then
  K=$(mktemp -d)
  /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 7300 -subj "/CN=Atticus Local Signing" -addext "extendedKeyUsage=critical,codeSigning" \
    -addext "keyUsage=critical,digitalSignature" -keyout "$K/k.pem" -out "$K/c.pem" 2>/dev/null &&
  /usr/bin/openssl pkcs12 -export -inkey "$K/k.pem" -in "$K/c.pem" -out "$K/a.p12" -passout pass:atticus 2>/dev/null &&
  security import "$K/a.p12" -P atticus -T /usr/bin/codesign >/dev/null 2>&1 || true   # fails quietly: ad hoc still works
  rm -rf "$K"
  ID=$(security find-identity -p codesigning | awk '/Atticus Local Signing/{print $2; exit}')
fi
codesign -s "${ID:--}" --force "$APP"
# register with macOS, or System Settings can't list it for permissions
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
AGENT=~/Library/LaunchAgents/com.atticus.app.plist   # starts at login, restarts if it crashes (Quit stays quit)
mkdir -p ~/Library/LaunchAgents ~/.config/atticus
cat > "$AGENT" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.atticus.app</string>
<key>ProgramArguments</key><array><string>$APP/Contents/MacOS/Atticus</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
<key>StandardErrorPath</key><string>$HOME/.config/atticus/app.err</string>
</dict></plist>
P
[ -n "$ATTICUS_NO_RESTART" ] && exit 0   # the app's own updater restarts it when idle
# Reload the job so launchd refreshes its executable signing requirement after a rebuild.
launchctl bootout gui/$(id -u)/com.atticus.app 2>/dev/null || true
pkill -f "$APP/Contents/MacOS/Atticus$" 2>/dev/null && sleep 1   # stop a copy opened by hand too
# bootout can return before the job has finished unloading.
launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || { sleep 1; launchctl bootstrap gui/$(id -u) "$AGENT" 2>/dev/null || {
  echo "Could not add Atticus to Login Items; opening it directly instead."
  open "$APP"
}; }
echo "Atticus is running. Hold Control+Option+Space and talk."
