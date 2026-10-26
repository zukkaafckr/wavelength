#!/bin/bash
# Build ~/Downloads/Wavelength/Wavelength-<VERSION>.dmg: a self-contained, ad hoc signed Wavelength.app (not notarized yet).
# Does not touch the installed app, its LaunchAgent or the live voice.
set -e
cd "$(dirname "$0")/.."
VERSION=$(tr -d '\n' < VERSION)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
./build.sh --package "$W/build"
APP="$W/build/Wavelength.app"; RT="$APP/Contents/Resources/runtime"

echo "== verify =="
"$RT/python/bin/python3" -I -c "import kokoro_onnx; print('import kokoro_onnx ok')"
env -i HOME="$HOME" PATH=/usr/bin:/bin "$RT/python/bin/python3" -I - "$RT" <<'PY'
import os, sys, time
rt = sys.argv[1]; sys.path.insert(0, rt + "/voice")
import zuka_voice_light as zl
from kokoro_onnx import Kokoro
assert zl.KOKORO == rt + "/kokoro", zl.KOKORO
k = Kokoro(f"{rt}/kokoro/kokoro-v1.0.int8.onnx", f"{rt}/kokoro/voices-v1.0.bin", espeak_config=zl.short_espeak())
t = time.time(); a, sr = k.create("Wavelength voice check.", voice="af_heart", speed=1.0, lang="en-us")
assert len(a) > sr * 0.5, "no audio"
print(f"voice render ok ({len(a) / sr:.1f}s of audio in {time.time() - t:.1f}s, clean env)")
PY
OUT=$(ATTICUS_DIR=$(mktemp -d) WAVELENGTH_RUNTIME="$RT" PATH="$RT/python/bin:/usr/bin:/bin" ATTICUS_RESOURCES_DIR="$APP/Contents/Resources" \
  /bin/sh "$APP/Contents/Resources/atticus.py" --fast "what time is it" 2>&1) || { echo "atticus.py --fast failed: $OUT"; exit 1; }
echo "atticus.py --fast ok: $OUT"
codesign --verify --deep --strict "$APP" && echo "codesign verify ok"

echo "== dmg =="
D="$W/dmg"; mkdir -p "$D"
cp -R "$APP" "$D/"
ln -s /Applications "$D/Applications"
printf 'Drag Wavelength to the Applications folder.\nFirst open: right-click Wavelength, choose Open, then Open again (it is not notarized yet).\n' > "$D/Open me first.txt"
mkdir -p ~/Downloads/Wavelength
DMG=~/Downloads/Wavelength/Wavelength-$VERSION.dmg
rm -f "$DMG"
hdiutil create -quiet -volname "Wavelength" -srcfolder "$D" -format UDZO -fs HFS+ "$DMG"
echo "$DMG"; du -h "$DMG" | cut -f1
