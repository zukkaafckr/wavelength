#!/usr/bin/env python3
"""Render greetings/lines.json into ~/.local/share/zuka/greetings/<part>-N.wav with the local voice.

Needs the voice server running (the install's --voice step starts it). Reads the user's call-name from
~/.config/atticus/settings.json (userCallName). Trims leading/trailing silence and speeds up with ffmpeg (1.1x, acks 1.12x).
Without ffmpeg the clips are kept untrimmed and not sped up. Skips cleanly when the voice server is missing.
"""
import json, os, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
_APP_SOCK = f"{HOME}/Library/Caches/Wavelength/voice/voice.sock"   # the packaged app's voice (its folder is read-only)
SOCK = _APP_SOCK if os.path.exists(os.path.join(os.path.dirname(HERE), "python", "bin", "python3")) else f"{HOME}/.local/share/chatterbox/voice.sock"
OUT = f"{HOME}/.local/share/zuka/greetings"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
TRIM = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse"


def call_name():
    try:
        with open(f"{HOME}/.config/atticus/settings.json") as f:
            return str(json.load(f).get("userCallName") or "there")
    except (OSError, ValueError):
        return "there"


def render(text, out):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(240)
    s.connect(SOCK)
    s.sendall((json.dumps({"text": text, "out": out, "emotion": "friendly"}) + "\n").encode())
    return s.makefile("rb").readline().strip() == b"ok"


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__); return 0
    ffmpeg = FFMPEG if os.path.exists(FFMPEG) else shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found: keeping the untrimmed clips.")
    if not os.path.exists(SOCK):
        print("The voice server is not running: skipping greetings."); return 0
    user = call_name()
    with open(os.path.join(HERE, "lines.json")) as f:
        parts = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    made = 0
    with tempfile.TemporaryDirectory() as tmp:
        for part, lines in parts.items():
            for n, line in enumerate(lines, 1):
                raw, final = os.path.join(tmp, f"{part}-{n}.wav"), os.path.join(OUT, f"{part}-{n}.wav")
                try:
                    ok = render(line.replace("{user}", user), raw)
                except OSError as e:
                    print(f"{part}-{n}: voice server error ({e}); stopping."); return 1
                if not ok or not os.path.exists(raw):
                    print(f"{part}-{n}: no audio; skipped."); continue
                if not ffmpeg:
                    shutil.copy(raw, final); made += 1; print(f"made {part}-{n}.wav (untrimmed)"); continue
                r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", raw, "-af", f"{TRIM},atempo={1.12 if part == 'ack' else 1.1}", final])
                if r.returncode != 0:
                    shutil.copy(raw, final)   # trimming failed: keep the untouched clip
                made += 1
                print(f"made {part}-{n}.wav")
    print(f"{made} greetings in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
