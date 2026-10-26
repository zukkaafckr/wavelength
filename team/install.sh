#!/bin/bash
# Team install. Run AFTER team/personalize.py:
#   bash team/install.sh [--voice] [--ram-gb N] [--no-open]
#   --voice      the natural voice (about 4 GB download); without it the free Mac voice is used
#   --ram-gb N   this Mac's memory. N<=8: the voice unloads after 15 idle minutes and does not start at login.
#                N>=16: the voice stays loaded and starts at login. In between: like 8 GB.
# Never uses sudo. Everything lands in your home folder.
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEAM="$REPO/team"
VOICE=0; RAM=0; OPEN=1
while [ $# -gt 0 ]; do
  case "$1" in
    --voice) VOICE=1 ;;
    --ram-gb) shift; RAM="${1:-0}" ;;
    --no-open) OPEN=0 ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac; shift
done
case "$RAM" in ''|*[!0-9]*) echo "--ram-gb needs a number"; exit 2 ;; esac
DONE=()
note() { DONE+=("$1"); echo "• $1"; }

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
s.update(assistantName=os.environ["NAME"], userCallName=os.environ["CALL"], usageCheck=True, autoUpdate=False, stats=False,
         improve=False, improveAsked=True, support=False, talkMode="toggle", routing="cheapest", speak=True, greet=True)
with open(p, "w") as f: json.dump(s, f, indent=2)
os.chmod(p, 0o600)
PY
note "Wrote settings: ask before using your Claude plan, no telemetry, no background updates, press-to-talk, cheapest routing, speak and greet on"

# 3. voice
CB="$HOME/.local/share/chatterbox"; LA="$HOME/Library/LaunchAgents"; UID_N=$(id -u)
mkdir -p "$LA" "$HOME/.local/share/zuka"
if [ "$VOICE" = 1 ]; then
  command -v uv >/dev/null || { echo "The natural voice needs uv. Run: brew install uv   (or see https://docs.astral.sh/uv/ ), then run this again with --voice."; exit 1; }
  mkdir -p "$CB/voices"
  cp "$TEAM/voice/atticus_voice_server.py" "$TEAM/voice/atticus-say" "$CB/"; chmod +x "$CB/atticus-say"
  cp "$TEAM/voice/voices/"*.wav "$CB/voices/"
  [ -x "$CB/.venv/bin/python" ] || uv venv --python 3.11 "$CB/.venv"
  uv pip install --python "$CB/.venv/bin/python" -r "$TEAM/voice/requirements.txt"
  note "Set up the voice in $CB (Python 3.11 environment, requirements installed)"
  echo "Downloading the voice model once (about 4 GB, this takes a while)..."
  HF_HUB_OFFLINE=0 "$CB/.venv/bin/python" -I -c "from chatterbox.tts_turbo import ChatterboxTurboTTS as M; M.from_pretrained(device='cpu')"
  note "Downloaded the voice model (the voice works offline from now on)"
  if [ "$RAM" -ge 16 ]; then IDLE=0; echo 0 > "$CB/idle-min"; else IDLE=15; echo 15 > "$CB/idle-min"; fi
  if [ "$RAM" -ge 16 ]; then
    cat > "$LA/com.zuka.voice.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.zuka.voice</string>
<key>ProgramArguments</key><array><string>$CB/.venv/bin/python</string><string>-I</string><string>$CB/atticus_voice_server.py</string></array>
<key>EnvironmentVariables</key><dict><key>ATTICUS_VOICE_IDLE_MIN</key><string>0</string><key>TQDM_DISABLE</key><string>1</string><key>PYTHONWARNINGS</key><string>ignore</string></dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
<key>Nice</key><integer>5</integer>
<key>StandardErrorPath</key><string>$HOME/.config/atticus/voice.log</string>
</dict></plist>
P
    launchctl bootout "gui/$UID_N/com.zuka.voice" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_N" "$LA/com.zuka.voice.plist"
    note "Started the voice at login and kept it loaded (16 GB or more)"
  else
    launchctl bootout "gui/$UID_N/com.zuka.voice" 2>/dev/null || true
    rm -f "$LA/com.zuka.voice.plist"
    # start it now (in the background) so the greetings can be recorded; it unloads itself after 15 idle minutes
    [ -S "$CB/voice.sock" ] || ( ATTICUS_VOICE_IDLE_MIN=15 TQDM_DISABLE=1 nohup "$CB/.venv/bin/python" -I "$CB/atticus_voice_server.py" >>"$HOME/.config/atticus/voice.log" 2>&1 & )
    note "Voice starts when needed and unloads after 15 idle minutes (not started at login)"
  fi
  for _ in $(seq 1 90); do [ -S "$CB/voice.sock" ] && break; sleep 2; done
  if [ -S "$CB/voice.sock" ]; then
    python3 -I "$TEAM/greetings/make-greetings.py" && note "Recorded the time-of-day greetings" || note "Greetings were skipped (see message above)"
  else
    note "The voice server did not start in time; greetings skipped (run team/greetings/make-greetings.py later)"
  fi
else
  note "Using the free Mac voice (run again with --voice for the natural voice)"
fi

# 4. check-ins (spoken hellos at set times, free, weekdays)
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

echo; echo "All done. What I did:"; for d in "${DONE[@]}"; do echo "  - $d"; done
if [ "$OPEN" = 1 ]; then open "$HOME/Applications/Atticus.app"; echo "Opened $NAME. Its setup window walks you through the permissions."; fi
