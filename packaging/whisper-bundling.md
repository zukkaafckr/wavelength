# Bundling Whisper dictation (not done yet)

Wavelength's hold-fn dictation uses `whisper-cli` and `whisper-server` (whisper.cpp, Metal) plus
`ggml-large-v3-turbo-q5_0.bin` when they are on this Mac. Today they come from Homebrew and
`~/.local/share/whisper/`; the app looks in `/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`
(`WhisperDictation.tool` in Atticus.swift) and falls back to Apple speech when anything is missing.

To ship it inside the app later:

1. Binaries: build whisper.cpp from a pinned tag with `-DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON
   -DBUILD_SHARED_LIBS=OFF -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 -DCMAKE_OSX_ARCHITECTURES=arm64`
   so `whisper-cli` and `whisper-server` are single static files with no Homebrew dylibs.
   Put them in `Atticus.app/Contents/Resources/whisper/` next to `make-runtime.sh`'s output
   (copy them in the same step that copies `atticus.py`).
2. Model: 550 MB, so do not put it in the DMG. Download `ggml-large-v3-turbo-q5_0.bin` on first use from
   `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/` into `~/.local/share/whisper/`, with a
   progress line in Settings and a SHA-256 check. Until it lands the app keeps using Apple speech.
   (`ggml-base.en-q5_1.bin`, ~60 MB, is a fine small fallback.)
3. Code signing and notarization: sign both binaries with the app's Developer ID and hardened runtime
   (`codesign --options runtime --timestamp`), sign them before the app bundle, and notarize the whole DMG.
   They need no extra entitlements: they only read the model and a WAV, and the server listens on 127.0.0.1.
4. Code change: in `WhisperDictation.tool` look in `Bundle.main.resourcePath + "/whisper/"` first;
   nothing else changes. `modelPath` stays in `~/.local/share/whisper/`.
5. The server is started lazily on the first dictation, stopped after 45 idle minutes (a long take's full-window server after 10) and at app quit, and a
   stale one from a crashed app is killed through the pid file in the temp folder.
6. Memory: the q5_0 model plus Metal buffers is roughly 1 GB resident while the server is warm. On 8 GB
   Macs that is why it idles out. Do not raise the thread count above 4.
