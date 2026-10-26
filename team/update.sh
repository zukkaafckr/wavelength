#!/bin/bash
# Get the latest Wavelength from the team repo and rebuild, keeping your assistant's name, what it calls you and its voice.
#   bash team/update.sh          update now (asks nothing; it is safe to run any time)
#   bash team/update.sh --auto   what the hourly updater runs: only while you are away from the Mac, quietly
# Every update is tested on a copy first; if a test fails, your current version stays as it is.
set -e
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
REPO=$(cd "$(dirname "$0")/.." && pwd); cd "$REPO"
AUTO=0; [ "$1" = "--auto" ] && AUTO=1
LOG="$HOME/.config/atticus/update.log"; mkdir -p "$(dirname "$LOG")"
say_() { echo "$(date '+%F %T') $*" >> "$LOG"; [ $AUTO = 1 ] || echo "$*"; }

if [ $AUTO = 1 ]; then   # never rebuild (it restarts the app) while someone is using the Mac
  idle=$(ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print int($NF/1000000000); exit}')
  [ "${idle:-0}" -ge 600 ] || exit 0
fi
git fetch -q origin main 2>>"$LOG" || { say_ "Couldn't reach GitHub (offline or not signed in: run gh auth login, then gh auth setup-git)."; exit 1; }
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && { say_ "Already up to date."; exit 0; }

MARK=team/.personalized
NAME=$(sed -n 's/^name=\(.*\) call=.*/\1/p' "$MARK" 2>/dev/null); CALL=$(sed -n 's/^name=.* call=\(.*\)$/\1/p' "$MARK" 2>/dev/null)
[ -n "$NAME" ] && [ -n "$CALL" ] || { say_ "This copy was never personalised (team/personalize.py). Not updating."; exit 1; }

# 1. test the new version on a copy, with your names
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
git archive origin/main | tar -x -C "$TMP"
python3 "$TMP/team/personalize.py" "$NAME" "$CALL" >/dev/null
( cd "$TMP" && ATTICUS_DIR=$(mktemp -d) python3 -m unittest tests.test_zuka tests.test_zuka_commands >>"$LOG" 2>&1 ) \
  || { say_ "The new version failed its checks, so I kept your current one. (Details: $LOG)"; exit 1; }

# 2. switch to it and put your names back
git reset -q --hard origin/main
rm -f "$MARK"; python3 team/personalize.py "$NAME" "$CALL" >/dev/null

[ -n "$WAVELENGTH_TEST" ] && { say_ "Test run: updated the files, skipped the voice and rebuild."; exit 0; }
# names now live in settings (older installs kept them only in team/.personalized): quit the app first, or it rewrites the file
osascript -e 'quit app id "com.atticus.app"' 2>/dev/null || true; for _ in $(seq 1 20); do pgrep -x Atticus >/dev/null || break; sleep 0.5; done
NAME="$NAME" CALL="$CALL" python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.config/atticus/settings.json")
try: s = json.load(open(p))
except (OSError, ValueError): s = {}
if s.get("assistantName") != os.environ["NAME"] or s.get("userCallName") != os.environ["CALL"]:
    s.update(assistantName=os.environ["NAME"], userCallName=os.environ["CALL"]); os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(s, open(p, "w"), indent=1)
PY
# 3. refresh the voice, check-ins and greeting recorder, then rebuild (this restarts the app)
CB="$HOME/.local/share/chatterbox"; Z="$HOME/.local/share/zuka"
if [ -d "$CB" ]; then cp team/voice/zuka_voice_light.py team/voice/atticus_voice_server.py team/voice/atticus-say "$CB/"; chmod +x "$CB/atticus-say"; fi
mkdir -p "$Z/greetings-maker"; cp team/greetings/make-greetings.py team/greetings/lines.json "$Z/greetings-maker/"
[ -f "$Z/zuka-checkin" ] && cp team/checkin/zuka-checkin "$Z/zuka-checkin" && chmod +x "$Z/zuka-checkin"
./build.sh >>"$LOG" 2>&1 || { say_ "The rebuild failed. (Details: $LOG)"; exit 1; }
launchctl kickstart -k "gui/$(id -u)/com.zuka.voice" 2>/dev/null || true
say_ "$NAME is updated to the latest version: $(git log -1 --format=%s)"
osascript -e "display notification \"Updated: $(git log -1 --format=%s | tr -d '\"')\" with title \"$NAME\"" 2>/dev/null || true
