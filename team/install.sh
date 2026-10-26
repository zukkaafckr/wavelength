#!/bin/bash
# Team install. Run AFTER team/personalize.py:
#   bash team/install.sh [--voice] [--pick VOICE] [--expressive] [--ram-gb N] [--no-open]
#   --voice       the natural voice, light and fast (about 350 MB download, works on any Mac, offline once set up)
#   --expressive  also record the greetings in the extra-expressive voice (+4 GB download; best on 16 GB Macs).
#                 Live replies always use the light voice. Implies --voice.
#   --pick VOICE  which voice: warm (default), bright, smooth, calm, british, indian, jarvis, deep, friendly-male, indian-male.
#                 Change it any time by saying "voice options" or "try the british voice".
#   --ram-gb N    accepted and ignored (older instructions used it)
#   DRY_RUN=1     print what would happen, change nothing
# Never uses sudo. Everything lands in your home folder.
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEAM="$REPO/team"
VOICE=0; EXPR=0; RAM=""; OPEN=1; PICK=""; DRY="${DRY_RUN:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --voice) VOICE=1 ;;
    --expressive) VOICE=1; EXPR=1 ;;
    --ram-gb) shift; RAM="${1:-}" ;;
    --no-open) OPEN=0 ;;
    --pick) shift; PICK="${1:-}"; VOICE=1
      case "$PICK" in warm|bright|smooth|calm|british|indian|jarvis|deep|friendly-male|indian-male) ;; *) echo "--pick: one of warm, bright, smooth, calm, british, indian, jarvis, deep, friendly-male, indian-male"; exit 2 ;; esac ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac; shift
done
if [ -n "$RAM" ]; then
  case "$RAM" in *[!0-9]*) echo "--ram-gb needs a number"; exit 2 ;; esac
  echo "(--ram-gb is no longer needed: the voice is light on every Mac. Ignoring it.)"
fi
run() { if [ -n "$DRY" ]; then echo "  [dry-run] $*"; else "$@"; fi; }
DONE=()
note() { DONE+=("$1"); echo "• $1"; }

if [ -n "$DRY" ]; then
  NAME=Name; CALL=Call; echo "[dry-run] skipping the checks, the app build and the settings file"
else
[ -f "$TEAM/.personalized" ] || { echo "Run python3 team/personalize.py NAME CALLNAME first."; exit 1; }
NAME=$(sed -n 's/^name=\(.*\) call=.*/\1/p' "$TEAM/.personalized"); CALL=$(sed -n 's/^name=.* call=\(.*\)/\1/p' "$TEAM/.personalized")
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || { echo "$NAME needs macOS 26 or later."; exit 1; }
if ! xcode-select -p >/dev/null 2>&1; then
  echo "First, Apple's command line tools. A macOS window will open: click Install, then run this again."
  xcode-select --install 2>/dev/null || true; exit 1
fi
CLAUDE_BIN=$(command -v claude || true)
for c in "$HOME/.local/bin/claude" "$HOME/.claude/local/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do [ -n "$CLAUDE_BIN" ] || { [ -x "$c" ] && CLAUDE_BIN="$c"; }; done
[ -n "$CLAUDE_BIN" ] || { echo "Claude Code was not found. Install it from https://claude.com/claude-code, sign in, then run this again."; exit 1; }
note "Checked: macOS $(sw_vers -productVersion), command line tools, Claude Code"

# 1. build the app (build.sh stages the compile first, so a failed build leaves any older app alone)
"$REPO/build.sh"
note "Built the app into ~/Applications/Atticus.app (shown as $NAME)"

# 2. settings, merged into any existing file; the app reads them at launch
mkdir -p "$HOME/.config/atticus"
NAME="$NAME" CALL="$CALL" python3 -I - <<'PY'
import json, os
p = os.path.expanduser("~/.config/atticus/settings.json")
try: s = json.load(open(p))
except (OSError, ValueError): s = {}
s.update(assistantName=os.environ["NAME"], userCallName=os.environ["CALL"], usageCheck=True, quietAgents=True, dictateMode="verbatim", autoUpdate=False, stats=False,
         improve=False, improveAsked=True, support=False, talkMode="toggle", routing="cheapest", speak=True, greet=True)
with open(p, "w") as f: json.dump(s, f, indent=2)
os.chmod(p, 0o600)
PY
note "Wrote settings: ask before using your Claude plan, no telemetry, no background updates, press-to-talk, cheapest routing, speak and greet on"
if [ -n "$PICK" ]; then [ -n "$DRY" ] || printf '{"pick": "%s"}\n' "$PICK" > "$HOME/.config/atticus/voice.json"; note "Voice: $PICK (say \"voice options\" any time to hear the others)"; fi
fi

# 3. voice
CB="$HOME/.local/share/chatterbox"; KO="$HOME/.local/share/kokoro"; LA="$HOME/Library/LaunchAgents"; UID_N=$(id -u)
KURL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
run mkdir -p "$LA" "$HOME/.local/share/zuka"
write_plist() {  # $1 = python, $2 = server script
  if [ -n "$DRY" ]; then echo "  [dry-run] write $LA/com.zuka.voice.plist (runs $2 with $1, KeepAlive, RunAtLoad)"; return; fi
  cat > "$LA/com.zuka.voice.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.zuka.voice</string>
<key>ProgramArguments</key><array><string>$1</string><string>-I</string><string>$2</string></array>
<key>EnvironmentVariables</key><dict><key>ATTICUS_VOICE_IDLE_MIN</key><string>0</string><key>TQDM_DISABLE</key><string>1</string><key>PYTHONWARNINGS</key><string>ignore</string></dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>Nice</key><integer>5</integer>
<key>ThrottleInterval</key><integer>15</integer>
<key>StandardErrorPath</key><string>$HOME/.config/atticus/voice.log</string>
</dict></plist>
P
}
if [ "$VOICE" = 1 ]; then
  command -v uv >/dev/null || [ -n "$DRY" ] || { echo "The natural voice needs uv. Run: brew install uv   (or see https://docs.astral.sh/uv/ ), then run this again with --voice."; exit 1; }
  run mkdir -p "$CB/voices" "$KO" "$HOME/.config/atticus"
  run cp "$TEAM/voice/atticus_voice_server.py" "$TEAM/voice/zuka_voice_light.py" "$TEAM/voice/atticus-say" "$CB/"
  run chmod +x "$CB/atticus-say"
  run cp "$TEAM/voice/voices/"*.wav "$CB/voices/"
  run rm -f "$CB/engine" "$CB/idle-min"   # live replies always use the light voice
  # light voice: Kokoro (about 350 MB)
  if [ ! -x "$KO/.venv/bin/python" ] || [ -n "$DRY" ]; then run uv venv --python 3.11 "$KO/.venv"; fi
  run uv pip install --python "$KO/.venv/bin/python" kokoro-onnx soundfile numpy
  for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do
    if [ -s "$KO/$f" ]; then echo "  $f already downloaded"; else run curl -fL --retry 3 -o "$KO/$f.part" "$KURL/$f"; run mv "$KO/$f.part" "$KO/$f"; fi
  done
  note "Set up the light voice (Kokoro, about 350 MB, works offline)"
  run launchctl bootout "gui/$UID_N/com.zuka.voice" 2>/dev/null || true
  if [ "$EXPR" = 1 ]; then
    # extra-expressive greetings: use the big voice once, only to record the greetings, then stop it
    if [ -n "$DRY" ]; then echo "  [dry-run] uv venv --python 3.11 $CB/.venv (if missing)"; else [ -x "$CB/.venv/bin/python" ] || uv venv --python 3.11 "$CB/.venv"; fi
    run uv pip install --python "$CB/.venv/bin/python" -r "$TEAM/voice/requirements.txt"
    echo "Downloading the extra-expressive voice once (about 4 GB, this takes a while)..."
    run env HF_HUB_OFFLINE=0 "$CB/.venv/bin/python" -I -c "from chatterbox.tts_turbo import ChatterboxTurboTTS as M; M.from_pretrained(device='cpu')"
    run rm -f "$CB/voice.sock"
    if [ -n "$DRY" ]; then
      echo "  [dry-run] start $CB/atticus_voice_server.py (HF_HUB_OFFLINE=0), wait for the socket"
      echo "  [dry-run] python3 -I $TEAM/greetings/make-greetings.py   (expressive greetings)"
      echo "  [dry-run] stop the expressive server and remove voice.sock"
    else
      ( HF_HUB_OFFLINE=0 ATTICUS_VOICE_IDLE_MIN=0 TQDM_DISABLE=1 nohup "$CB/.venv/bin/python" -I "$CB/atticus_voice_server.py" >>"$HOME/.config/atticus/voice.log" 2>&1 & echo $! > "$CB/expressive.pid" )
      for _ in $(seq 1 120); do [ -S "$CB/voice.sock" ] && break; sleep 2; done
      if [ -S "$CB/voice.sock" ]; then
        python3 -I "$TEAM/greetings/make-greetings.py" && note "Recorded the greetings in the extra-expressive voice" || note "Greetings were skipped (see message above)"
      else
        note "The expressive voice did not start in time; greetings skipped (run team/greetings/make-greetings.py later)"
      fi
      kill "$(cat "$CB/expressive.pid" 2>/dev/null)" 2>/dev/null || true; sleep 2; rm -f "$CB/expressive.pid" "$CB/voice.sock"
    fi
  fi
  write_plist "$KO/.venv/bin/python" "$CB/zuka_voice_light.py"
  run launchctl bootstrap "gui/$UID_N" "$LA/com.zuka.voice.plist"
  note "Started the light voice now and at every login (it stays loaded; it is small)"
  if [ "$EXPR" != 1 ]; then
    if [ -n "$DRY" ]; then
      echo "  [dry-run] wait for $CB/voice.sock, then python3 -I $TEAM/greetings/make-greetings.py   (greetings in the light voice)"
    else
      for _ in $(seq 1 45); do [ -S "$CB/voice.sock" ] && break; sleep 2; done
      if [ -S "$CB/voice.sock" ]; then
        python3 -I "$TEAM/greetings/make-greetings.py" && note "Recorded the time-of-day greetings" || note "Greetings were skipped (see message above)"
      else
        note "The voice did not start in time; greetings skipped (run team/greetings/make-greetings.py later)"
      fi
    fi
  fi
else
  note "Using the free Mac voice (run again with --voice for the natural voice)"
fi

# 4. check-ins (spoken hellos at set times, free, weekdays)
if [ -n "$DRY" ]; then echo "  [dry-run] install the check-ins (zuka-checkin + com.zuka.checkin agent)"; echo; echo "Dry run finished. Nothing was changed."; exit 0; fi
cp "$TEAM/checkin/zuka-checkin" "$HOME/.local/share/zuka/zuka-checkin"; chmod +x "$HOME/.local/share/zuka/zuka-checkin"
{
cat <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.zuka.checkin</string>
<key>ProgramArguments</key><array><string>/bin/sh</string><string>-c</string><string>h=\$(date +%H); if [ \$h -lt 12 ]; then p=morning; elif [ \$h -lt 17 ]; then p=afternoon; else p=evening; fi; exec $HOME/.local/share/zuka/zuka-checkin \$p</string></array>
<key>StartCalendarInterval</key><array>
P
for d in 1 2 3 4 5 6; do for t in "10 0" "14 30" "18 30"; do set -- $t
  echo "<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$1</integer><key>Minute</key><integer>$2</integer></dict>"; done; done
echo "</array>"; echo "</dict></plist>"
} > "$LA/com.zuka.checkin.plist"
launchctl bootout "gui/$UID_N/com.zuka.checkin" 2>/dev/null || true
launchctl bootstrap "gui/$UID_N" "$LA/com.zuka.checkin.plist"
note "Installed the check-ins (Mon-Sat at 10:00, 14:30 and 18:30, only when you are at the Mac)"

# 5. the voice they picked, the greeting recorder (for voice changes later) and team updates
mkdir -p "$HOME/.local/share/zuka/greetings-maker"; cp "$TEAM/greetings/make-greetings.py" "$TEAM/greetings/lines.json" "$HOME/.local/share/zuka/greetings-maker/"
command -v gh >/dev/null && gh auth setup-git >/dev/null 2>&1 || true   # lets the updater read the private repo with their GitHub sign-in
cat > "$LA/com.wavelength.update.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.wavelength.update</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>$TEAM/update.sh</string><string>--auto</string></array>
<key>StartInterval</key><integer>3600</integer>
<key>RunAtLoad</key><true/>
<key>StandardErrorPath</key><string>$HOME/.config/atticus/update.log</string>
</dict></plist>
P
launchctl bootout "gui/$UID_N/com.wavelength.update" 2>/dev/null || true
launchctl bootstrap "gui/$UID_N" "$LA/com.wavelength.update.plist"
note "Team updates: checked every hour and installed while you're away from the Mac (tested first; your names and voice stay)"

echo; echo "All done. What I did:"; for d in "${DONE[@]}"; do echo "  - $d"; done
if [ "$OPEN" = 1 ]; then open "$HOME/Applications/Atticus.app"; echo "Opened $NAME. Its setup window walks you through the permissions."; fi
