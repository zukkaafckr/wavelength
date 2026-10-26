#!/bin/bash
# Build Wavelength's self-contained runtime: a portable Python 3.11 with the voice libraries, the light voice model,
# and the voice scripts, so the app needs nothing installed on the Mac (no Homebrew, no uv, no Claude Code).
#   packaging/make-runtime.sh OUT_DIR      -> OUT_DIR/python, OUT_DIR/kokoro, OUT_DIR/voice
# Needs (on the build Mac only): uv, and the Kokoro model in ~/.local/share/kokoro (or internet to fetch it).
set -e
OUT="${1:?usage: make-runtime.sh OUT_DIR}"
HERE=$(cd "$(dirname "$0")/.." && pwd)
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
mkdir -p "$OUT"

# 1. portable Python (python-build-standalone via uv: relocatable, any folder works)
uv python install 3.11 >/dev/null
SRC=$(ls -d "$HOME"/.local/share/uv/python/cpython-3.11.*-macos-aarch64-none | sort -V | tail -1)
[ -x "$SRC/bin/python3" ] || { echo "No portable Python 3.11 from uv"; exit 1; }
rm -rf "$OUT/python"; cp -R "$SRC" "$OUT/python"
rm -f "$OUT/python/lib/python3.11/EXTERNALLY-MANAGED"
uv pip install -q --python "$OUT/python/bin/python3" --system kokoro-onnx soundfile numpy
# trim what an assistant never uses
rm -rf "$OUT/python/lib/python3.11/test" "$OUT/python/lib/python3.11/idlelib" "$OUT/python/lib/python3.11/tkinter" \
       "$OUT/python/lib/python3.11/turtledemo" "$OUT/python/lib/python3.11/ensurepip" "$OUT/python/share" "$OUT/python/include"
find "$OUT/python" -name __pycache__ -type d -prune -exec rm -rf {} +

# 2. the light voice model (Kokoro int8 + voice styles, about 115 MB)
mkdir -p "$OUT/kokoro"
for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do
  if [ -f "$HOME/.local/share/kokoro/$f" ]; then cp "$HOME/.local/share/kokoro/$f" "$OUT/kokoro/"
  else curl -fL -o "$OUT/kokoro/$f" "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f"; fi
done

# 3. the voice scripts (team versions: no personal details)
mkdir -p "$OUT/voice"
T=~/Projects/zuka-team/team
cp "$T/voice/zuka_voice_light.py" "$T/voice/atticus_voice_server.py" "$T/voice/atticus-say" "$T/greetings/make-greetings.py" "$T/greetings/lines.json" "$OUT/voice/"
chmod +x "$OUT/voice/atticus-say"
# the spoken check-in (the setup's "Spoken check-ins" runs it from a LaunchAgent): this repo's copy reads the call name from settings and works with none
cp "$HERE/packaging/zuka-checkin" "$OUT/voice/zuka-checkin"; chmod +x "$OUT/voice/zuka-checkin"

# 4. check: the voice renders from here, offline, with nothing from this Mac's environment
env -i HOME="$HOME" PATH=/usr/bin:/bin HF_HUB_OFFLINE=1 "$OUT/python/bin/python3" -I - "$OUT" <<'PY'
import os, sys, time
out = sys.argv[1]; sys.path.insert(0, os.path.join(out, "voice"))
import zuka_voice_light as zl
from kokoro_onnx import Kokoro
k = Kokoro(f"{out}/kokoro/kokoro-v1.0.int8.onnx", f"{out}/kokoro/voices-v1.0.bin", espeak_config=zl.short_espeak())
t = time.time(); a, sr = k.create("Wavelength runtime check.", voice="af_heart", speed=1.0, lang="en-us")
assert len(a) > sr * 0.5, "no audio"
print(f"voice check ok ({time.time() - t:.1f}s)")
PY
du -sh "$OUT/python" "$OUT/kokoro" | sed 's/^/  /'
