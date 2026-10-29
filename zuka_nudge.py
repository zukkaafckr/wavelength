"""Zuka's nudges, all free (no Claude, no network): speak up when a Claude chat has been waiting for the owner's answer.

Reads the Claude desktop app's session sidebar through the accessibility tree (zuka_apps.hands_read: read-only, never clicks, never focuses the app)
and finds sessions whose name ends with "Awaiting input". A LaunchAgent (install_nudge) runs `python3 zuka_nudge.py --run` every 2 minutes.
Quiet unless the person is at the Mac (HID idle under 10 min) and the Claude app is NOT the frontmost app (they are probably in it).
First nudge once a chat has waited 3 minutes, again every 10 minutes, at most 4 times per chat; a chat that stops waiting is forgotten.
A generate press Zuka is still asking about (generate-pending.json, unexpired) or a pending message send is never nudged: Zuka's own flow asks those.
`--dry-run` prints what would be said instead of speaking or notifying.
"""
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # `python3 -I` drops the script folder
import zuka_apps as apps  # noqa: E402

STATE = os.path.expanduser('~/.config/atticus/nudge.json')
GENERATE_FILE = os.path.expanduser('~/.config/atticus/generate-pending.json')
SEND_FILE = os.path.expanduser('~/.config/atticus/send-pending.json')
SAY = os.path.expanduser('~/.local/share/chatterbox/atticus-say')
FIRST_AFTER = 180      # seconds a chat waits before the first nudge
REPEAT_EVERY = 600
MAX_NUDGES = 4
AT_MAC_SECS = 600
_AWAITING = ' Awaiting input'
GENERATE_KEY = 'Zuka generate request'   # state key for a generate press whose spoken-yes window ran out unanswered


# ---------------------------------------------------------------- reading
def parse_awaiting(text):
    """Chat titles whose sidebar row reads '<title> Awaiting input' (the row's own accessible name), in order, without repeats."""
    out = []
    for line in (text or '').splitlines():
        line = line.strip()
        if line.endswith(_AWAITING):
            title = line[:-len(_AWAITING)].strip()
            if title and title not in out:
                out.append(title)
    return out


def short_title(title, words=6):
    w = title.split()
    return ' '.join(w[:words])


def read_awaiting():
    """Titles awaiting input in the Claude app, or None when the app can't be read (hands read never starts or focuses it)."""
    for _ in range(3):   # the accessibility read fails now and then (app busy); a failed read is not "nobody is waiting"
        d = apps.hands_read('Claude', 3)
        if d:
            return parse_awaiting(d['text'])
        time.sleep(1)
    return None


def idle_seconds():
    """Seconds since the last key or mouse touch (same ioreg HIDIdleTime method as the hiring check); None when unreadable."""
    r = apps._run(['/usr/sbin/ioreg', '-c', 'IOHIDSystem'], 5)
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', r.stdout or '')
    return int(m.group(1)) // 1_000_000_000 if m else None


# ---------------------------------------------------------------- state and timing
def load_state(path=None):
    try:
        with open(path or STATE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state, path=None):
    path = path or STATE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(state, f)
    except OSError:
        pass


def step(state, waiting, now):
    """One tick of the timing rules. -> (new state, titles to nudge now). state: {title: {'first': t, 'count': n, 'last': t}}."""
    new, due = {}, []
    for title in waiting:
        e = dict(state.get(title) or {'first': now, 'count': 0, 'last': 0})
        if e['count'] == 0:
            if now - e['first'] >= FIRST_AFTER:
                due.append(title)
        elif e['count'] < MAX_NUDGES and now - e['last'] >= REPEAT_EVERY:
            due.append(title)
        if title in due:
            e['count'] += 1
            e['last'] = now
        new[title] = e
    return new, due   # chats no longer awaiting are simply not carried over


def _read_json(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def zuka_waiting(now, generate_file=None, send_file=None):
    """Zuka's own pending items that need a nudge: [] when nothing, or while Zuka is still asking (unexpired generate, pending send).
    A generate request whose 2 minutes ran out unanswered shows up as one waiting item."""
    if _read_json(send_file or SEND_FILE) is not None:
        return []
    g = _read_json(generate_file or GENERATE_FILE)
    if g and now > g.get('expires', 0):
        return [GENERATE_KEY]
    return []


# ---------------------------------------------------------------- one run
def run(now=None, at_mac=None, frontmost=None, read=None, speak=None, notify=None, state_path=None,
        generate_file=None, send_file=None):
    """One check. Every side effect is injectable. -> the spoken lines (possibly empty)."""
    now = time.time() if now is None else now
    idle = at_mac if at_mac is not None else idle_seconds()
    if idle is None or idle >= AT_MAC_SECS:
        return []
    front = frontmost if frontmost is not None else apps.frontmost()
    if front == 'Claude':
        return []
    reader = read or read_awaiting
    titles = reader()
    state = load_state(state_path)
    if titles is not None and any(k != GENERATE_KEY and k not in titles for k in state):
        titles = reader()   # a tracked chat looks gone: read again before forgetting it (the accessibility read is sometimes partial)
    if titles is None:
        titles = []
        state = {k: v for k, v in state.items() if k == GENERATE_KEY}   # Claude not readable: forget chats, keep Zuka's item
    waiting = list(titles) + zuka_waiting(now, generate_file, send_file)
    state, due = step(state, waiting, now)
    save_state(state, state_path)
    lines = []
    for t in due:
        lines.append("Zuka's generate request, is still waiting for your answer." if t == GENERATE_KEY
                     else f"{short_title(t)}, is waiting for your answer.")
    if lines:
        (speak or _speak)(' '.join(lines))
        (notify or _notify)('; '.join(lines))
    return lines


def _speak(line):
    if os.access(SAY, os.X_OK):
        apps._run([SAY, line], 60)


def _notify(line):
    apps._run(['/usr/bin/osascript', '-e', 'on run argv', '-e', 'display notification (item 1 of argv) with title "Waiting for you"', '-e', 'end run', line], 10)


# ---------------------------------------------------------------- LaunchAgent
def install_nudge(seconds=120, home=None):
    """Write ~/Library/LaunchAgents/com.wavelength.nudge.plist (every `seconds`, not at load) and load it with launchctl bootstrap. -> the plist path."""
    home = home or os.path.expanduser('~')
    plist = {'Label': 'com.wavelength.nudge',
             'ProgramArguments': ['/usr/bin/python3', str(Path(__file__).resolve()), '--run'],
             'StartInterval': seconds, 'RunAtLoad': False}
    path = Path(home) / 'Library/LaunchAgents/com.wavelength.nudge.plist'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as f:
        plistlib.dump(plist, f)
    uid = str(os.getuid())
    subprocess.run(['launchctl', 'bootout', f'gui/{uid}/com.wavelength.nudge'], capture_output=True)   # reload cleanly if already loaded
    subprocess.run(['launchctl', 'bootstrap', f'gui/{uid}', str(path)], capture_output=True)
    return str(path)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--install' in argv:
        print(install_nudge())
        return 0
    if '--dry-run' in argv:
        # fake clock: tick once to record first-seen, again 200 s later; nothing is spoken, gating is skipped, the real state file is untouched
        import tempfile
        st = os.path.join(tempfile.mkdtemp(), 'nudge.json')
        titles = read_awaiting()
        print('awaiting input:', titles)
        t0 = time.time()
        for t in (t0, t0 + FIRST_AFTER + 20):
            run(now=t, at_mac=0, frontmost='', read=lambda: titles, state_path=st,
                speak=lambda l: print('WOULD SAY:', l), notify=lambda l: print('WOULD NOTIFY:', l))
        return 0
    if '--run' in argv:
        run()
        return 0
    print('usage: zuka_nudge.py --run | --install | --dry-run')
    return 1


if __name__ == '__main__':
    sys.exit(main())
