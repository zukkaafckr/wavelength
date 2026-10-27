"""Zuka's wider set of free Mac commands: anything the Mac can do by itself never reaches Claude.

zuka_commands.handle() calls handle(t, raw) last, when none of its own commands matched.
t = normalised lowercase words, raw = what was said. Returns a short spoken reply, or None (then the person is asked before Claude is used).
Nothing destructive or outward happens here: no deleting, emptying the trash, restarting, sending or buying. Those only open or prepare, or return None.
"""
import json
import os
import random
import re
import shutil
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from html import unescape

import zuka_commands as zc


# ---------------------------------------------------------------- small helpers
def _c():
    """', J' (or '' when there is no call name) for the end of a sentence."""
    return zc.call_suffix()


def _done(what='Done'):
    return f"{what}{_c()}."


def _home():
    return os.path.expanduser('~')


def _q(s):
    """A string for inside an AppleScript literal."""
    return str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '" & linefeed & "')


def _se(body):
    """System Events script."""
    return 'tell application "System Events"\n' + body + '\nend tell'


def _front():
    return 'first application process whose frontmost is true'


def _epoch():
    return time.time()


def _now_utc():
    return datetime.now(timezone.utc)


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _today():
    return zc._now().date()


def _sh(args, timeout=8):
    """stdout of a shell command, '' on any failure."""
    try:
        r = zc._run(args, timeout)
        return (r.stdout or '').strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _cap(s):
    s = s.strip()
    return s if s != s.lower() else s[:1].upper() + s[1:]


_LEAD = re.compile(r"^(?:(?:hey|ok|okay|um+|uh+|zuka|please|kindly|just|now|so|and|then|also|go ahead and|"
                   r"(?:can|could|would|will) (?:you|u)(?: please)?|(?:i|we) (?:want|need|would like|d like|wanna|have) (?:you )?to|"
                   r"i want you to|i need you to|i would like you to|i wanna|lets|you can|you could|i d like you to)\b\s*)+")
_TRAIL = re.compile(r"(?:\s+(?:please|for me|right now|real quick|quickly|thanks|thank you|if you can|now))+$")


def _tidy(t):
    t = (t if isinstance(t, str) else '').lower().replace("'", ' ')
    t = re.sub(r'\bwi ?-? ?fi\b', 'wifi', t)
    t = re.sub(r'\be mail\b', 'email', t)
    t = re.sub(r'\bface time\b', 'facetime', t)
    t = re.sub(r'\bwhats app\b', 'whatsapp', t)
    t = re.sub(r'\b(what|that|how|where|who)\s?s\b', r'\1 is', t)   # "what's" -> "what is"
    t = re.sub(r'\b(\w+) s\b', r'\1', t)       # "mac's" -> "mac s" -> "mac"
    t = re.sub(r'\s+', ' ', t).strip()
    for _ in range(3):
        t = _TRAIL.sub('', _LEAD.sub('', t)).strip()
    return t


def _on_off(s):
    """True/False from the words around a switch ("turn on", "disable", "off"), else None."""
    on = re.search(r'\b(on|enable|enabled|activate|start|open up|engage)\b', s)
    off = re.search(r'\b(off|disable|disabled|deactivate|stop|end|cancel|exit)\b', s)
    if on and not off: return True
    if off and not on: return False
    return None


def _clip(s, n=200):
    s = ' '.join(str(s).split())
    return s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + '...'


# ---------------------------------------------------------------- apps and windows
_MINIMIZE = re.compile(r"^minimi[sz]e(?: (?:this|the|my|that|current|front))*(?: window| app)?$")
_EXIT_FULL = re.compile(r"^(?:exit|leave|get out of|come out of|stop) full ?screen(?: mode)?$|^(?:un ?full ?screen)(?: this| the window| it)?$")
_CLOSE_WIN = re.compile(r"^close (?:this|the|my|that|current|front)(?: current| front)? window$")
_NEXT_WIN = re.compile(r"^(next|previous|last) window$|^switch (?:to the )?(next|previous) window$|^cycle (?:through )?windows$")
_HIDE_OTHERS = re.compile(r"^hide (?:all )?(?:the )?(?:other|others|everything else)(?: windows| apps| applications)?$|^hide all other (?:windows|apps|applications)$")
_HIDE_ALL = re.compile(r"^(?:show|go to) (?:me )?(?:the |my )?desktop$|^(?:minimi[sz]e|hide) (?:all|every|everything)(?: the| my)?(?: windows| apps| applications)?$|^clear (?:the |my )?screen$")
_HIDE_THIS = re.compile(r"^hide (?:this|the front|the current|current|front)(?: app| application)?$")
_HIDE_APP = re.compile(r"^hide (?P<a>[a-z0-9][a-z0-9 ]*?)(?: app| application| window| windows)?$")
_QUIT_ALL = re.compile(r"^(?:quit|close|exit) (?:all|every|everything)(?: of)?(?: the)?(?: other| open| running)?(?: apps?| applications?| programs?)?(?: other than| except(?: for)?| but| apart from| besides| aside from) (?P<k>.+)$")


def _apps_and_windows(s):
    if _MINIMIZE.match(s):
        zc._osa(_se(f'set p to {_front()}\ntry\nset value of attribute "AXMinimized" of window 1 of p to true\nend try'))
        return f"Minimized{_c()}."
    if _EXIT_FULL.match(s):
        zc._osa(_se(f'set p to {_front()}\ntry\nset value of attribute "AXFullScreen" of window 1 of p to false\nend try'))
        return f"Out of full screen{_c()}."
    if _CLOSE_WIN.match(s):
        zc._osa(_se('keystroke "w" using command down'))
        return _done('Closed it')
    m = _NEXT_WIN.match(s)
    if m:
        back = 'previous' in s or 'last' in s
        zc._osa(_se('key code 50' + (' using {command down, shift down}' if back else ' using command down')))
        return _done('Switched window')
    if _HIDE_OTHERS.match(s):
        zc._osa(_se('keystroke "h" using {command down, option down}'))
        return _done('Hid the rest')
    if _HIDE_ALL.match(s):
        zc._osa(_se('set visible of every process whose visible is true and background only is false and name is not "Finder" to false'))
        return f"Cleared the screen{_c()}."
    if _HIDE_THIS.match(s):
        zc._osa(_se(f'set visible of ({_front()}) to false'))
        return _done('Hidden')
    m = _QUIT_ALL.match(s)
    if m:
        return _quit_all_but(m.group('k'))
    m = _HIDE_APP.match(s)
    if m and not re.search(r'\b(this|that|it|them|all|everything|desktop|sidebar|toolbar|dock|menu|cursor|mouse)\b', m.group('a')):
        want = m.group('a').strip()
        for n, _ in zc._running_apps():
            if n.lower() == want or want in n.lower().split() or n.lower().startswith(want + ' '):
                zc._osa(_se(f'set visible of process "{_q(n)}" to false'))
                return f"Hid {n}{_c()}."
        if _app_exists(want.title()) or _app_exists(want):
            return f"{want.title()} isn't running{_c()}."
    return None


def _quit_all_but(keep_words):
    words = [w.strip() for w in re.split(r',| and | or ', keep_words) if w.strip()]
    words = [re.sub(r'^(?:the )?', '', w) for w in words]
    if not words or len(words) > 6:
        return None
    apps = [(n, b) for n, b in zc._running_apps() if b != 'missing value']
    keep_ids = set(zc.KEEP_IDS)
    for w in words:   # every name must be an app that is running, else do nothing
        hit = [b for n, b in apps if w == n.lower() or w in n.lower().split() or (len(w) > 3 and w in n.lower())]
        if not hit:
            return None
        keep_ids |= set(hit)
    keepwf = {k.lower() for k in zc._workflow().get('keepOpen', [])}
    targets = [(n, b) for n, b in apps if b not in keep_ids and n.lower() not in keepwf]
    if not targets:
        return f"Nothing else is open{_c()}."
    for n, b in targets:
        zc._osa(f'ignoring application responses\ntell application id "{_q(b)}" to quit\nend ignoring')   # a polite quit, never forced
    left = targets
    for _ in range(12):
        running = {b for _, b in zc._running_apps()}
        left = [(n, b) for n, b in targets if b in running]
        if not left: break
        time.sleep(0.5)
    return zc._close_reply([n for n, b in targets if (n, b) not in left], [n for n, _ in left])


# ---------------------------------------------------------------- system
_BRIGHT = re.compile(r"\b(brightness|brighter|dimmer|dim the (?:screen|display)|screen up|screen down)\b")
_BRIGHT_SET = re.compile(r"(?:set|put|change|make|turn)(?: the)?(?: screen| display)? brightness (?:to|at) (\d{1,3})(?: percent)?$|brightness (?:to|at) (\d{1,3})(?: percent)?$")
_BRIGHT_DIR = re.compile(r"^(?:(?:turn|bring|put|crank|make|raise|lower|increase|decrease|reduce) )?(?:the )?(?:screen |display )?(?:brightness |it )?(?P<d>up|down|higher|lower|brighter|dimmer)(?: a bit| a little| a lot)?$|"
                         r"^(?:(?:turn|bring|put|crank|make|raise|lower|increase|decrease|reduce|dim) )(?:the )?(?:screen |display )?(?:brightness)(?: (?P<d2>up|down|higher|lower))?(?: a bit| a little| a lot)?$|"
                         r"^(?:make )(?:the )?(?:screen|display) (?P<d3>brighter|dimmer)(?: a bit| a little| a lot)?$|^dim(?: the)? (?:screen|display)$|^brighten(?: the)? (?:screen|display)$|"
                         r"^(?:increase|raise|decrease|lower|reduce) (?:the )?(?:screen |display )?brightness$")
_BRIGHT_MAX = re.compile(r"^(?:max(?:imum)?|full) (?:screen |display )?brightness$|^(?:brightness|screen|display) (?:to )?(?:max|full|maximum)$|^(?:turn|put|set) (?:the )?brightness (?:to )?(?:max|full|maximum)$")
_BRIGHT_MIN = re.compile(r"^(?:min(?:imum)?|lowest) (?:screen |display )?brightness$|^(?:turn|put|set) (?:the )?brightness (?:to )?(?:min|minimum|lowest|zero)$")


def _brightness(s):
    if not _BRIGHT.search(s) and not re.match(r'^(?:dim|brighten)\b', s):
        return None
    keys = lambda key, n: f'repeat {n} times\nkey code {key}\ndelay 0.04\nend repeat\n'
    if _BRIGHT_MAX.match(s):
        zc._osa(_se(keys(144, 16)))
        return f"Brightness at max{_c()}."
    if _BRIGHT_MIN.match(s):
        zc._osa(_se(keys(145, 16)))
        return f"Brightness at the lowest{_c()}."
    m = _BRIGHT_SET.search(s)
    if m:
        pct = max(0, min(100, int(m.group(1) or m.group(2))))
        zc._osa(_se(keys(145, 16) + keys(144, round(pct * 16 / 100))))
        return f"Brightness at about {pct} percent{_c()}."
    m = _BRIGHT_DIR.match(s)
    if not m:
        return None
    word = ' '.join(x for x in (m.groupdict().get('d'), m.groupdict().get('d2'), m.groupdict().get('d3')) if x) or s
    up = bool(re.search(r'\b(up|higher|brighter|brighten|increase|raise)\b', word if m.groupdict().get('d') or m.groupdict().get('d2') or m.groupdict().get('d3') else s))
    if re.match(r'^dim\b', s) or re.search(r'\b(dimmer|lower|decrease|reduce|down)\b', s): up = False
    zc._osa(_se(keys(144 if up else 145, 3)))
    return f"Brightness {'up' if up else 'down'}{_c()}."


_DARK = re.compile(r"^(?:(?:turn|go|change|set|put|use|enable|activate|flip)(?: it| the mac| my mac| the screen| everything)?(?: on| to| into)? |switch (?:it |the mac |my mac )?(?:to|into) )?(?P<m>dark|light) (?:mode|theme|appearance)(?: on)?$|^(?P<m6>dark|light) mode (?P<o6>on|off)$|"
                   r"^(?:turn|set|put) (?P<o>on|off) (?:the )?(?P<m2>dark|light) (?:mode|theme)$|^(?:turn|set|put) (?P<m3>dark|light) (?:mode|theme) (?P<o3>on|off)$|"
                   r"^(?:disable|stop) (?P<m4>dark|light) (?:mode|theme)$|^(?P<t>toggle|flip|switch)(?: the)?(?: dark mode| appearance| theme| between dark and light(?: mode)?)$|^(?:enable) (?P<m5>dark|light) (?:mode|theme)$")


def _dark_mode(s):
    m = _DARK.match(s)
    if not m:
        return None
    g = m.groupdict()
    if g.get('t'):
        val, word = 'not dark mode', 'Flipped the appearance'
    else:
        mode = g.get('m') or g.get('m6') or g.get('m2') or g.get('m3') or g.get('m4') or g.get('m5')
        on = True
        if g.get('o') == 'off' or g.get('o3') == 'off' or g.get('o6') == 'off' or g.get('m4'):
            on = False
        want_dark = (mode == 'dark') == on
        val, word = ('true' if want_dark else 'false'), ('Dark mode on' if want_dark else 'Light mode on')
    zc._osa(_se('tell appearance preferences to set dark mode to ' + val))
    return f"{word}{_c()}."


_DND = re.compile(r"\b(?:do not disturb|dnd|focus(?: mode)?|silent mode|quiet mode)\b")


def _focus(s):
    if not _DND.search(s) or not re.match(r"^(?:turn|switch|set|put|enable|disable|activate|deactivate|start|stop|end|go|toggle|cancel|exit)\b|^(?:do not disturb|dnd|focus)(?: mode)? (?:on|off)$|^(?:do not disturb|dnd|focus)$", s):
        return None
    if re.search(r'\b(timer|session|music|playlist|app|on (?:the )?(?:homework|work)|my work)\b', s):
        return None
    on = _on_off(s)
    if on is None and not re.search(r'\btoggle\b', s):
        on = True
    name = _shortcut_for(on)
    if name:
        zc._run(['shortcuts', 'run', name], 15)
        return f"{'Do Not Disturb on' if on else 'Do Not Disturb off'}{_c()}."
    try:
        zc._osa(_se('tell process "ControlCenter" to click menu bar item "Control Center" of menu bar 1'), 6)
        return f"I can't flip Focus by myself yet{_c()}. I opened Control Center, tap Focus there."
    except Exception:
        zc._run(['open', 'x-apple.systempreferences:com.apple.Focus-Settings.extension'], 8)
        return f"I can't flip Focus by myself yet{_c()}. I opened the Focus settings for you."


def _shortcut_for(on):
    """A Shortcuts shortcut that turns Do Not Disturb / Focus on or off, if the person made one."""
    names = [n.strip() for n in (_sh(['shortcuts', 'list'], 8)).splitlines() if n.strip()]
    for n in names:
        low = n.lower()
        if re.search(r'do not disturb|dnd|focus', low):
            if on is True and re.search(r'\bon\b|enable|start', low): return n
            if on is False and re.search(r'\boff\b|disable|stop|end', low): return n
    return None


def _wifi_iface():
    out = _sh(['networksetup', '-listallhardwareports'], 6)
    m = re.search(r'Hardware Port: (?:Wi-Fi|AirPort)\s*\nDevice: (\w+)', out)
    return m.group(1) if m else 'en0'


_WIFI_SW = re.compile(r"^(?:turn|switch|set|put|shut|power|enable|disable)\b.*\bwifi\b|^wifi (?:on|off)$|^(?:turn|switch) wifi (?:on|off)$")
_WIFI_Q = re.compile(r"^is (?:my )?(?:the )?wifi (?:on|off|enabled|turned on|working)\??$|^(?:my |the )?wifi (?:status|state|working)\??$")   # bare "wifi off" is a switch
_WIFI_NAME = re.compile(r"^(?:what|which)(?: wifi| network)?(?: network)? (?:am i|are we|is my mac|is this mac)(?: connected| on| using| joined)?(?: to| on)?(?: wifi| network| which wifi| which network)?$|"
                        r"^(?:what is|what|which) (?:my |the )?(?:wifi|network)(?: name| network)?(?: i m connected to| am i on| am i connected to| i am on| is this)?$|^(?:what|which) wifi(?: am i)?(?: on| connected to| connected)?$|"
                        r"^(?:name of (?:my |the )?wifi|current wifi|wifi name|network name|ssid)$|^what is the name of (?:my |the |this )?wifi$|^which wifi (?:am i|is my mac) (?:on|connected to|using)$|^what wifi am i (?:connected to|on|using)$")


def _wifi(s):
    if _WIFI_NAME.match(s):
        return _wifi_name()
    if _WIFI_Q.match(s):
        out = _sh(['networksetup', '-getairportpower', _wifi_iface()], 6)
        m = re.search(r'\b(On|Off)\b', out)
        return f"Wi-Fi is {m.group(1).lower()}{_c()}." if m else None
    if _WIFI_SW.match(s) and 'wifi' in s:
        on = _on_off(s)
        if on is None:
            return None
        zc._run(['networksetup', '-setairportpower', _wifi_iface(), 'on' if on else 'off'], 10)
        return f"Wi-Fi {'on' if on else 'off'}{_c()}."
    return None


def _wifi_name():
    iface = _wifi_iface()
    out = _sh(['networksetup', '-getairportnetwork', iface], 6)
    m = re.search(r'Current (?:Wi-Fi|AirPort) Network:\s*(.+)$', out, re.M)
    name = m.group(1).strip() if m else ''
    if not name or 'redacted' in name.lower():
        summary = _sh(['ipconfig', 'getsummary', iface], 6)
        m = re.search(r'^\s*SSID\s*:\s*(.+)$', summary, re.M)
        name = m.group(1).strip() if m else ''
    if name and 'redacted' not in name.lower():
        return f"You're on {name}{_c()}."
    if _sh(['ipconfig', 'getifaddr', iface], 4):
        return f"You're on Wi-Fi, but macOS hides the network name from me{_c()}."
    return f"You're not on Wi-Fi right now{_c()}."


def _blueutil():
    return shutil.which('blueutil') or next((p for p in ('/opt/homebrew/bin/blueutil', '/usr/local/bin/blueutil') if os.path.exists(p)), None)


_BT_SW = re.compile(r"^(?:turn|switch|set|put|power|enable|disable)\b.*\bbluetooth\b|^bluetooth (?:on|off)$")
_BT_Q = re.compile(r"^is (?:my )?(?:the )?bluetooth (?:on|off|enabled|turned on|status|state)\??$|^(?:my |the )?bluetooth (?:status|state)\??$")   # bare "bluetooth on" is a switch


def _bluetooth(s):
    if _BT_Q.match(s):
        out = _sh(['system_profiler', 'SPBluetoothDataType'], 20)
        m = re.search(r'(?:Bluetooth Power|State):\s*(On|Off)', out, re.I)
        return f"Bluetooth is {m.group(1).lower()}{_c()}." if m else None
    if _BT_SW.match(s) and 'bluetooth' in s:
        on = _on_off(s)
        if on is None:
            return None
        bu = _blueutil()
        if bu:
            zc._run([bu, '-p', '1' if on else '0'], 10)
            return f"Bluetooth {'on' if on else 'off'}{_c()}."
        zc._run(['open', 'x-apple.systempreferences:com.apple.BluetoothSettings'], 8)
        return f"I can't switch Bluetooth by myself without blueutil{_c()}. I opened the Bluetooth settings, flip it there."
    return None


_BATTERY = re.compile(r"\b(?:battery|charge|charging)\b")
_BATT_Q = re.compile(r"^(?:what is |how much )?(?:my |the )?(?:battery|charge)(?: percentage| percent| level| life| status| left| remaining)*(?: do i have)?(?: is left| left| remaining| do i have left)?$|"
                     r"^how much (?:battery|charge)(?: life| power)?(?: do i have| is there| is left| have i got| do we have)?(?: left| remaining)?$|^how(?: much)? is my battery(?: doing)?$|"
                     r"^(?:is|are) (?:my|the) (?:mac|macbook|laptop|computer)(?: currently)? (?:charging|plugged in|on battery)$|^(?:is|am) (?:it|i) (?:charging|plugged in)$|^battery(?: percentage| percent| level| status)?$|"
                     r"^how long (?:will|does) (?:my )?battery last$|^how long until (?:my )?(?:mac|battery)(?: is)? (?:fully )?charged$|^(?:what is|what) (?:my )?battery (?:at|on)$|^check (?:my |the )?battery(?: level| percentage)?$|^how(?: much)? (?:power|juice) (?:do i have )?left$")


def _battery(s):
    if not _BATTERY.search(s) or not _BATT_Q.match(s):
        return None
    out = _sh(['pmset', '-g', 'batt'], 6)
    m = re.search(r'(\d{1,3})%;\s*([A-Za-z ]+?)(?:;\s*(\d+:\d+) remaining|;|\s*$)', out, re.M)
    if not m:
        return f"This Mac has no battery{_c()}." if out and 'InternalBattery' not in out else None
    pct, state, left = int(m.group(1)), m.group(2).strip().lower(), m.group(3)
    plugged = 'AC Power' in out
    if re.search(r'charging|finishing', state) and 'dis' not in state:
        lead = f"Battery's at {pct} percent and charging"
    elif 'charged' in state:
        lead = f"Battery's at {pct} percent and fully charged"
    elif plugged:
        lead = f"Battery's at {pct} percent, plugged in"
    else:
        lead = f"Battery's at {pct} percent, on battery"
    if re.search(r'\bcharging\b', s) or re.search(r'plugged in', s):
        lead = ("Yes, " if (plugged or ('charging' in state and 'dis' not in state)) else "No, ") + (f"it's {'charging' if 'charging' in state and 'dis' not in state else 'plugged in' if plugged else 'on battery'} at {pct} percent")
    if left and left != '0:00':
        h, mnt = (int(x) for x in left.split(':'))
        bits = (f"{h} hour{'s' if h != 1 else ''}" if h else '') + (' ' if h and mnt else '') + (f"{mnt} minutes" if mnt else '')
        lead += f", about {bits} {'to full' if 'charging' in state and 'dis' not in state else 'left'}"
    return lead + f"{_c()}."


_STORAGE = re.compile(r"^how much (?:storage|disk space|space|disk|hard drive space|free space|room)(?: do i have| have i got| do we have| is there)?(?: left| free| available| remaining)?(?: on (?:my|the) (?:mac|computer|laptop|disk|drive|hard drive))?$|"
                      r"^(?:how much|what) (?:storage|disk space|space)(?: is| do i have| have i got)?(?: left| free| available)(?: on (?:my|the) (?:mac|computer|laptop|disk|drive))?$|^(?:check |show )?(?:my )?(?:disk|storage)(?: space| usage)?$|"
                      r"^(?:am i|are we) (?:low|running low|out) (?:on|of) (?:storage|disk space|space)$|^how full is my (?:disk|drive|mac|storage)$|^how much free (?:storage|space|disk space)(?: do i have)?(?: left)?$|^storage(?: space| left)?$")


def _unit_say(v):
    m = re.match(r'^([\d.]+)\s*([KMGTP]?)i?B?$', v.strip())
    if not m:
        return v
    n = float(m.group(1))
    n = int(n) if n == int(n) else n
    unit = {'K': 'kilobytes', 'M': 'megabytes', 'G': 'gigabytes', 'T': 'terabytes', 'P': 'petabytes', '': 'bytes'}[m.group(2)]
    return f"{n} {unit}"


def _storage(s):
    if not _STORAGE.match(s):
        return None
    out = _sh(['df', '-H', '/'], 6).splitlines()
    if len(out) < 2:
        return None
    p = out[1].split()
    if len(p) < 4:
        return None
    return f"You have {_unit_say(p[3])} free out of {_unit_say(p[1])}{_c()}."


_IP = re.compile(r"^(?:what is|what|show|tell me|get|give me) (?:my |the )?(?:local |lan |internal |private |current )?ip(?: address)?(?: is)?(?: of this mac)?$|^(?:my )?(?:local )?ip(?: address)?$|^what is my ip$")
_IP_PUB = re.compile(r"^(?:what is|what|show|tell me|get|give me) (?:my |the )?(?:public|external|outside|internet|wan) ip(?: address)?$|^(?:my )?(?:public|external) ip(?: address)?$|^what ip (?:do|does) (?:the )?(?:internet|websites?) see$")


def _ip(s):
    if _IP_PUB.match(s):
        ip = (zc._get_text('https://api.ipify.org', 5) or '').strip()
        return f"Your public IP is {ip}{_c()}." if re.fullmatch(r'[0-9a-fA-F:.]{7,45}', ip) else None
    if _IP.match(s):
        for iface in dict.fromkeys([_wifi_iface(), 'en0', 'en1']):
            ip = _sh(['ipconfig', 'getifaddr', iface], 4)
            if ip:
                return f"Your local IP is {ip}{_c()}."
        return f"You're not connected to a network right now{_c()}."
    return None


_UPTIME = re.compile(r"^how long (?:has|have) (?:my |the |this )?(?:mac|computer|laptop|macbook|system|machine)(?: been| has been)?(?: on| up| running| awake| switched on| turned on)(?: for)?$|^(?:what is|what|show|check) (?:my |the |this )?(?:mac )?uptime$|^uptime$|^when did (?:my |the )?(?:mac|computer|laptop) (?:last )?(?:start|boot|restart|turn on)(?: up)?$|^how long since (?:my |the )?(?:mac|computer|laptop) (?:last )?(?:restarted|rebooted|booted|started)$")


def _span(secs):
    secs = int(secs)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    mn = rem // 60
    parts = []
    if d: parts.append(f"{d} day{'s' if d != 1 else ''}")
    if h: parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if not d and mn: parts.append(f"{mn} minute{'s' if mn != 1 else ''}")
    return ' and '.join(parts) if parts else 'under a minute'


def _uptime(s):
    if not _UPTIME.match(s):
        return None
    m = re.search(r'sec\s*=\s*(\d+)', _sh(['sysctl', '-n', 'kern.boottime'], 4))
    if not m:
        return None
    return f"Your Mac has been on for {_span(_epoch() - int(m.group(1)))}{_c()}."


_SLEEP = re.compile(r"^(?:put|send|set) (?:the |my |this )?(?:mac|macbook|computer|laptop|system|machine)(?: to| into)? sleep$|^sleep (?:the |my |this )?(?:mac|macbook|computer|laptop|system|machine)$|^(?:make|let) (?:the |my |this )?(?:mac|macbook|computer|laptop) (?:go to )?sleep$|^(?:mac|computer|laptop|macbook) sleep$")
_NOT_NOW = re.compile(r"^(?:empty|clear|clean out|clean|delete everything in|delete) (?:the |my )?(?:trash|bin|recycle bin|downloads(?: folder)?)$|^(?:restart|reboot|shut ?down|power off|power down|turn off)(?: the| my| this)?(?: mac| macbook| computer| laptop| system| machine)?$|^(?:log out|sign out|logout)$")


def _awake(s):
    m = re.match(r"^(?:keep|stop) (?:my |the |this )?(?:mac|macbook|computer|laptop|screen|display|system)(?: from sleeping| awake| on| from going to sleep)(?: for (?P<n>\d+(?:\.\d+)?) (?P<u>hours?|hrs?|minutes?|mins?))?$|^(?:stop|cancel|end|disable) keeping (?:my |the |this )?(?:mac|macbook|computer|laptop|screen|display) awake$|^(?:let|allow) (?:my |the |this )?(?:mac|computer|laptop|macbook) (?:to )?sleep(?: again)?$|^(?:stay|keep) awake$", s)
    if not m:
        return None
    if re.match(r"^(?:stop|cancel|end|disable|let|allow)", s):
        zc._run(['pkill', '-x', 'caffeinate'], 4)
        return f"Okay, your Mac can sleep again{_c()}."
    secs = 3600
    if m.groupdict().get('n'):
        secs = int(float(m.group('n')) * (3600 if m.group('u').startswith('h') else 60))
    zc._spawn(['caffeinate', '-d', '-i', '-t', str(secs)])
    return f"Keeping your Mac awake for {zc._human_dur(secs)}{_c()}."


_MIC = re.compile(r"^(?:mute|silence|turn off|switch off|disable) (?:my |the )?(?:mic|microphone|mike|input)$|^(?:unmute|turn on|switch on|enable) (?:my |the )?(?:mic|microphone|mike|input)$|^(?:mic|microphone) (?:off|on|mute|unmute)$")
_NIGHT = re.compile(r"^(?:turn|switch|set|put)(?: on| off)? night shift(?: on| off)?$|^(?:enable|disable|toggle) night shift$|^night shift(?: on| off)?$|^(?:turn|switch) (?:on|off) the night shift$")
_HIDDEN = re.compile(r"^(?:show|hide|toggle|reveal|unhide|display) (?:the |my |all )?(?:hidden|invisible) (?:files|folders|items)(?: in finder| in the finder| on my mac)?$")
_SYS_Q = [
    (re.compile(r"^(?:what|which) (?:mac|macbook|computer|laptop)(?: model)?(?: is this| do i have| am i using| have i got)$|^what (?:model|kind|type) of (?:mac|macbook|computer|laptop)(?: is this| do i have| am i using)?$|^(?:what is|what) (?:my |this )?mac(?: model)?$|^what chip (?:do i have|is this|does my mac have)$|^what processor (?:do i have|is this)$|^(?:what|which) (?:cpu|chip|processor)(?: do i have| is this| does this mac have)?$"), 'model'),
    (re.compile(r"^(?:what|which) (?:macos|mac os|os|operating system)(?: version)?(?: am i (?:on|running|using)| do i have| is this| is installed)?$|^(?:what is|what) (?:my |the )?(?:macos|os)(?: version)?$|^(?:what|which) version of (?:macos|mac os) (?:am i (?:on|running|using)|do i have|is this)$|^macos version$"), 'os'),
    (re.compile(r"^how much (?:ram|memory) (?:do i have|does my mac have|does this mac have|have i got|is installed)$|^(?:what is|what) (?:my |the )?(?:mac )?(?:ram|memory)(?: size| capacity)?$|^how much (?:ram|memory)$"), 'ram'),
    (re.compile(r"^how much (?:ram|memory)(?: is| do i have| have i got)? (?:free|left|available|in use|used)$|^(?:is|am) (?:my|i)(?: mac| computer)?(?: low| running low| out) (?:on|of) (?:ram|memory)$|^(?:memory|ram)(?: usage| pressure| free)$|^how much (?:free )?(?:ram|memory) (?:is )?(?:free|left|available)$"), 'free'),
    (re.compile(r"^(?:what is|what) (?:my |the |this )?(?:mac|computer|laptop|macbook)(?: name| called)$|^what(?: is)? (?:my )?(?:mac|computer|laptop|macbook) called$|^what is this (?:mac|computer|laptop) called$"), 'name'),
    (re.compile(r"^(?:is|am)(?: my| the| this)?(?: mac| computer| laptop| macbook| i)?(?: connected| online)(?: to the internet)?(?: right now)?$|^(?:is )?(?:the )?internet (?:working|on|down|up)$|^am i online$|^do i have (?:internet|wifi)$|^is (?:my )?(?:internet|wifi) working$"), 'online'),
]


def _system(s):
    if _NOT_NOW.match(s):
        return None   # emptying, deleting, restarting: never without a spoken confirmation, so the person is asked first
    for fn in (_brightness, _dark_mode, _focus, _wifi, _bluetooth, _battery, _storage, _ip, _uptime, _awake):
        r = fn(s)
        if r:
            return r
    if _SLEEP.match(s):
        zc._run(['pmset', 'sleepnow'], 5)
        return f"Going to sleep{_c()}."
    m = _MIC.match(s)
    if m:
        mute = bool(re.search(r"^(?:mute|silence|turn off|switch off|disable)|off$|^(?:mic|microphone) mute$", s)) and not s.startswith('unmute')
        zc._osa(f"set volume input volume {0 if mute else 70}")
        return f"Mic muted{_c()}." if mute else f"Mic back on{_c()}."
    if _NIGHT.match(s):
        zc._run(['open', 'x-apple.systempreferences:com.apple.Displays-Settings.extension'], 8)
        return f"macOS has no switch I can flip for Night Shift{_c()}. I opened the Display settings, it's under Night Shift."
    if _HIDDEN.match(s):
        zc._osa('tell application "Finder" to activate')
        zc._osa(_se('keystroke "." using {command down, shift down}'))
        return f"Toggled hidden files in Finder{_c()}."
    for rx, kind in _SYS_Q:
        if rx.match(s):
            return _sys_info(kind)
    return None


def _sys_info(kind):
    if kind == 'online':
        return f"Yes, you're online{_c()}." if zc._tcp('1.1.1.1', 53, 2) else f"No, I can't reach the internet right now{_c()}."
    if kind == 'name':
        n = _sh(['scutil', '--get', 'ComputerName'], 4)
        return f"This Mac is called {n}{_c()}." if n else None
    if kind == 'os':
        v = _sh(['sw_vers', '-productVersion'], 4)
        if not v:
            return None
        major = v.split('.')[0]
        nm = {'11': 'Big Sur', '12': 'Monterey', '13': 'Ventura', '14': 'Sonoma', '15': 'Sequoia', '26': 'Tahoe'}.get(major)
        return f"You're on macOS {v}" + (f", {nm}" if nm else '') + f"{_c()}."
    if kind == 'free':
        out = _sh(['memory_pressure'], 8)
        m = re.search(r'free percentage:\s*(\d+)%', out)
        return f"About {m.group(1)} percent of your memory is free{_c()}." if m else None
    out = _sh(['system_profiler', 'SPHardwareDataType'], 25)
    name = re.search(r'Model Name:\s*(.+)', out)
    chip = re.search(r'(?:Chip|Processor Name):\s*(.+)', out)
    mem = re.search(r'Memory:\s*(.+)', out)
    if kind == 'ram':
        return f"You have {mem.group(1).strip()} of memory{_c()}." if mem else None
    if not name:
        return None
    return f"It's a {name.group(1).strip()}" + (f" with the {chip.group(1).strip()} chip" if chip else '') + (f" and {mem.group(1).strip()} of memory" if mem else '') + f"{_c()}."


# ---------------------------------------------------------------- media (Music / Spotify)
def _players():
    return [a for a in ('Music', 'Spotify') if zc._run(['pgrep', '-x', a], 3).returncode == 0]


def _playing():
    """The Music/Spotify app whose player state is playing right now, or None."""
    for a in _players():
        try:
            if zc._osa(f'tell application "{a}" to return (player state as text)', 5).lower().startswith('play'):
                return a
        except Exception:
            continue
    return None


def _player():
    """The Music/Spotify app that is playing (else any running one), or None."""
    run = _players()
    for a in run:
        try:
            if zc._osa(f'tell application "{a}" to return (player state as text)', 5).lower().startswith('play'):
                return a
        except Exception:
            continue
    return run[0] if run else None


_NOW = re.compile(r"^(?:what is|what) (?:is )?(?:playing|this song|this track|the song(?: that is)? playing|the current song|the current track|currently playing|this song called|that song|the song)(?: right now| at the moment| now)?$|"
                  r"^(?:what|which) (?:song|track|music) (?:is|s) (?:this|playing|on|that)(?: right now)?$|^what am i listening to$|^name (?:this|that) (?:song|track)$|^which song is this$|^what is (?:this|that) (?:song|track)(?: called)?$|^whats playing$|^what is this$|"
                  r"^who (?:sings|is singing|s singing|sang|is the artist(?: of)?|made|is playing) (?:this|that)(?: song| track)?$|^who (?:is )?this (?:artist|singer|by)$|^what(?: is|s)? the (?:current )?(?:song|track) (?:playing|name)$|^what(?: is|s)? the (?:song|track) (?:name )?playing$")
_SHUFFLE = re.compile(r"^(?:turn|switch|set|put)(?: (?:on|off))? (?:the )?shuffle(?: (?:on|off))?$|^shuffle(?: (?:on|off))?$|^(?:enable|disable) shuffle$|^(?:shuffle|mix up) (?:my |the |this )?(?:music|songs|playlist|library|tracks)$|^(?:stop|no more) shuffl(?:e|ing)$|^(?:turn|switch) (?:on|off) shuffle$")
_REPEAT = re.compile(r"^(?:repeat|loop) (?:this |the current )?(?:song|track)(?: (?:on|off))?$|^(?:turn|switch|set)(?: (?:on|off))? (?:song |track )?repeat(?: (?:on|off))?$|^(?:stop|disable) repeating(?: this| the)?(?: song| track)?$|^repeat (?:on|off)$|^(?:turn|switch) (?:on|off) repeat$")
_LIKE = re.compile(r"^(?:like|love|favou?rite|heart|save|add to favou?rites) (?:this|the current|that|it)(?: song| track| one| video)?(?: to (?:my )?(?:favou?rites|library|liked(?: songs| videos)?|playlist))?$|"
                   r"^add (?:this|that|it)(?: song| track| one| video)? to (?:my |the )?(?:favou?rites|library|liked(?: songs| videos)?|(?:\w+ )?playlist)$")
_SIMILAR = re.compile(r"^(?:play |put on |give me |queue )?(?:some |a few )?(?:(?:more|other|similar)(?: (?:songs?|music|tracks|stuff|ones?))?|songs?|music|tracks|stuff|ones?) (?:like|similar to) (?:this|that|it)(?: song| one| track)?$|"
                      r"^(?:play |put on |give me )?(?:some |a few )?(?:more )?similar (?:songs?|music|tracks|stuff|ones?)$|^more like (?:this|that)$")
_MUSIC_VOL = re.compile(r"^(?:turn|make|put|bring|crank)(?: the)? music (?P<d>up|down|louder|quieter|softer)$|^music (?P<d2>up|down|louder|quieter)$|^(?:turn|make) (?:the )?(?:song|songs|track) (?P<d3>up|down|louder|quieter)$")
_APPLE_PL = re.compile(r"^(?:play|put on|start|queue up|start playing|play me)(?: my| the| a)?(?: playlist)?(?: called| named)? (?P<p>.+?)(?: playlist)? (?:in|on|using|from|with|through) (?:my )?(?:the )?(?:apple music|music app|the music app|music)$|^(?:apple music|music app)(?: play| start| put on)(?: my| the)?(?: playlist)? (?P<p2>.+?)(?: playlist)?$")


def _media(s, raw):
    m = _MUSIC_VOL.match(s)
    if m:
        up = (m.groupdict().get('d') or m.groupdict().get('d2') or m.groupdict().get('d3')) in ('up', 'louder')
        return zc._volume('volume up' if up else 'volume down', 'volume up' if up else 'volume down')
    if _NOW.match(s):
        return _now_playing(s)
    if _SHUFFLE.match(s):
        on = not re.search(r'\b(off|disable|stop|no more)\b', s)
        a = _player()
        if not a:
            return f"Neither Music nor Spotify is open{_c()}."
        val = 'true' if on else 'false'
        zc._osa(f'tell application "{a}" to set {"shuffle enabled" if a == "Music" else "shuffling"} to {val}')
        return f"Shuffle {'on' if on else 'off'}{_c()}."
    if _REPEAT.match(s):
        on = not re.search(r'\b(off|disable|stop)\b', s)
        a = _player()
        if not a:
            return f"Neither Music nor Spotify is open{_c()}."
        if a == 'Music':
            zc._osa(f'tell application "Music" to set song repeat to {"one" if on else "off"}')
        else:
            zc._osa(f'tell application "Spotify" to set repeating to {"true" if on else "false"}')
        return f"{'Repeating this song' if on else 'Repeat off'}{_c()}."
    if _SIMILAR.match(s):
        return _similar()
    if _LIKE.match(s):
        if 'Music' in _players():
            zc._osa('tell application "Music" to set favorited of current track to true')
            return f"Added it to your favorites{_c()}."
        return None if _players() else _yt_like()   # Spotify has no like in AppleScript; no app running = the YouTube tab
    m = _APPLE_PL.match(s)
    if m:
        name = (m.group('p') or m.group('p2') or '').strip()
        name = re.sub(r'^(?:my|the|a|playlist)\b\s*', '', name).strip()
        if not name or re.search(r'\b(this|that|it|something|anything|music|a song|songs?)$', name):
            return None
        r = zc._osa('tell application "Music"\nset r to (every playlist whose name contains "%s")\nif (count of r) = 0 then return "none"\nplay (item 1 of r)\nreturn name of (item 1 of r)\nend tell' % _q(name), 15)
        if r == 'none':
            return f"I couldn't find a playlist called {name} in Apple Music{_c()}."
        return f"Playing {r} in Apple Music{_c()}."
    return None


def _similar():
    """'play more like this': Music -> more by the current artist from the library; YouTube (Music) -> '<title> mix'."""
    a = _playing()
    if a == 'Music':
        r = zc._osa('tell application "Music"\nset a to artist of current track\nset i to database ID of current track\n'
                    'set r to (every track of library playlist 1 whose artist is a and database ID is not i)\n'
                    'if (count of r) = 0 then return "none"\nplay (some item of r)\nreturn a\nend tell', 15)
        return f"I couldn't find more by that artist in your library{_c()}." if r in ('none', '') else f"Playing more by {r}{_c()}."
    if a:
        return None   # Spotify can't search from AppleScript
    host, title = _yt_exec(_YT_WHAT)
    if not host or not title:
        return None
    title = re.sub(r"\s+", ' ', title).strip()
    import atticus
    return f"Playing a mix like {title}{_c()}." if atticus.youtube_play(f"{title} mix", music='music.youtube.com' in host) else None


_YT_LIKE = ("(function(){var r=document.querySelector('ytmusic-like-button-renderer');if(r&&r.getAttribute('like-status')==='LIKE')return 'already';"
            "var b=document.querySelector('ytmusic-like-button-renderer #button-shape-like button,ytmusic-like-button-renderer .like,like-button-view-model button,#segmented-like-button button,ytd-toggle-button-renderer#like-button button');"
            "if(!b)return 'none';if(b.getAttribute('aria-pressed')==='true')return 'already';b.click();return 'liked'})()")


def _yt_like():
    host, out = _yt_exec(_YT_LIKE)
    if not host:
        return None
    music = 'music.' in host
    return f"You'd already liked it{_c()}." if out == 'already' else f"Liked it on {'YouTube Music' if music else 'YouTube'}{_c()}. It's saved to your liked {'songs' if music else 'videos'}."


def _now_playing(s):
    a = _player()
    if not a:
        return f"Nothing's playing in Music or Spotify{_c()}."
    out = zc._osa(f'tell application "{a}"\nif player state is not playing then return ""\nreturn (name of current track) & "|" & (artist of current track)\nend tell', 6)
    if '|' not in out:
        return f"Nothing's playing in {a} right now{_c()}."
    name, artist = out.split('|', 1)
    if re.search(r'\bwho\b|artist|singer|sings', s):
        return f"That's {artist}, with {name}{_c()}."
    return f"{name} by {artist}{_c()}."


# ---------------------------------------------------------------- browser
def _bscript(verb_chromium, verb_safari, after=''):
    """Run something on the front window of the person's own browser (Chromium vs Safari). 'off' if it isn't running."""
    b = zc._browser()
    if zc._is_safari(b):
        body = f'tell front window to {verb_safari}'
    else:
        body = f'tell front window to {verb_chromium}'
    return (f'if application "{b}" is not running then return "off"\ntell application "{b}"\nif (count of windows) = 0 then return "none"\n{body}\n{after}\nend tell\nreturn "ok"'), b


def _browser_ui(s, raw):
    b = zc._browser()
    sh = zc._short(b)
    safari = zc._is_safari(b)
    if re.match(r"^(?:open |make |create |start )?(?:a |another )?new tab$|^(?:open |make |create )(?:a |another )?(?:new )?(?:blank )?tab$", s):
        if safari:
            script = f'tell application "Safari"\nactivate\nif (count of windows) = 0 then\nmake new document\nelse\ntell front window to set current tab to (make new tab)\nend if\nend tell'
        else:
            script = f'tell application "{b}"\nactivate\nif (count of windows) = 0 then make new window\ntell front window to make new tab\nend tell'
        zc._osa(script)
        return f"New tab{_c()}."
    if re.match(r"^close (?:this |the |my |current |that )?tab$", s):
        script, _ = _bscript('close active tab', 'close current tab')
        r = zc._osa(script)
        return f"Closed the tab{_c()}." if r == 'ok' else f"{sh} isn't open{_c()}."
    if re.match(r"^(?:reload|refresh)(?: this| the| my| that)?(?: page| tab| site| website)?$|^(?:hard )?(?:reload|refresh) (?:it|this)$", s):
        script, _ = _bscript('reload active tab', 'set URL of current tab to (URL of current tab)')
        r = zc._osa(script)
        return f"Reloaded{_c()}." if r == 'ok' else f"{sh} isn't open{_c()}."
    m = re.match(r"^go (back|forward)(?: a page| one page| a step)?$|^(?:navigate|page|browser) (back|forward)$|^(back|forward) a page$", s)
    if m:
        back = 'back' in s
        zc._osa(_se(f'keystroke "{"[" if back else "]"}" using command down'))
        return f"Went {'back' if back else 'forward'}{_c()}."
    if re.match(r"^(?:next|previous) tab$|^(?:switch|go|move)(?: to)?(?: the)? (?:next|previous) tab$|^tab (?:left|right)$|^go to (?:the )?(?:next|previous) tab$", s):
        back = bool(re.search(r'\b(previous|left)\b', s))
        zc._osa(f'tell application "{b}" to activate\n' + _se('key code 48 using ' + ('{control down, shift down}' if back else 'control down')))
        return f"{'Previous' if back else 'Next'} tab{_c()}."
    if re.match(r"^(?:open |reopen |restore |bring back |undo closing |get back )(?:my |the )?(?:last|previous|recently)? ?(?:closed )?tab(?: again)?$|^reopen (?:the |my )?(?:last |previous )?(?:closed )?(?:tab|page)$|^(?:open|bring back|restore) (?:my |the )?last closed (?:tab|page)$|^(?:undo|bring back) (?:the )?(?:tab )?close$", s):
        zc._osa(f'tell application "{b}" to activate\n' + _se('keystroke "t" using {command down, shift down}'))
        return f"Brought back your last tab{_c()}."
    if re.match(r"^(?:open |start |make |new )(?:a |an |another )?(?:new )?(?:private|incognito) (?:window|tab|browsing|session)$|^(?:new |go )(?:private|incognito)(?: window)?$", s):
        if safari:
            zc._osa('tell application "Safari" to activate\n' + _se('keystroke "n" using {command down, shift down}'))
        else:
            zc._osa(f'tell application "{b}"\nactivate\nmake new window with properties {{mode:"incognito"}}\nend tell')
        return f"Private window open{_c()}."
    if re.match(r"^bookmark (?:this|the|my|that|current)?(?: page| tab| site| website)?$|^(?:add|save) (?:this|the current)(?: page| site| tab)? (?:to|as)(?: my)? (?:bookmarks?|favou?rites)$|^(?:add|save) (?:a )?bookmark$", s):
        zc._osa(f'tell application "{b}" to activate\n' + _se('keystroke "d" using command down'))
        return f"Bookmark window open{_c()}. Hit return to save it."
    m = re.match(r"^zoom (in|out)(?: a bit| a little)?$|^(?:make|turn) (?:the )?(?:page|text|screen) (bigger|smaller|larger)$", s)
    if m:
        zin = m.group(1) == 'in' or m.group(2) in ('bigger', 'larger')
        zc._osa(_se(f'keystroke "{"=" if zin else "-"}" using command down'))
        return f"Zoomed {'in' if zin else 'out'}{_c()}."
    if re.match(r"^paste(?: it| that| here| this)?$", s):
        zc._osa(_se('keystroke "v" using command down'))
        return f"Pasted{_c()}."
    # reading the page
    title = re.match(r"^(?:what is|what) (?:the )?(?:title|name) of (?:this|the|my|that|current)(?: current| open)? (?:page|tab|site|website|webpage)$|^(?:read|tell|say|give) (?:me )?(?:the )?(?:page|tab|site|website|webpage) title$|^(?:what|which) (?:page|tab|site|website|webpage) (?:am i|is) (?:on|open|in)$|^what(?: is|s)? (?:the )?(?:page|tab|website|site)? ?(?:title|name)$|^(?:what|which) tab (?:am i on|is open|is this)$", s)
    url = re.match(r"^(?:what is|what) (?:the )?(?:url|link|address|web address) (?:of|for) (?:this|the|my|that|current)(?: current| open)? (?:page|tab|site|website|webpage)$|^(?:what is|what) (?:this|the current) (?:page s |page )?(?:url|link|address)$|^(?:read|tell|say|give) (?:me )?(?:the )?(?:page |tab )?(?:url|link|address)$", s)
    copy = re.match(r"^copy (?:the |this |my |that |current )?(?:page |tab |site |website )?(?:link|url|address)(?: of this page| to the clipboard| to my clipboard)?$|^copy (?:the |this )?(?:page|tab|site|website)(?: link| url| address)?(?: to the clipboard)?$|^copy this page s (?:link|url)$", s)
    if title or url or copy:
        prop = ('URL of current tab' if safari else 'URL of active tab') if (url or copy) else ('name of current tab' if safari else 'title of active tab')
        out = zc._osa(f'if application "{b}" is not running then return ""\ntell application "{b}"\nif (count of windows) = 0 then return ""\nreturn {prop} of front window\nend tell')
        if not out:
            return f"{sh} isn't open{_c()}."
        if copy:
            zc._run(['pbcopy'], 4, out)
            return f"Copied the page link{_c()}."
        return (f"The link is {out}{_c()}." if url else f"You're on {_clip(out, 120)}{_c()}.")
    # search Google (fast() sends "search google for X" nowhere sensible because Google counts as an app name there)
    m = re.search(r"(?:search|look up|find|google)(?: up)?(?: on)? google (?:for )?(.+)$|(?:search|look up)(?: up)? (?:for )?(.+?) (?:on|in|with|using) google$", raw.strip(), re.I)
    if m and re.match(r"^(?:search|look up|find)(?: up)?(?: on)? google|^(?:search|look up)(?: up)?(?: for)? .+ (?:on|in|with|using) google$", s):
        q = (m.group(1) or m.group(2) or '').strip(' .?!')
        if q and not re.search(r'\b(this|that|it|them|here|there)$', q.lower()):
            if zc._open_browser('https://www.google.com/search?q=' + urllib.parse.quote(q)):
                return f"Searched Google for {q}{_c()}."
    return None


# ---------------------------------------------------------------- files and folders
_LATEST_OPEN = re.compile(r"^open (?:my |the )?(?:latest|last|newest|most recent|recent|newly) (?:downloaded )?(?:download|file|downloaded file)(?: i downloaded| in downloads| from downloads)?$|^open (?:the )?(?:file )?(?:i just|i recently|i last) downloaded$|^open what i (?:just|last) downloaded$|^open (?:my )?(?:last|latest) download$")
_LATEST_SHOW = re.compile(r"^(?:show|reveal|find|where is|where is|locate) (?:me )?(?:my |the )?(?:latest|last|newest|most recent) (?:downloaded )?(?:download|file)(?: in (?:the )?finder)?$|^(?:reveal|show) (?:my )?(?:latest|last) download in finder$")
_LATEST_NAME = re.compile(r"^what (?:did i|have i|was the|was my|is my|is the|s my|s the) (?:last |latest |just |recently )?(?:download|downloaded)(?: last| most recently| recently| just now)?$|^what is (?:my |the )?(?:latest|last|newest|most recent) download$|^what (?:was|is) (?:my |the )?(?:latest|last|newest|most recent) (?:download|file i downloaded)$|^what did i (?:just )?download(?: last)?$")


def _latest_download():
    d = os.path.join(_home(), 'Downloads')
    best = None
    try:
        for e in os.scandir(d):
            if e.name.startswith('.') or e.name.endswith(('.crdownload', '.download', '.part', '.tmp', '.opdownload')):
                continue
            try:
                mt = e.stat().st_mtime
            except OSError:
                continue
            if best is None or mt > best[0]:
                best = (mt, e.path, e.name)
    except OSError:
        return None
    return best


def _files(s, raw):
    if _LATEST_OPEN.match(s) or _LATEST_SHOW.match(s) or _LATEST_NAME.match(s):
        best = _latest_download()
        if not best:
            return f"Your Downloads folder is empty{_c()}."
        _, path, name = best
        if _LATEST_NAME.match(s):
            return f"Your latest download is {name}{_c()}."
        if _LATEST_SHOW.match(s):
            zc._run(['open', '-R', path], 8)
            return f"Showing {name} in Finder{_c()}."
        zc._run(['open', path], 8)
        return f"Opening {name}{_c()}."
    if re.match(r"^open (?:the |my )?applications(?: folder)?$", s):
        zc._run(['open', '/Applications'], 8)
        return f"Opening Applications{_c()}."
    q = None
    m = re.search(r"(?:find|search for|locate|look for|where is|get me)\s+(?:a |an |the |my |any )?(?:files?|documents?|pdfs?|folders?)?\s*(?:file )?(?:named|called|with the name|titled)\s+(.+?)(?:\s+(?:on|in) (?:my |the )?(?:mac|computer|laptop|macbook))?$", raw.strip(' .?!'), re.I)
    if m and re.match(r"^(?:find|search for|locate|look for|where is|get me)\b", s):
        q = m.group(1)
    if not q:
        m = re.search(r"^(?:search|look|find|scan)(?: through)? (?:my |the |this )?(?:mac|computer|laptop|macbook|files|documents|drive|hard drive|disk)(?: for)? (.+?)$|^(?:find|search for|locate|look for) (?:a |an |the |my )?(.+?) (?:on|in) (?:my |the |this )(?:mac|computer|laptop|macbook)$", raw.strip(' .?!'), re.I)
        if m and re.match(r"^(?:search|look|find|scan)\b", s):
            q = m.group(1) or m.group(2)
    if q:
        q = re.sub(r'^(?:for |a |an |the |my )+', '', q.strip(), flags=re.I).strip()
        if not q or re.search(r'\b(this|that|it|them)$', q.lower()) or len(q) > 60:
            return None
        return _find_file(q)
    m = re.match(r"^open (?:the |my )?folder (?:called |named )?(?P<f>[a-z0-9 _.-]+?)$|^open (?:the |my )?(?P<f2>[a-z0-9 _.-]+?) folder$|^go to (?:the |my )?(?P<f3>[a-z0-9 _.-]+?) folder$|^show (?:me )?(?:the |my )?(?P<f4>[a-z0-9 _.-]+?) folder$", s)
    if m:
        name = (m.group('f') or m.group('f2') or m.group('f3') or m.group('f4')).strip()
        if name in ('applications',) or re.search(r'\b(this|that|it|new|my|the|a|recent|shared)$', name):
            return None
        return _open_folder(name, raw)
    m = re.match(r"^(?:make|create|add|new|start) (?:me )?(?:a |an )?(?:new )?folder(?: (?:on|in) (?:my |the )?(?P<w1>desktop|documents|downloads|home))? (?:called|named|titled)? ?(?P<n>.+?)(?: (?:on|in) (?:my |the )?(?P<w2>desktop|documents|downloads|home))?$", s)
    if m and re.search(r'\b(?:called|named|titled)\b', s):
        n = re.search(r'(?:called|named|titled)\s+(.+?)(?:\s+(?:on|in) (?:my |the )?(?:desktop|documents|downloads|home))?$', raw.strip(' .?!'), re.I)
        name = (n.group(1) if n else m.group('n')).strip()
        where = (m.group('w1') or m.group('w2') or 'desktop').lower()
        return _new_folder(name, where)
    if re.match(r"^(?:what is|what|whats|show me|list|tell me what is|what files are) (?:on |in )?(?:my |the )?desktop(?: files)?$|^what files (?:are )?on my desktop$|^how many (?:files|things|items|icons) (?:are |do i have )?(?:on|in) my desktop$|^list (?:the )?(?:files )?(?:on |in )?my desktop$|^what(?: is|s) on my desktop$", s):
        return _desktop()
    return None


def _find_file(q):
    out = _sh(['mdfind', '-onlyin', _home(), '-name', q], 15)
    hits = [p for p in out.splitlines() if p and '/Library/' not in p and '/.' not in p and '/node_modules/' not in p]
    if not hits:
        return f"I couldn't find anything named {q}{_c()}."
    def mt(p):
        try: return os.path.getmtime(p)
        except OSError: return 0
    hits.sort(key=lambda p: (-(os.path.splitext(os.path.basename(p))[0].lower() == q.lower()), -mt(p)))
    top = hits[0]
    zc._run(['open', '-R', top], 8)
    folder = os.path.basename(os.path.dirname(top)) or 'your Mac'
    many = f"Found {len(hits)} matches. " if len(hits) > 1 else ''
    return f"{many}The best one is {os.path.basename(top)} in {folder}, and I showed it in Finder{_c()}."


def _open_folder(name, raw):
    home = _home()
    low = name.lower()
    for base in ('', 'Desktop', 'Documents', 'Downloads', 'Movies', 'Pictures', 'Music', 'Projects', 'Developer'):
        root = os.path.join(home, base) if base else home
        try:
            for e in os.scandir(root):
                if e.is_dir() and e.name.lower() == low and not e.name.startswith('.'):
                    zc._run(['open', e.path], 8)
                    return f"Opening {e.name}{_c()}."
        except OSError:
            continue
    out = _sh(['mdfind', '-onlyin', home, f'kMDItemContentType == "public.folder" && kMDItemFSName == "{_q(name)}"c'], 12)
    hits = [p for p in out.splitlines() if p and '/Library/' not in p and '/.' not in p and '/node_modules/' not in p]
    if hits:
        hits.sort(key=lambda p: p.count('/'))
        zc._run(['open', hits[0]], 8)
        return f"Opening {os.path.basename(hits[0])}{_c()}."
    return f"I couldn't find a folder called {name}{_c()}."


def _new_folder(name, where):
    name = re.sub(r'[/:\\]+', ' ', name).strip().strip('.')
    if not name or len(name) > 80:
        return None
    if name == name.lower(): name = name.title()
    base = _home() if where == 'home' else os.path.join(_home(), where.capitalize())
    path = os.path.join(base, name)
    if os.path.exists(path):
        return f"There's already a folder called {name} on your {where}{_c()}."
    os.mkdir(path)
    return f"Made a folder called {name} on your {where}{_c()}."


def _desktop():
    try:
        names = sorted(n for n in os.listdir(os.path.join(_home(), 'Desktop')) if not n.startswith('.'))
    except OSError:
        return None
    if not names:
        return f"Your Desktop is empty{_c()}."
    shown = ', '.join(names[:4]) + (f' and {len(names) - 4} more' if len(names) > 4 else '')
    return f"You have {len(names)} item{'s' if len(names) != 1 else ''} on your Desktop: {shown}{_c()}."


# ---------------------------------------------------------------- people: WhatsApp, email, FaceTime, calls, texts
def _contact(name):
    """(full name, phone digits, email) from Contacts, or None if there is no such person."""
    out = zc._osa('tell application "Contacts"\nset ps to (people whose name contains "%s")\nif (count of ps) = 0 then return ""\nset p to item 1 of ps\n'
                  'set ph to ""\nif (count of phones of p) > 0 then set ph to value of item 1 of phones of p\n'
                  'set em to ""\nif (count of emails of p) > 0 then set em to value of item 1 of emails of p\nreturn (name of p) & "|" & ph & "|" & em\nend tell' % _q(name), 15)
    if not out or '|' not in out:
        return None
    full, ph, em = (out.split('|') + ['', ''])[:3]
    digits = re.sub(r'\D', '', ph)
    return full, digits, em.strip()


def _app_exists(name):
    return any(os.path.exists(os.path.join(d, name + '.app')) for d in ('/Applications', os.path.join(_home(), 'Applications')))


def _who(w):
    w = re.sub(r"^(?:my|the)\s+", '', w.strip(), flags=re.I).strip()
    if w == w.lower(): w = w.title()
    return w if 0 < len(w) <= 40 and re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", w) else None


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_COMPOSE = re.compile(r"^(?:write|compose|draft|start|begin|create|open|make|prepare|send|shoot|fire off|type)(?: up| out)? (?:me )?(?:a |an |a new |an new |new )?(?:email|mail|e mail|message)(?: draft)?(?: to| for) (?P<w>.+)$|^(?:email|mail) (?P<w2>.+)$")
_SEND_TXT = re.compile(r"^(?:text|sms|imessage|message) (?P<w>.+)$|^(?:send|write|shoot) (?:a )?(?:text|sms|imessage|text message) to (?P<w2>.+)$")
_WA = re.compile(r"^(?:open|start|show|go to|pull up|bring up|find|message|text|chat with|talk to)(?: up)?(?: the| my)? (?:whatsapp )?(?:chat|conversation|thread|messages?)? ?(?:with|from|of|for) (?P<w>.+?)(?: (?:on|in|from) whatsapp)?$|^(?:whatsapp|message|text|chat with) (?P<w2>.+?) (?:on|in|using|via) whatsapp$|^(?:open )?whatsapp (?:chat )?(?:with|for) (?P<w3>.+)$|^whatsapp (?P<w4>.+)$")
_FACETIME = re.compile(r"^(?:facetime|face time) (?P<w>.+)$|^(?:open|start|launch)(?: a)? facetime(?: call)?(?: with| to) (?P<w2>.+)$")
_CALL = re.compile(r"^(?:call|phone|ring|dial|give a call to|make a call to|make a phone call to) (?P<w>.+)$")


def _people(s, raw):
    r = raw.strip(' .?!')
    m = _WA.match(s)
    if m and ('whatsapp' in s):
        who = _who(re.sub(r'\s+', ' ', (m.group('w') or m.group('w2') or m.group('w3') or m.group('w4') or '')).strip())
        who = re.sub(r"\s+(?:chat|conversation)$", '', who or '') or None
        if who:
            return _whatsapp(who)
    m = _COMPOSE.match(s)
    if m:
        return _compose(r)
    m = _FACETIME.match(s)
    if m:
        who = _who(r[re.search(r'face ?time', r, re.I).end():].strip() if re.search(r'face ?time', r, re.I) else '')
        zc._run(['open', '-a', 'FaceTime'], 8)
        return f"Opened FaceTime{_c()}. Pick {who} there to call, I won't dial for you." if who else f"Opened FaceTime{_c()}."
    m = _CALL.match(s)
    if m:
        who = _who(m.group('w'))
        if who and who.lower().split()[0] not in ('me', 'it', 'us', 'them', 'back', 'that', 'this', 'him', 'her', 'a', 'an', 'out', 'off', 'in', 'you', 'zuka', 'for', 'to') and len(who.split()) <= 2:
            zc._run(['open', '-a', 'FaceTime'], 8)
            return f"I opened FaceTime{_c()}. Pick {who} there, I won't place the call myself."
    m = _SEND_TXT.match(s)
    if m and not re.search(r'\b(?:whatsapp|telegram|signal|slack|discord|insta|instagram)\b', s):
        return _text(r)
    return None


def _whatsapp(who):
    c = _contact(who)
    if not c:
        return f"I couldn't find {who} in your Contacts{_c()}."
    full, digits, _ = c
    if len(digits) < 10:
        return f"{full} has no phone number in Contacts{_c()}."
    if _app_exists('WhatsApp'):
        zc._run(['open', f'whatsapp://send?phone={digits}'], 8)
    elif not zc._open_browser(f'https://wa.me/{digits}'):
        return None
    return f"Opened your WhatsApp chat with {full}{_c()}. I haven't sent anything."


def _compose(r):
    em = _EMAIL.search(r)
    subject = None
    msub = re.search(r"\b(?:about|regarding|re|with (?:the )?subject|subject)\s+(.+)$", r, re.I)
    tail = r[:msub.start()] if msub else r
    if msub: subject = _cap(msub.group(1).strip(' .'))
    to, full = '', ''
    if em:
        to = em.group(0)
        if len(re.sub(re.escape(to), '', tail, flags=re.I).split(' to ', 1)[-1].split()) > 6:
            return None
    else:
        mt = re.search(r"\b(?:to|for)\s+(.+?)$", tail, re.I) or re.search(r"^(?:email|mail)\s+(.+?)$", tail.strip(), re.I)
        who = _who(mt.group(1)) if mt else None
        if not who or len(who.split()) > 3:
            return None   # "an email to my boss asking for leave" needs real writing: not free
        c = _contact(who)
        if not c:
            return None
        full, _, to = c
        if not to:
            to = ''
    url = 'mailto:' + urllib.parse.quote(to) + ('?subject=' + urllib.parse.quote(subject) if subject else '')
    zc._run(['open', url], 8)
    who = to or full or 'a blank address'
    return f"Opened an email draft to {who}{_c()}. I won't send it, that's yours."


def _text(r):
    m = re.search(r"^(?:text|sms|imessage|message)\s+(?P<w>[A-Za-z][A-Za-z .'-]{0,30}?)(?:\s+(?:saying|that says|that|to say|and say|telling (?:him|her|them))\s+(?P<b>.+))?$|^(?:send|write|shoot)\s+(?:a )?(?:text|sms|imessage|text message)\s+to\s+(?P<w2>[A-Za-z][A-Za-z .'-]{0,30}?)(?:\s+(?:saying|that says|that|to say)\s+(?P<b2>.+))?$", r, re.I)
    if not m:
        return None
    who = _who(m.group('w') or m.group('w2'))
    body = (m.group('b') or m.group('b2') or '').strip(' .')
    if not who or len(who.split()) > 2 or who.lower() in ('me', 'my', 'him', 'her', 'them', 'back', 'it'):
        return None
    c = _contact(who)
    if not c or len(c[1]) < 10:
        return None
    url = f'sms:+{c[1]}' + ('&body=' + urllib.parse.quote(_cap(body)) if body else '')
    zc._run(['open', url], 8)
    return f"Opened a message to {c[0]}{_c()}. It's not sent, press return when you're ready."


# ---------------------------------------------------------------- dates, calendar
_MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'], 1)}
_MONTHS.update({'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12})
_WEEKDAYS = {d: i for i, d in enumerate(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])}
_HOLIDAYS = {'christmas': (12, 25), 'christmas day': (12, 25), 'christmas eve': (12, 24), 'new year': (1, 1), 'new years': (1, 1), 'new year day': (1, 1), 'new years day': (1, 1),
             'new years eve': (12, 31), 'new year eve': (12, 31), 'halloween': (10, 31), 'valentines day': (2, 14), 'valentine day': (2, 14), 'valentines': (2, 14)}
_MON_RX = '|'.join(sorted(_MONTHS, key=len, reverse=True))


def _next_md(month, day, today, year=None):
    if year:
        return date(year, month, day)
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def _parse_date(text, today):
    """(date, spoken label) from words like 'tomorrow', 'next friday', 'december 25th 2027', 'christmas'; else None."""
    s = text.lower().strip().replace("'", '')
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    s = re.sub(r'\b(\d{1,2})(?:st|nd|rd|th)\b', r'\1', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'^(?:the |on |for |until |till |to |is |next time )+', '', s).strip()
    if s in ('today', 'tonight'): return today, 'today'
    if s == 'tomorrow': return today + timedelta(days=1), 'tomorrow'
    if s == 'yesterday': return today - timedelta(days=1), 'yesterday'
    if s == 'day after tomorrow': return today + timedelta(days=2), 'the day after tomorrow'
    if s in _HOLIDAYS:
        mo, dy = _HOLIDAYS[s]
        return _next_md(mo, dy, today), s
    m = re.fullmatch(r'(next |this |coming )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)', s)
    if m:
        delta = (_WEEKDAYS[m.group(2)] - today.weekday()) % 7
        if m.group(1) == 'next ' and delta == 0: delta = 7
        elif m.group(1) == 'next ' and delta < 7 and False: pass
        if m.group(1) is None or m.group(1) == 'this ': pass
        if m.group(1) == 'next ' and delta == 0: delta = 7
        return today + timedelta(days=delta), s
    m = re.fullmatch(rf'({_MON_RX}) (\d{{1,2}})(?: (\d{{4}}))?', s) or None
    if m:
        mo, dy, yr = _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3)) if m.group(3) else None
    else:
        m = re.fullmatch(rf'(\d{{1,2}}) (?:of )?({_MON_RX})(?: (\d{{4}}))?', s)
        if not m: return None
        mo, dy, yr = _MONTHS[m.group(2)], int(m.group(1)), int(m.group(3)) if m.group(3) else None
    try:
        return _next_md(mo, dy, today, yr), s
    except ValueError:
        return None


def _day_name(d, today):
    diff = (d - today).days
    if diff == 0: return 'today'
    if diff == 1: return 'tomorrow'
    if diff == -1: return 'yesterday'
    if 0 < diff < 7: return d.strftime('%A')
    return f"{d.strftime('%A')} the {zc._ordinal(d.day)} of {d.strftime('%B')}"


def _long_date(d):
    return f"{d.strftime('%A')}, {d.strftime('%B')} {zc._ordinal(d.day)}, {d.year}"


_DAYS_UNTIL = re.compile(r"^how many days (?:are )?(?:left |is it |are there |to go |remain(?:ing)? )?(?:until|till|to|before|til) (?P<d>.+)$|^how long (?:is it )?(?:until|till|to|before) (?P<d2>.+)$|^(?:days|how many days) (?:until|till|to|left until|left till) (?P<d3>.+)$|^how many (?:sleeps|days) (?:until|till|to) (?P<d4>.+)$|^how far (?:away )?is (?P<d5>.+)$|^when is (?P<d6>christmas|halloween|new years? (?:eve|day)?|valentines day|christmas eve)$")
_WHAT_DAY = re.compile(r"^what (?:day|day of the week) (?:is|does|will|was) (?:it )?(?:on )?(?P<d>.+?)(?: fall on| land on| be)?$|^what (?:day|weekday) is (?P<d2>.+)$|^which day (?:is|does) (?P<d3>.+?)(?: fall on)?$|^what(?: is|s)? (?:the )?date (?:on |of |for )?(?P<d4>.+)$|^what(?: is|s)? (?:the )?date (?P<d5>next .+|this .+|tomorrow|yesterday)$|^when is (?P<d6>next .+|this .+)$|^what is the date (?P<d7>.+)$")


def _dates(s, raw):
    today = _today()
    m = _DAYS_UNTIL.match(s)
    if m:
        txt = next(g for g in m.groups() if g)
        txt0 = txt
        if re.search(r'\b(?:my|his|her|their|our)\b', txt) or re.search(r'\b(birthday|anniversary|wedding|exam|trip|vacation|holiday|deadline|salary|payday|weekend|summer|winter|diwali|eid|holi)\b', txt):
            if re.match(r'^(?:the )?weekend$', txt):
                delta = (5 - today.weekday()) % 7
                return f"{delta} day{'s' if delta != 1 else ''} until the weekend{_c()}." if delta else f"It's the weekend{_c()}."
            return None
        if re.match(r"^(?:the )?(?:end of (?:the )?year|new year(?:s)? eve|year end|the year ends?)$", txt):
            delta = (date(today.year, 12, 31) - today).days
            return f"{delta} day{'s' if delta != 1 else ''} left in {today.year}{_c()}."
        r = _parse_date(txt, today)
        if not r:
            return None
        d, _ = r
        delta = (d - today).days
        key = re.sub(r'[^a-z ]', '', txt0.lower()).strip()
        key = re.sub(r'^(?:the )', '', key)
        what = key.title() if key in _HOLIDAYS else f"{d.strftime('%B')} {zc._ordinal(d.day)}"
        if delta == 0: return f"That's today{_c()}."
        if delta < 0: return f"That was {-delta} day{'s' if delta != -1 else ''} ago{_c()}."
        return f"{delta} day{'s' if delta != 1 else ''} until {what}{_c()}."
    if re.match(r"^how many days (?:are )?(?:left|remain(?:ing)?)(?: in| of) (?:the |this )?year$|^how many days (?:are )?left this year$|^days (?:left )?(?:in|of) (?:the |this )?year$", s):
        delta = (date(today.year, 12, 31) - today).days
        return f"{delta} day{'s' if delta != 1 else ''} left in {today.year}{_c()}."
    if re.match(r"^(?:what|which) (?:week|week number) (?:of the year )?(?:is it|are we in)(?: now| right now)?$|^what week of the year is it$|^what is the week number$|^(?:what|which) week (?:of the year )?(?:are we in|is this)$", s):
        return f"It's week {today.isocalendar()[1]} of {today.year}{_c()}."
    m = _WHAT_DAY.match(s)
    if m:
        txt = next(g for g in m.groups() if g)
        if re.search(r'\b(it|this|that|my|today)\b', txt) and txt.strip() not in ('this friday', 'this monday', 'this tuesday', 'this wednesday', 'this thursday', 'this saturday', 'this sunday'):
            return None
        r = _parse_date(txt, today)
        if not r:
            return None
        d, lab = r
        if re.search(r'^(?:what is the date|what is the date|what date|when is)', s) or 'date' in s.split()[:3]:
            lead = _day_name(d, today).capitalize() if lab in ('today', 'tomorrow', 'yesterday') else lab.title()
            day = f"{d.strftime('%B')} {zc._ordinal(d.day)}, {d.year}" if re.search(r'monday|tuesday|wednesday|thursday|friday|saturday|sunday', lab) else _long_date(d)
            return f"{lead} is {day}{_c()}."
        return f"{d.strftime('%B')} {zc._ordinal(d.day)}, {d.year} is a {d.strftime('%A')}{_c()}."
    return None


_CITY_TZ = {'london': 'Europe/London', 'uk': 'Europe/London', 'england': 'Europe/London', 'britain': 'Europe/London', 'new york': 'America/New_York', 'nyc': 'America/New_York', 'tokyo': 'Asia/Tokyo', 'japan': 'Asia/Tokyo',
            'dubai': 'Asia/Dubai', 'uae': 'Asia/Dubai', 'abu dhabi': 'Asia/Dubai', 'sydney': 'Australia/Sydney', 'melbourne': 'Australia/Melbourne', 'paris': 'Europe/Paris', 'france': 'Europe/Paris', 'berlin': 'Europe/Berlin',
            'germany': 'Europe/Berlin', 'mumbai': 'Asia/Kolkata', 'delhi': 'Asia/Kolkata', 'new delhi': 'Asia/Kolkata', 'india': 'Asia/Kolkata', 'bangalore': 'Asia/Kolkata', 'bengaluru': 'Asia/Kolkata', 'pune': 'Asia/Kolkata',
            'kolkata': 'Asia/Kolkata', 'chennai': 'Asia/Kolkata', 'hyderabad': 'Asia/Kolkata', 'singapore': 'Asia/Singapore', 'hong kong': 'Asia/Hong_Kong', 'los angeles': 'America/Los_Angeles', 'la': 'America/Los_Angeles',
            'san francisco': 'America/Los_Angeles', 'seattle': 'America/Los_Angeles', 'california': 'America/Los_Angeles', 'chicago': 'America/Chicago', 'dallas': 'America/Chicago', 'houston': 'America/Chicago',
            'denver': 'America/Denver', 'toronto': 'America/Toronto', 'vancouver': 'America/Vancouver', 'moscow': 'Europe/Moscow', 'russia': 'Europe/Moscow', 'beijing': 'Asia/Shanghai', 'shanghai': 'Asia/Shanghai',
            'china': 'Asia/Shanghai', 'seoul': 'Asia/Seoul', 'korea': 'Asia/Seoul', 'istanbul': 'Europe/Istanbul', 'turkey': 'Europe/Istanbul', 'cairo': 'Africa/Cairo', 'egypt': 'Africa/Cairo',
            'johannesburg': 'Africa/Johannesburg', 'south africa': 'Africa/Johannesburg', 'lagos': 'Africa/Lagos', 'nairobi': 'Africa/Nairobi', 'sao paulo': 'America/Sao_Paulo', 'brazil': 'America/Sao_Paulo',
            'mexico city': 'America/Mexico_City', 'mexico': 'America/Mexico_City', 'bangkok': 'Asia/Bangkok', 'thailand': 'Asia/Bangkok', 'karachi': 'Asia/Karachi', 'pakistan': 'Asia/Karachi', 'dhaka': 'Asia/Dhaka',
            'rome': 'Europe/Rome', 'italy': 'Europe/Rome', 'madrid': 'Europe/Madrid', 'spain': 'Europe/Madrid', 'amsterdam': 'Europe/Amsterdam', 'lisbon': 'Europe/Lisbon', 'dublin': 'Europe/Dublin', 'ireland': 'Europe/Dublin',
            'auckland': 'Pacific/Auckland', 'new zealand': 'Pacific/Auckland', 'honolulu': 'Pacific/Honolulu', 'hawaii': 'Pacific/Honolulu', 'boston': 'America/New_York', 'miami': 'America/New_York',
            'washington': 'America/New_York', 'atlanta': 'America/New_York', 'jakarta': 'Asia/Jakarta', 'manila': 'Asia/Manila', 'kuala lumpur': 'Asia/Kuala_Lumpur', 'riyadh': 'Asia/Riyadh', 'saudi arabia': 'Asia/Riyadh',
            'doha': 'Asia/Qatar', 'qatar': 'Asia/Qatar', 'tel aviv': 'Asia/Jerusalem', 'israel': 'Asia/Jerusalem', 'tehran': 'Asia/Tehran', 'kathmandu': 'Asia/Kathmandu', 'colombo': 'Asia/Colombo', 'zurich': 'Europe/Zurich',
            'vienna': 'Europe/Vienna', 'stockholm': 'Europe/Stockholm', 'oslo': 'Europe/Oslo', 'copenhagen': 'Europe/Copenhagen', 'helsinki': 'Europe/Helsinki', 'athens': 'Europe/Athens', 'warsaw': 'Europe/Warsaw',
            'prague': 'Europe/Prague', 'kyiv': 'Europe/Kyiv', 'kiev': 'Europe/Kyiv', 'buenos aires': 'America/Argentina/Buenos_Aires', 'argentina': 'America/Argentina/Buenos_Aires', 'bogota': 'America/Bogota',
            'lima': 'America/Lima', 'santiago': 'America/Santiago', 'anchorage': 'America/Anchorage', 'utc': 'UTC', 'gmt': 'UTC', 'est': 'America/New_York', 'pst': 'America/Los_Angeles', 'cst': 'America/Chicago',
            'ist': 'Asia/Kolkata', 'bst': 'Europe/London', 'cet': 'Europe/Paris', 'jst': 'Asia/Tokyo', 'aest': 'Australia/Sydney'}
_TIME_IN = re.compile(r"^(?:what|whats) (?:the )?(?:time|is the time|is it)(?: is it| it is)? (?:right now )?(?:in|at over in|over in|for) (?P<c>[a-z .]+?)(?: right now| now| currently| at the moment)?$|^(?:what is |what )?(?:the )?(?:current |local )?time (?:in|at) (?P<c2>[a-z .]+?)(?: right now| now| currently)?$|^what time is it (?:over )?in (?P<c3>[a-z .]+?)$|^(?:tell me )?(?:the )?time (?:in|for) (?P<c4>[a-z .]+?)$|^(?:what is |what is )?(?:the )?time (?:there )?in (?P<c5>[a-z .]+?)$")


def _time_in(s):
    m = _TIME_IN.match(s)
    if not m:
        return None
    city = next(g for g in m.groups() if g).strip()
    city = re.sub(r'^(?:the )', '', city)
    key = city.lower()
    try:
        from zoneinfo import ZoneInfo, available_timezones
        name = _CITY_TZ.get(key)
        if not name:
            want = key.replace(' ', '_')
            name = next((z for z in sorted(available_timezones()) if z.lower().rsplit('/', 1)[-1] == want), None)
        if not name:
            return None
        there = _now_utc().astimezone(ZoneInfo(name))
        here = _now_utc().astimezone(_local_tz())
    except Exception:
        return None
    h = there.hour % 12 or 12
    clock = f"{h}:{there.minute:02d} {'AM' if there.hour < 12 else 'PM'}"
    diff = (there.date() - here.date()).days
    day = ' tomorrow' if diff == 1 else ' yesterday' if diff == -1 else ''
    label = city.upper() if len(city) <= 3 else city.title()
    return f"It's {clock}{day} in {label}{_c()}."


_ADD_EVENT = re.compile(r"^(?:add|put|create|schedule|set up|make|book|block|new|plan|pencil in|set)\b.*\b(?:meeting|event|appointment|call|reminder event|lunch|dinner|interview|catch up|standup|stand up|class|session|calendar|calendar event|block|slot|sync|check in|1 on 1|one on one|dentist|doctor|gym|haircut|flight|trip|party|birthday|breakfast|date|presentation|demo|review)\b|^(?:add|put) .+ (?:to|on|in) (?:my |the )?calendar\b")
_TIME_RX = re.compile(r"\b(?:at |@ )?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>a ?m|p ?m)\b|\bat (?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\b(?! ?(?:minutes|hours|days|percent))|\b(?P<w>noon|midday|midnight)\b")
_DUR_RX = re.compile(r"\bfor (?P<n>\d+(?:\.\d+)?|an?|half an?) ?(?P<u>hours?|hrs?|minutes?|mins?)\b")
_DATE_RX = re.compile(rf"\b(?:today|tonight|tomorrow|day after tomorrow|(?:next |this |on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|(?:on )?(?:{_MON_RX}) \d{{1,2}}(?:st|nd|rd|th)?(?: \d{{4}})?|(?:on )?\d{{1,2}}(?:st|nd|rd|th)? (?:of )?(?:{_MON_RX})(?: \d{{4}})?)\b")


def _clock_from(m):
    if m.group('w'):
        return {'noon': (12, 0), 'midday': (12, 0), 'midnight': (0, 0)}[m.group('w')]
    h = int(m.group('h') or m.group('h2'))
    mn = int(m.group('m') or m.group('m2') or 0)
    ap = (m.group('ap') or '').replace(' ', '')
    if ap == 'pm' and h < 12: h += 12
    elif ap == 'am' and h == 12: h = 0
    elif not ap:   # "at 5" with no am/pm: working hours
        if 1 <= h <= 7: h += 12
        elif h == 12: h = 12
    if h > 23 or mn > 59:
        return None
    return h, mn


def _add_event(s, raw):
    if not _ADD_EVENT.match(s):
        return None
    c = zc._clean(raw)
    if re.search(r'\b(?:every|each|daily|weekly|monthly|yearly|repeat\w*|recurring)\b', c):
        return None   # recurring events need real setup
    today = _today()
    dm = _DATE_RX.search(c)
    when = today
    if dm:
        r = _parse_date(re.sub(r'^on ', '', dm.group(0)), today)
        if not r:
            return None
        when = r[0]
    elif re.search(r'\b(?:every|each|daily|weekly|monthly|repeat)\b', c):
        return None   # recurring events need real setup
    tm = _TIME_RX.search(c)
    if not tm:
        return None
    clk = _clock_from(tm)
    if not clk:
        return None
    start = datetime(when.year, when.month, when.day, clk[0], clk[1])
    mins = 60
    du = _DUR_RX.search(c)
    if du:
        n = du.group('n')
        v = 0.5 if n.startswith('half') else 1.0 if n in ('a', 'an') else float(n)
        mins = int(v * (60 if du.group('u').startswith('h') else 1))
    title = ''
    mt = re.search(r"\b(?:called|named|titled|about|for)\s+(?!\d)(.+?)$", raw.strip(' .?!'), re.I)
    if mt and not re.match(r"(?:\d|an? (?:hour|minute|half)|half an?|the next)", mt.group(1), re.I):
        title = mt.group(1)
    else:
        mn_ = re.search(r"\b(meeting|call|appointment|lunch|dinner|interview|catch up|standup|stand up|class|session|sync|check in|dentist|doctor|gym|haircut|presentation|demo|review|breakfast|party|event)(?: with [A-Za-z]+(?: [A-Za-z]+)?)?", raw, re.I)
        title = mn_.group(0) if mn_ else 'Meeting'
    # cut the date, time and duration words off the title
    title = _DATE_RX.sub(' ', title) if title else title
    title = re.sub(r"\b(?:at |@ )?\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b|\bat \d{1,2}(?::\d{2})?\b|\bnoon\b|\bmidnight\b|\bfor (?:\d+(?:\.\d+)?|an?|half an?) ?(?:hours?|hrs?|minutes?|mins?)\b|\b(?:on|at|to my calendar|in my calendar|on my calendar)\b\s*$", ' ', title, flags=re.I)
    title = re.sub(r"\b(?:on|at)\s*$", '', re.sub(r'\s+', ' ', title)).strip(' ,.-')
    if not title:
        title = 'Meeting'
    title = title.title() if title == title.lower() else title[:1].upper() + title[1:]
    end = start + timedelta(minutes=mins)

    def d_script(var, d):
        return (f'set {var} to current date\nset day of {var} to 1\nset year of {var} to {d.year}\nset month of {var} to {d.month}\nset day of {var} to {d.day}\n'
                f'set hours of {var} to {d.hour}\nset minutes of {var} to {d.minute}\nset seconds of {var} to 0\n')
    script = ('tell application "Calendar"\n' + d_script('s', start) + d_script('e', end) +
              'set cal to missing value\nrepeat with c in calendars\nif writable of c then\nset cal to c\nexit repeat\nend if\nend repeat\n'
              'if cal is missing value then return "nocal"\n'
              f'tell cal to make new event with properties {{summary:"{_q(title)}", start date:s, end date:e}}\nreturn name of cal\nend tell')
    try:
        out = zc._osa(script, 25)
    except RuntimeError:
        return f"I couldn't reach Calendar{_c()}. Allow it in System Settings, Privacy, Calendars."
    if out == 'nocal':
        return f"None of your calendars can take new events{_c()}."
    day = _day_name(when, today)
    return f"Added {title} {day} at {zc._clock(start)}{_c()}."


def _cal_events(frm, to):
    """-> list of (start, end, title, allday) or an error string."""
    data = zc._calendar_events(frm, to)
    if data.get('need') == 'calendar':
        return "I need Calendar access first. Allow it in System Settings, Privacy, Calendars."
    if not data.get('calendars'):
        return ("Your Mac's Calendar has no accounts yet. Add your Google account in System Settings, "
                "Internet Accounts, and I'll read your meetings for free.")
    evs = []
    for e in data.get('events') or []:
        try:
            evs.append((zc._dt(e['start']), zc._dt(e['end']), e.get('title') or 'Untitled', bool(e.get('allDay'))))
        except Exception:
            continue
    return sorted(evs, key=lambda x: x[0])


_CAL_DAY = re.compile(r"^(?:what is|what is|whats|show me|read me|tell me) (?:on |in )?(?:my )?(?:calendar|schedule|agenda|diary)(?: for| on)? (?P<d>.+)$|^(?:what do i have|what have i got|what is up|what is up|what is happening|do i have anything|do i have any (?:meetings|events|plans|appointments)|any (?:meetings|events|plans|appointments)|what meetings do i have|what events do i have|how is my day|how does my day look|what does my day look like|what is my day like) ?(?:on |for )?(?P<d2>tomorrow|today|this week|next week|(?:next |this |on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))$|^(?:what is|what is) (?:my )?(?:day|week) (?:like|look like|looking like) (?P<d3>tomorrow|this week|next week)$|^(?:do i have|got) (?:anything|any meetings|meetings|any events|plans) (?P<d4>tomorrow|this week|on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))$|^(?:what is|what is) (?:my )?(?:calendar|schedule) (?:looking )?like (?P<d5>tomorrow|this week)$|^(?:my )?(?:calendar|schedule|agenda) (?:for )?(?P<d6>tomorrow|this week|next week)$|^(?:read|show) (?:me )?(?:tomorrow s|my) (?:calendar|schedule|meetings)(?: for tomorrow)?$")
_FREE = re.compile(r"^(?:am i|are we|will i be) (?:free|busy|available|around)(?: (?P<d>today|tomorrow|on [a-z]+|this [a-z]+|next [a-z]+|[a-z]+))? (?:at|around|by) (?P<t>.+)$|^(?:do i have|have i got) (?:anything|a meeting|meetings|something|plans) (?:at|around) (?P<t2>.+?)(?: (?P<d2>today|tomorrow|on [a-z]+))?$")


def _calendar_more(s, raw):
    today = _today()
    m = _CAL_DAY.match(s)
    if m:
        g = [x for x in m.groups() if x]
        txt = g[0] if g else 'tomorrow'
        if re.match(r"^(?:read|show) (?:me )?tomorrow", s): txt = 'tomorrow'
        if txt == 'today':
            return None   # zuka_commands handles today
        if txt in ('this week', 'next week'):
            return _cal_range(txt, today)
        r = _parse_date(txt, today)
        if not r:
            return None
        d, _ = r
        return _cal_day(d, today)
    m = _FREE.match(s)
    if m:
        dtxt = m.group('d') or m.group('d2') or 'today'
        r = _parse_date(dtxt, today)
        tm = _TIME_RX.search(zc._clean(m.group('t') or m.group('t2')) + ' ') or _TIME_RX.search('at ' + zc._clean(m.group('t') or m.group('t2')))
        if not r or not tm:
            return None
        clk = _clock_from(tm)
        if not clk:
            return None
        d = r[0]
        start = datetime(d.year, d.month, d.day, clk[0], clk[1]).astimezone()
        evs = _cal_events(start - timedelta(hours=8), start + timedelta(hours=8))
        if isinstance(evs, str):
            return evs
        hits = [e for e in evs if not e[3] and e[0] < start + timedelta(minutes=30) and e[1] > start]
        if hits:
            return f"No, you have {hits[0][2]} then{_c()}."
        return f"Yes, you're free at {zc._clock(start)} {_day_name(d, today)}{_c()}."
    return None


def _cal_day(d, today):
    frm = datetime(d.year, d.month, d.day).astimezone()
    evs = _cal_events(frm, frm + timedelta(days=1))
    if isinstance(evs, str):
        return evs
    day = _day_name(d, today)
    timed = [e for e in evs if not e[3]]
    allday = [e for e in evs if e[3]]
    if not timed and not allday:
        return f"Nothing on your calendar {day}{_c()}."
    bits = [f"{t} at {zc._clock(s0)}" for s0, _, t, _ in timed[:3]]
    out = f"{len(timed)} {'thing' if len(timed) == 1 else 'things'} {day}: " + '; '.join(bits) + (f", plus {len(timed) - 3} more" if len(timed) > 3 else '') if timed else f"No timed meetings {day}"
    if allday:
        out += f". All day: {allday[0][2]}" + (f" and {len(allday) - 1} more" if len(allday) > 1 else '')
    return out + f"{_c()}." if not out.endswith('.') else out


def _cal_range(txt, today):
    start = today if txt == 'this week' else today + timedelta(days=(7 - today.weekday()))
    frm = datetime(start.year, start.month, start.day).astimezone()
    to = frm + timedelta(days=7 if txt == 'this week' else 7)
    evs = _cal_events(max(frm, datetime.now().astimezone()) if txt == 'this week' else frm, to)
    if isinstance(evs, str):
        return evs
    evs = [e for e in evs if not e[3]]
    if not evs:
        return f"Nothing on your calendar {txt}{_c()}."
    top = '; '.join(f"{t} {e0.strftime('%A')} at {zc._clock(e0)}" for e0, _, t, _ in evs[:3])
    return f"{len(evs)} coming up {txt}: {top}" + (f", plus {len(evs) - 3} more" if len(evs) > 3 else '') + f"{_c()}."


# ---------------------------------------------------------------- notes
_NOTE_SAVE = re.compile(r"^(?:take|make|write|jot|save|create|start|add|put|leave) (?:me )?(?:a |an )?(?:quick |new |little |short )?note(?: to self)?(?: that| saying| says| about| for me)?(?::|,)?\s+(?P<n>.+)$|^note to self(?::|,)?\s+(?P<n2>.+)$|^(?:write|jot) (?:this|that|it)(?: down)?(?::|,)?\s+(?P<n3>.+)$|^(?:add|put) (?P<n4>.+?) (?:to|in|into|on) (?:my |the )?(?:notes|notes app|apple notes)$|^(?:write|jot) down(?::|,)?\s+(?P<n6>.+)$|^remember (?:this|to write down)(?::|,)?\s+(?P<n7>.+)$")
_NOTE_NEW = re.compile(r"^(?:create|make|open|start|new|begin) (?:me )?(?:a |an )?(?:new |blank |fresh )?note(?: in notes)?$|^new note$")
_NOTE_READ = re.compile(r"^(?:read|show|open|tell|say) (?:me )?(?:my |the )?(?:last|latest|newest|most recent|recent) note(?:s)?(?: to me| out loud| aloud)?$|^what is (?:in )?(?:my |the )?(?:last|latest|newest|most recent) note$|^what (?:was|is) (?:in )?(?:my |the )?(?:last|latest|newest|most recent) note$|^what did i (?:just )?(?:write|note|jot)(?: down)?(?: last| in my last note)?$|^read (?:me )?(?:my )?notes?$|^what is my (?:last|latest|newest) note$|^what is (?:my )?(?:last|latest|newest) note$|^what is my (?:last|latest|newest) note$|^whats my (?:last|latest|newest|most recent) note$")


def _notes(s, raw):
    r = raw.strip()
    if _NOTE_NEW.match(s):
        zc._osa('tell application "Notes"\nactivate\nmake new note with properties {body:""}\nend tell', 15)
        return f"New note open{_c()}."
    m = _NOTE_SAVE.match(s)
    if m:
        body = None
        mr = re.search(r"(?:note(?: to self)?(?: that| saying| says| about| for me)?|write (?:this|that|it)(?: down)?|jot (?:this|that|it)(?: down)?|note (?:this|that|it)(?: down)?|write down|jot down)\s*(?::|,)?\s+(.+)$", r, re.I)
        if mr:
            body = mr.group(1)
        mr2 = re.search(r"^(?:add|put)\s+(.+?)\s+(?:to|in|into|on)\s+(?:my |the )?(?:notes|notes app|apple notes)$", r.strip(' .'), re.I)
        if mr2:
            body = mr2.group(1)
        body = (body or next((g for g in m.groups() if g), '')).strip(' .')
        body = re.sub(r"^(?:that |to )", '', body) if re.match(r"(?i)^(?:that )", body) else body
        if not body or len(body) > 1500 or re.match(r"^(?:this|that|it)$", body.lower()):
            return None
        body = _cap(body)
        html = '<div>' + body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>') + '</div>'
        zc._osa(f'tell application "Notes" to make new note with properties {{body:"{_q(html)}"}}', 15)
        return f"Noted{_c()}. It's in your Notes app."
    if _NOTE_READ.match(s):
        out = zc._osa('tell application "Notes"\nif (count of notes) = 0 then return ""\nreturn plaintext of note 1\nend tell', 15)
        if not out:
            return f"You don't have any notes yet{_c()}."
        return f"Your latest note says: {_clip(out, 400)}"
    return None


# ---------------------------------------------------------------- clipboard
def _clipboard(s, raw):
    if re.match(r"^(?:what is|what is|whats|read|tell me|say|show me|check) (?:me )?(?:what is |what is )?(?:on |in |the contents of )?(?:my |the )?clipboard(?: say| contain| has| contains)?$|^(?:read|tell me|say) (?:me )?(?:my |the )?clipboard(?: to me| out loud| aloud)?$|^what did i (?:just |last )?copy(?: last)?$|^what(?:\'s| is) (?:on )?(?:my |the )?clipboard$|^what(?: have|\'ve) i copied$|^what do i have (?:on|in|copied to) (?:my |the )?clipboard$|^what is currently on (?:my |the )?clipboard$|^what is (?:on|in) (?:my |the )?clipboard$", s):
        r = zc._run(['pbpaste'], 4)
        txt = (r.stdout or '').strip() if r.returncode == 0 else ''
        if not txt:
            return f"Your clipboard has no text on it{_c()}."
        return f"On your clipboard: {_clip(txt, 300)}"
    if re.match(r"^(?:clear|empty|wipe|reset) (?:my |the )?clipboard$", s):
        zc._run(['pbcopy'], 4, '')
        return f"Clipboard cleared{_c()}."
    m = re.search(r"^copy (?:the )?(?:text |words |this text |following )?(?:that says )?(.+?)(?: (?:to|onto|into) (?:my |the )?(?:clipboard|pasteboard))$|^(?:put|place|save) (.+?) (?:on|onto|in|into|to) (?:my |the )?(?:clipboard|pasteboard)$|^copy (?:the )?(?:text|this text|words)(?::|,)? (.+)$", raw.strip(' .?!'), re.I)
    if m and re.match(r"^(?:copy|put|place|save)\b", s):
        txt = next(g for g in m.groups() if g).strip(' "\'')
        if not txt or re.match(r"^(?:this|that|it|the page|the link|the url|the selection|everything|all)$", txt.lower()):
            return None
        zc._run(['pbcopy'], 4, txt)
        return f"Copied that to your clipboard{_c()}."
    return None


# ---------------------------------------------------------------- unit conversion
_UNITS = {}
for _cat, _base, _items in (
    ('len', 'm', {'m': 1, 'meter': 1, 'metre': 1, 'meters': 1, 'metres': 1, 'km': 1000, 'kilometer': 1000, 'kilometre': 1000, 'kilometers': 1000, 'kilometres': 1000, 'kms': 1000, 'cm': 0.01, 'centimeter': 0.01,
                  'centimetre': 0.01, 'centimeters': 0.01, 'centimetres': 0.01, 'mm': 0.001, 'millimeter': 0.001, 'millimetre': 0.001, 'millimeters': 0.001, 'millimetres': 0.001, 'mile': 1609.344, 'miles': 1609.344, 'mi': 1609.344,
                  'foot': 0.3048, 'feet': 0.3048, 'ft': 0.3048, 'inch': 0.0254, 'inches': 0.0254, 'in': 0.0254, 'yard': 0.9144, 'yards': 0.9144, 'yd': 0.9144}),
    ('mass', 'kg', {'kg': 1, 'kilo': 1, 'kilos': 1, 'kilogram': 1, 'kilograms': 1, 'kgs': 1, 'g': 0.001, 'gram': 0.001, 'grams': 0.001, 'lb': 0.45359237, 'lbs': 0.45359237, 'pound': 0.45359237, 'pounds': 0.45359237,
                    'oz': 0.028349523, 'ounce': 0.028349523, 'ounces': 0.028349523, 'stone': 6.35029318, 'stones': 6.35029318, 'tonne': 1000, 'tonnes': 1000, 'ton': 907.18474, 'tons': 907.18474}),
    ('vol', 'l', {'l': 1, 'liter': 1, 'litre': 1, 'liters': 1, 'litres': 1, 'ml': 0.001, 'milliliter': 0.001, 'millilitre': 0.001, 'milliliters': 0.001, 'millilitres': 0.001, 'gallon': 3.785411784, 'gallons': 3.785411784, 'gal': 3.785411784,
                  'cup': 0.2365882365, 'cups': 0.2365882365, 'pint': 0.473176473, 'pints': 0.473176473, 'quart': 0.946352946, 'quarts': 0.946352946, 'fluid ounce': 0.0295735296, 'fluid ounces': 0.0295735296, 'floz': 0.0295735296,
                  'tablespoon': 0.0147867648, 'tablespoons': 0.0147867648, 'tbsp': 0.0147867648, 'teaspoon': 0.00492892159, 'teaspoons': 0.00492892159, 'tsp': 0.00492892159}),
    ('speed', 'mps', {'mph': 0.44704, 'miles per hour': 0.44704, 'kph': 0.277777778, 'kmh': 0.277777778, 'km h': 0.277777778, 'kilometers per hour': 0.277777778, 'kilometres per hour': 0.277777778, 'km per hour': 0.277777778, 'mps': 1,
                      'meters per second': 1, 'metres per second': 1, 'knots': 0.514444444, 'knot': 0.514444444}),
    ('area', 'sqm', {'square meters': 1, 'square metres': 1, 'sqm': 1, 'square feet': 0.09290304, 'square foot': 0.09290304, 'sqft': 0.09290304, 'square kilometers': 1e6, 'square miles': 2589988.11, 'acre': 4046.8564, 'acres': 4046.8564,
                     'hectare': 10000, 'hectares': 10000}),
    ('data', 'b', {'byte': 1, 'bytes': 1, 'kb': 1e3, 'kilobytes': 1e3, 'kilobyte': 1e3, 'mb': 1e6, 'megabytes': 1e6, 'megabyte': 1e6, 'gb': 1e9, 'gigabytes': 1e9, 'gigabyte': 1e9, 'tb': 1e12, 'terabytes': 1e12, 'terabyte': 1e12}),
    ('time', 's', {'second': 1, 'seconds': 1, 'minute': 60, 'minutes': 60, 'hour': 3600, 'hours': 3600, 'day': 86400, 'days': 86400, 'week': 604800, 'weeks': 604800})):
    for _k, _f in _items.items():
        _UNITS[_k] = (_cat, _f)
_TEMPS = {'c': 'c', 'celsius': 'c', 'centigrade': 'c', 'degrees celsius': 'c', 'degree celsius': 'c', 'f': 'f', 'fahrenheit': 'f', 'degrees fahrenheit': 'f', 'degree fahrenheit': 'f', 'k': 'k', 'kelvin': 'k'}
_SAY = {'m': 'meters', 'km': 'kilometers', 'cm': 'centimeters', 'mm': 'millimeters', 'mile': 'miles', 'foot': 'feet', 'inch': 'inches', 'yard': 'yards', 'kg': 'kilograms', 'g': 'grams', 'lb': 'pounds',
        'oz': 'ounces', 'stone': 'stone', 'tonne': 'tonnes', 'ton': 'tons', 'l': 'liters', 'ml': 'milliliters', 'gallon': 'gallons', 'cup': 'cups', 'pint': 'pints', 'quart': 'quarts', 'fluid ounce': 'fluid ounces',
        'tablespoon': 'tablespoons', 'teaspoon': 'teaspoons', 'mph': 'miles per hour', 'kph': 'kilometers per hour', 'mps': 'meters per second', 'knot': 'knots', 'sqm': 'square meters', 'sqft': 'square feet',
        'acre': 'acres', 'hectare': 'hectares', 'byte': 'bytes', 'kb': 'kilobytes', 'mb': 'megabytes', 'gb': 'gigabytes', 'tb': 'terabytes', 'second': 'seconds', 'minute': 'minutes', 'hour': 'hours', 'day': 'days', 'week': 'weeks'}
_CANON = {}
for _k in _UNITS:
    _CANON[_k] = {'meters': 'm', 'meter': 'm', 'metre': 'm', 'metres': 'm', 'kilometer': 'km', 'kilometre': 'km', 'kilometers': 'km', 'kilometres': 'km', 'kms': 'km', 'centimeter': 'cm', 'centimetre': 'cm',
                  'centimeters': 'cm', 'centimetres': 'cm', 'millimeter': 'mm', 'millimetre': 'mm', 'millimeters': 'mm', 'millimetres': 'mm', 'miles': 'mile', 'mi': 'mile', 'feet': 'foot', 'ft': 'foot', 'inches': 'inch',
                  'in': 'inch', 'yards': 'yard', 'yd': 'yard', 'kilo': 'kg', 'kilos': 'kg', 'kilogram': 'kg', 'kilograms': 'kg', 'kgs': 'kg', 'gram': 'g', 'grams': 'g', 'lbs': 'lb', 'pound': 'lb', 'pounds': 'lb',
                  'ounce': 'oz', 'ounces': 'oz', 'stones': 'stone', 'tonnes': 'tonne', 'tons': 'ton', 'liter': 'l', 'litre': 'l', 'liters': 'l', 'litres': 'l', 'milliliter': 'ml', 'millilitre': 'ml', 'milliliters': 'ml',
                  'millilitres': 'ml', 'gallons': 'gallon', 'gal': 'gallon', 'cups': 'cup', 'pints': 'pint', 'quarts': 'quart', 'fluid ounces': 'fluid ounce', 'floz': 'fluid ounce', 'tablespoons': 'tablespoon',
                  'tbsp': 'tablespoon', 'teaspoons': 'teaspoon', 'tsp': 'teaspoon', 'miles per hour': 'mph', 'kmh': 'kph', 'km h': 'kph', 'kilometers per hour': 'kph', 'kilometres per hour': 'kph',
                  'km per hour': 'kph', 'meters per second': 'mps', 'metres per second': 'mps', 'knots': 'knot', 'square meters': 'sqm', 'square metres': 'sqm', 'square feet': 'sqft', 'square foot': 'sqft',
                  'acres': 'acre', 'hectares': 'hectare', 'bytes': 'byte', 'kilobytes': 'kb', 'kilobyte': 'kb', 'megabytes': 'mb', 'megabyte': 'mb', 'gigabytes': 'gb', 'gigabyte': 'gb', 'terabytes': 'tb',
                  'terabyte': 'tb', 'seconds': 'second', 'minutes': 'minute', 'hours': 'hour', 'days': 'day', 'weeks': 'week'}.get(_k, _k)
_UNIT_RX = '|'.join(sorted(list(_UNITS) + list(_TEMPS), key=len, reverse=True))
_NUM = r"(?P<n>-?\d+(?:\.\d+)?|an?|one)"
_CONV = [re.compile(rf"^(?:convert |change |turn )?{_NUM} (?:degrees? )?(?P<a>{_UNIT_RX}) (?:to|into|in|as|is how many|equals? (?:how many )?|are how many|in terms of) (?:degrees? )?(?P<b>{_UNIT_RX})$"),
         re.compile(rf"^(?:how many|how much) (?:degrees? )?(?P<b>{_UNIT_RX}) (?:are |is |in |make up )?(?:there )?(?:are )?(?:in |is |of |to )?{_NUM} (?:degrees? )?(?P<a>{_UNIT_RX})$"),
         re.compile(rf"^(?:what is|what|whats|how much is|how many|how much) (?:is )?{_NUM} (?:degrees? )?(?P<a>{_UNIT_RX}) (?:in|to|into|as) (?:degrees? )?(?P<b>{_UNIT_RX})$"),
         re.compile(rf"^(?:how many|how much) (?:degrees? )?(?P<b>{_UNIT_RX}) (?:is|are) {_NUM} (?:degrees? )?(?P<a>{_UNIT_RX})$"),
         re.compile(rf"^(?:what is|what|whats|how much is|how many is) {_NUM} (?:degrees? )?(?P<a>{_UNIT_RX}) (?:in|to|into) (?:degrees? )?(?P<b>{_UNIT_RX})$"),
         re.compile(rf"^{_NUM} (?:degrees? )?(?P<a>{_UNIT_RX}) (?:in|to|into) (?:degrees? )?(?P<b>{_UNIT_RX})$")]


def _fmt_conv(v):
    return zc._fmt_num(v, 2)


def _convert(s, raw):
    c = zc._clean(raw) if raw else s
    c = re.sub(r'\bdegrees? ', '', c) if re.search(r'\bdegrees? (?:celsius|fahrenheit|kelvin|c|f)\b', c) else c
    c = re.sub(r'^(?:hey |please )+', '', c)
    c = re.sub(r'\b(?:can you|could you|please|tell me|give me)\b ?', '', c).strip()
    c = re.sub(r'\b(?:fahrenheit|celsius)\b', lambda m: m.group(0), c)
    for rx in _CONV:
        m = rx.match(c)
        if not m:
            continue
        n = m.group('n')
        val = 1.0 if n in ('a', 'an', 'one') else float(n)
        a, b = m.group('a'), m.group('b')
        if a in _TEMPS and b in _TEMPS:
            ta, tb = _TEMPS[a], _TEMPS[b]
            if ta == tb:
                continue
            k = val + 273.15 if ta == 'c' else (val - 32) * 5 / 9 + 273.15 if ta == 'f' else val
            out = k - 273.15 if tb == 'c' else (k - 273.15) * 9 / 5 + 32 if tb == 'f' else k
            nm = {'c': 'degrees Celsius', 'f': 'degrees Fahrenheit', 'k': 'kelvin'}
            return f"{zc._fmt_num(val, 2)} {nm[ta]} is {_fmt_conv(out)} {nm[tb]}{_c()}."
        if a in _TEMPS or b in _TEMPS or a not in _UNITS or b not in _UNITS:
            continue
        (ca, fa), (cb, fb) = _UNITS[a], _UNITS[b]
        if ca != cb:
            continue
        ua, ub = _CANON[a], _CANON[b]
        if ua == ub:
            continue
        out = val * fa / fb
        return f"{zc._fmt_num(val, 2)} {_SAY.get(ua, ua) if val != 1 else _singular(_SAY.get(ua, ua))} is {_fmt_conv(out)} {_SAY.get(ub, ub)}{_c()}."
    return None


def _singular(w):
    return {'meters': 'meter', 'kilometers': 'kilometer', 'centimeters': 'centimeter', 'millimeters': 'millimeter', 'miles': 'mile', 'feet': 'foot', 'inches': 'inch', 'yards': 'yard', 'kilograms': 'kilogram',
            'grams': 'gram', 'pounds': 'pound', 'ounces': 'ounce', 'liters': 'liter', 'gallons': 'gallon', 'cups': 'cup', 'pints': 'pint', 'quarts': 'quart', 'hours': 'hour', 'minutes': 'minute', 'seconds': 'second', 'days': 'day', 'weeks': 'week'}.get(w, w)


# ---------------------------------------------------------------- translation (MyMemory, free)
_LANGS = {'hindi': 'hi', 'spanish': 'es', 'french': 'fr', 'german': 'de', 'italian': 'it', 'portuguese': 'pt', 'japanese': 'ja', 'chinese': 'zh-CN', 'mandarin': 'zh-CN', 'korean': 'ko', 'arabic': 'ar', 'russian': 'ru',
          'marathi': 'mr', 'punjabi': 'pa', 'gujarati': 'gu', 'tamil': 'ta', 'telugu': 'te', 'bengali': 'bn', 'urdu': 'ur', 'dutch': 'nl', 'turkish': 'tr', 'greek': 'el', 'thai': 'th', 'indonesian': 'id',
          'vietnamese': 'vi', 'polish': 'pl', 'swedish': 'sv', 'ukrainian': 'uk', 'hebrew': 'he', 'kannada': 'kn', 'malayalam': 'ml', 'nepali': 'ne', 'swahili': 'sw', 'english': 'en', 'danish': 'da', 'norwegian': 'no',
          'finnish': 'fi', 'czech': 'cs', 'romanian': 'ro', 'hungarian': 'hu', 'persian': 'fa', 'filipino': 'tl', 'tagalog': 'tl', 'malay': 'ms'}
_LANG_RX = '|'.join(sorted(_LANGS, key=len, reverse=True))
_TRANS = [re.compile(rf"^(?:translate|say|write|put)(?: this| the phrase| the word| the sentence| the words)?(?: for me)?(?::|,)? (?P<q>.+?) (?:in|into|to|in to|from english to|into the language) (?P<l>{_LANG_RX})$"),
          re.compile(rf"^(?:how do you say|how do i say|how would you say|how to say|how do you write|what is the word for|what is the word for|how do they say|how do we say) (?P<q>.+?) (?:in|into) (?P<l>{_LANG_RX})$"),
          re.compile(rf"^(?:what is|what is|what are) (?P<q>.+?) (?:in|into) (?P<l>{_LANG_RX})$"),
          re.compile(rf"^(?:translate|say) (?:to|into) (?P<l>{_LANG_RX})(?::|,)? (?P<q>.+)$"),
          re.compile(rf"^(?:what is|what is) the (?P<l>{_LANG_RX}) (?:word )?(?:for|translation of) (?P<q>.+)$"), re.compile(rf"^(?:translate|say) (?P<q>.+?) (?:in|to) (?P<l>{_LANG_RX}) please$")]


def _translate(s, raw):
    if not re.search(rf"\b(?:{_LANG_RX})\b", s):
        return None
    m = next((x for x in (rx.match(s) for rx in _TRANS) if x), None)
    if not m:
        return None
    lang = m.group('l')
    q = m.group('q').strip()
    # keep the person's own spelling and punctuation when it is there
    mr = re.search(rf"(?i)(?:translate|say|write|put|say|how do (?:you|i|they|we) say|how would you say|how to say|how do you write|what(?:'s| is| s| are) )(?: this| the phrase| the word| the sentence| the words)?(?: for me)?(?::|,)?\s*(?:the word for )?(.+?)\s+(?:in|into|in to|to)\s+{lang}\b", raw)
    if mr and mr.group(1).strip().lower().replace("'", '') == q.replace("'", ''):
        q = mr.group(1).strip()
    if not q or len(q) > 200 or lang == 'english':
        return None
    if re.search(r'\b(?:this|that|it|clipboard|selection|page)$', q) and len(q.split()) <= 2:
        return None
    url = 'https://api.mymemory.translated.net/get?q=' + urllib.parse.quote(q) + '&langpair=en|' + _LANGS[lang]
    data = zc._get_json(url, 6)
    try:
        out = unescape(data['responseData']['translatedText']).strip()
        if not out or 'MYMEMORY WARNING' in out.upper() or 'SELECT TWO DISTINCT' in out.upper() or int(data.get('responseStatus', 200)) != 200:
            return None
    except Exception:
        return None
    return f"{q} in {lang.title()} is {out}{_c()}."


# ---------------------------------------------------------------- news (free RSS)
_NEWS = re.compile(r"^(?:what is |what is )?(?:the )?(?:latest |top |today s |current |breaking |daily |morning )*(?:news|headlines)(?: headlines)?(?: today| right now| now| this morning)?$|^(?:what is|what is) (?:happening|going on|new)(?: in the world| today| right now| around the world| out there)?$|"
                  r"^(?:read|tell|give|show) (?:me )?(?:the |today s |my |some )?(?:latest |top |breaking |current )*(?:news|headlines)(?: headlines)?(?: today| now| out)?$|^(?:any|got any|is there any|is there) (?:news|new news)(?: today| right now)?$|^(?:what is the |what is the )?news(?: today| now)?$|"
                  r"^(?P<t>tech|technology|business|sports?|science|health|world|uk|india|entertainment|us|politics) news$|^(?:latest|top|breaking) (?P<t2>tech|technology|business|sports?|science|health|world|uk|india|entertainment|us|politics) news$|^(?:what is |what is )?(?:the )?(?:bbc|google|cnn|reuters) news(?: headlines)?$|"
                  r"^(?:read|tell|give|show) (?:me )?(?:the |today s |some )?(?:latest |top |breaking )?(?P<t3>tech|technology|business|sports?|science|health|world|uk|india|entertainment|us|politics) (?:news|headlines)$|^bbc news$|^(?:the )?news$")
_FEEDS = {'tech': 'technology', 'technology': 'technology', 'business': 'business', 'sport': 'sport', 'sports': 'sport', 'science': 'science_and_environment', 'health': 'health', 'world': 'world', 'uk': 'uk',
          'entertainment': 'entertainment_and_arts', 'us': 'world/us_and_canada', 'politics': 'politics', 'india': 'world/asia/india'}


def _news(s):
    m = _NEWS.match(s)
    if not m:
        return None
    topic = next((g for g in m.groupdict().values() if g), None)
    path = _FEEDS.get(topic, '') if topic else ''
    urls = [f"https://feeds.bbci.co.uk/news/{path + '/' if path else ''}rss.xml".replace('//rss', '/rss'), 'https://news.google.com/rss?hl=en&gl=US&ceid=US:en']
    for url in urls:
        txt = zc._get_text(url, 6)
        if not txt:
            continue
        titles = []
        for t in re.findall(r'<item>.*?<title>(.*?)</title>', txt, re.S):
            t = unescape(re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', t)).strip()
            t = re.sub(r'\s+-\s+[^-]{2,40}$', '', t) if 'news.google' in url else t   # Google appends " - Publisher"
            if t and t not in titles:
                titles.append(t)
            if len(titles) == 3:
                break
        if titles:
            return f"Top headlines{' in ' + topic if topic else ''}: " + '. '.join(t.rstrip('.') for t in titles) + '.'
    return None


# ---------------------------------------------------------------- fun: jokes, coin, dice, random numbers, stopwatch
JOKES = ["Why don't scientists trust atoms? They make up everything.", "I told my computer I needed a break, and now it won't stop sending me Kit Kat ads.",
         "Why did the developer go broke? He used up all his cache.", "I'd tell you a UDP joke, but you might not get it.", "Why do Java developers wear glasses? Because they don't C sharp.",
         "What do you call a fake noodle? An impasta.", "Why did the scarecrow win an award? He was outstanding in his field.", "I only know 25 letters of the alphabet. I don't know y.",
         "What's a computer's favorite snack? Microchips.", "Why was the math book sad? It had too many problems.", "I used to hate facial hair, but then it grew on me.",
         "Why don't skeletons fight each other? They don't have the guts.", "What did the ocean say to the beach? Nothing, it just waved.", "Parallel lines have so much in common. It's a shame they'll never meet.",
         "Why did the tomato turn red? It saw the salad dressing."]
FACTS = ["Honey never spoils. Edible honey has been found in ancient Egyptian tombs.", "Octopuses have three hearts and blue blood.", "A day on Venus is longer than its year.",
         "Bananas are berries, but strawberries are not.", "The shortest war in history lasted about 38 minutes, between Britain and Zanzibar in 1896.", "There are more possible chess games than atoms in the observable universe.",
         "Sharks are older than trees.", "A group of flamingos is called a flamboyance.", "Your brain uses about 20 percent of your body's energy.", "Wombat droppings are cube shaped.",
         "The Eiffel Tower grows about 15 centimeters taller in summer because the iron expands.", "Sound travels about four times faster in water than in air."]
QUOTES = ["The only way to do great work is to love what you do. Steve Jobs.", "It always seems impossible until it's done. Nelson Mandela.", "Well done is better than well said. Benjamin Franklin.",
          "Done is better than perfect. Sheryl Sandberg.", "The best way to predict the future is to create it. Peter Drucker.", "You miss one hundred percent of the shots you don't take. Wayne Gretzky.",
          "Courage is not the absence of fear, it's acting in spite of it. Mark Twain.", "What we do every day matters more than what we do once in a while. Gretchen Rubin."]
BALL = ["It is certain.", "Without a doubt.", "Yes, definitely.", "Most likely.", "Signs point to yes.", "Ask again later.", "Better not tell you now.", "Don't count on it.", "My sources say no.", "Very doubtful."]
CARDS = ['Ace', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Jack', 'Queen', 'King']
STOPWATCH_FILE = os.path.join(os.environ.get('ATTICUS_DIR') or os.path.join(os.path.expanduser('~'), '.config/atticus'), 'stopwatch.json')


def _stopwatch_state(new=None, clear=False):
    path = STOPWATCH_FILE
    try:
        if clear:
            if os.path.exists(path): os.remove(path)
            return None
        if new is not None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f: json.dump({'start': new}, f)
            return new
        with open(path) as f:
            return float(json.load(f)['start'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _elapsed(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    mn, sc = divmod(rem, 60)
    bits = []
    if h: bits.append(f"{h} hour{'s' if h != 1 else ''}")
    if mn: bits.append(f"{mn} minute{'s' if mn != 1 else ''}")
    if sc or not bits: bits.append(f"{sc} second{'s' if sc != 1 else ''}")
    return ' '.join(bits[:-1]) + (' and ' if len(bits) > 1 else '') + bits[-1] if len(bits) > 1 else bits[0]


def _fun(s, raw):
    if re.match(r"^(?:tell|say|give|got|have you got|do you know|know) (?:me )?(?:a |an |another |any |one |some )?(?:good |funny |dad |bad |new |random |clean )?jokes?(?: please)?$|^(?:another|one more|next) joke$|^joke(?: time)?$|^make me laugh$|^(?:say|tell me) something funny$|^(?:i need|i want|id like) a (?:joke|laugh)$|^cheer me up$", s):
        return random.choice(JOKES)
    if re.match(r"^(?:flip|toss|spin) (?:a |the )?(?:coin|quarter)$|^(?:heads or tails|coin flip|coin toss|flip coin|toss up|call it)$|^(?:do a |make a )?coin (?:flip|toss)$|^heads or tails\??$", s):
        return f"{random.choice(['Heads', 'Tails'])}{_c()}."
    m = re.match(r"^(?:roll|throw|toss) (?:a |an |the |some |two |three |four |\d+ )?(?:(?P<n>\d+|two|three|four|five|six) )?(?:dice|die|d(?P<s>\d+)|(?P<sd>\d+) sided dice|(?P<sd2>\d+) sided die)(?: for me)?$|^roll (?:a )?(?P<n2>two|three|four|five|six|\d+) dice$|^roll (?:the )?dice$|^roll (?P<n3>\d+) dice$", zc._clean(raw))
    if m or re.match(r"^(?:roll|throw) (?:a |the )?(?:dice|die)$", s):
        cc = zc._clean(raw)
        n = 1
        mm = re.search(r"\b(?:roll|throw|toss) (\d+|two|three|four|five|six)\b", cc)
        if mm and mm.group(1).isdigit(): n = int(mm.group(1))
        elif mm: n = {'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}[mm.group(1)]
        elif re.search(r'\bdice\b', cc) and re.search(r'\b(?:two|2)\b', cc): n = 2
        sides = 6
        ms = re.search(r"\bd(\d{1,3})\b|\b(\d{1,3}) sided", cc)
        if ms: sides = int(ms.group(1) or ms.group(2))
        n, sides = max(1, min(n, 10)), max(2, min(sides, 1000))
        rolls = [random.randint(1, sides) for _ in range(n)]
        if n == 1:
            return f"You rolled a {rolls[0]}{_c()}."
        return f"You rolled {', '.join(map(str, rolls[:-1]))} and {rolls[-1]}, that's {sum(rolls)}{_c()}."
    c = zc._clean(raw)
    m = re.match(r"^(?:give me |pick |choose |generate |tell me |say )?(?:me )?(?:a |an )?(?:random )?number(?: (?:between|from) (?P<a>-?\d+) (?:and|to|through|-) (?P<b>-?\d+)| (?:up to|under|below|to) (?P<c>\d+))?(?: please)?$|^random (?:number )?(?:from|between) (?P<a2>-?\d+) (?:and|to) (?P<b2>-?\d+)$|^pick a number (?:between|from) (?P<a3>-?\d+) (?:and|to) (?P<b3>-?\d+)$|^(?:pick|choose|give me) a (?:random )?number$|^(?:random number|random)(?: generator)?$|^pick (?:a )?number(?: (?:from|between) (?P<a4>-?\d+) (?:to|and) (?P<b4>-?\d+))?$", c)
    if m and ('number' in c or c == 'random'):
        g = m.groupdict()
        lo = g.get('a') or g.get('a2') or g.get('a3') or g.get('a4') or '1'
        hi = g.get('b') or g.get('b2') or g.get('b3') or g.get('b4') or g.get('c') or '100'
        lo, hi = int(lo), int(hi)
        if lo > hi: lo, hi = hi, lo
        return f"{random.randint(lo, hi)}{_c()}."
    if re.match(r"^(?:pick|draw|choose|deal) (?:me )?(?:a |one )?(?:random )?card$", s):
        return f"{random.choice(CARDS)} of {random.choice(['hearts', 'spades', 'clubs', 'diamonds'])}{_c()}."
    if re.match(r"^(?:magic |ask the magic )?(?:8|eight) ball\b.*$|^ask the (?:magic )?(?:8|eight) ball\b.*$", s):
        return random.choice(BALL)
    if re.match(r"^(?:tell|give|say|got|share) (?:me )?(?:a |an |another |one |some |any )?(?:fun |random |interesting |cool |good )?fact(?: please)?$|^(?:fun|random|interesting) fact$|^did you know$|^(?:another|one more) fact$|^teach me something$|^surprise me$", s):
        return random.choice(FACTS)
    if re.match(r"^(?:give|tell|say|got|share) (?:me )?(?:a |an |another |one )?(?:good |nice |motivational |inspirational |inspiring |daily )?quote$|^(?:motivate|inspire) me$|^(?:motivational|inspirational|daily) quote$|^quote of the day$", s):
        return random.choice(QUOTES)
    # stopwatch
    if re.match(r"^(?:start|begin|run|set|turn on|fire up|kick off|go)(?: a| the| my| up a)? ?(?:new )?stop ?watch(?: now)?$|^stop ?watch(?: start| go)$|^(?:time me|start timing(?: me)?)$", s):
        _stopwatch_state(new=_epoch())
        return f"Stopwatch running{_c()}."
    if re.match(r"^(?:stop|end|pause|finish|halt|kill)(?: the| my| that| a)? ?stop ?watch$|^stop ?watch(?: stop| end)$|^(?:stop timing(?: me)?|stop the clock)$", s):
        st = _stopwatch_state()
        if st is None:
            return f"No stopwatch is running{_c()}."
        _stopwatch_state(clear=True)
        return f"Stopped at {_elapsed(_epoch() - st)}{_c()}."
    if re.match(r"^(?:what is|what is|whats|check|read|show|tell me|how long is|how long has|how much time is on)(?: me)?(?: the| my)? stop ?watch(?: at| time| been running| on)?$|^how long (?:has|have) (?:the )?stop ?watch (?:been )?(?:running|going)$|^(?:how long|what is the time) (?:is|on) (?:the )?stop ?watch$|^stop ?watch (?:time|check|status)$|^how long has it been$", s):
        st = _stopwatch_state()
        if st is None:
            return f"No stopwatch is running{_c()}."
        return f"{_elapsed(_epoch() - st)}{_c()}."
    if re.match(r"^reset(?: the| my)? stop ?watch$|^(?:restart|clear)(?: the| my)? stop ?watch$|^stop ?watch reset$", s):
        if re.match(r"^(?:restart)", s) or True:
            if s.startswith('restart') or s.startswith('reset'):
                _stopwatch_state(new=_epoch())
                return f"Stopwatch reset and running{_c()}."
        _stopwatch_state(clear=True)
        return f"Stopwatch cleared{_c()}."
    return None


_CAN_DO = re.compile(r"^(?:what can you do|what do you do|what are you able to do|what are your (?:commands|features|skills|abilities|capabilities)|what can i (?:ask|say to|tell) you|what can i say|what can you help (?:me )?with|help|help me|show (?:me )?(?:your )?commands|list (?:your )?commands|what commands do you (?:have|know)|how can you help(?: me)?|what are you capable of|what is your skill set|what are the things you can do|what all can you do)$")


def _what_can_you_do():
    return ("I can open and close apps, move windows, search, play music, set timers and reminders, take notes, check the weather, "
            "battery, storage and Wi-Fi, change brightness, volume and dark mode, convert units, translate, read the news and your calendar, "
            f"add meetings, find files, and flip coins or roll dice, all free on your Mac{_c()}. Just ask.")


# ---------------------------------------------------------------- Reminders lists (shopping, to do)
_LIST_NAMES = {'shopping': ['Shopping', 'Groceries', 'Grocery'], 'grocery': ['Groceries', 'Grocery', 'Shopping'], 'groceries': ['Groceries', 'Grocery', 'Shopping'],
               'to do': ['To Do', 'Todo', 'To-Do', 'Tasks'], 'todo': ['To Do', 'Todo', 'To-Do', 'Tasks'], 'task': ['Tasks', 'To Do', 'Todo']}


def _list_script(kind):
    names = _LIST_NAMES[kind]
    tries = ''.join(f'try\nif L is missing value then set L to first list whose name contains "{n}"\nend try\n' for n in names)
    fallback = 'if L is missing value then set L to default list\n' if kind in ('to do', 'todo', 'task') else ''
    return 'set L to missing value\n' + tries + fallback + 'if L is missing value then return "nolist"\n'


def _lists(s, raw):
    m = re.match(r"^(?:add|put|append) (?P<x>.+?) (?:to|on|onto|in|into) (?:my |the )?(?P<l>shopping|grocery|groceries|to do|todo|task) list$", s)
    if m:
        mr = re.search(r"^(?:add|put|append)\s+(.+?)\s+(?:to|on|onto|in|into)\s+(?:my |the )?(?:shopping|grocery|groceries|to do|todo|to-do|task) list$", raw.strip(' .?!'), re.I)
        item = (mr.group(1) if mr else m.group('x')).strip(' "\'')
        if not item or len(item) > 120 or re.match(r"^(?:this|that|it|them|everything)$", item.lower()):
            return None
        out = zc._osa('tell application "Reminders"\n' + _list_script(m.group('l')) + f'tell L to make new reminder with properties {{name:"{_q(_cap(item))}"}}\nreturn name of L\nend tell', 20)
        if out == 'nolist':
            return f"I couldn't find a {m.group('l')} list in Reminders{_c()}."
        return f"Added {item} to {out}{_c()}."
    m = re.match(r"^(?:what is|what is|whats|read|show me|tell me|check|read me) (?:what is |what is )?(?:on |in )?(?:my |the )?(?P<l>shopping|grocery|groceries|to do|todo|task) list(?: to me)?$", s)
    if m:
        out = zc._osa('tell application "Reminders"\n' + _list_script(m.group('l')) + 'set r to name of (reminders of L whose completed is false)\nset o to ""\nrepeat with x in r\nset o to o & x & "|"\nend repeat\nreturn o\nend tell', 20)
        if out == 'nolist':
            return f"I couldn't find a {m.group('l')} list in Reminders{_c()}."
        items = [x for x in out.split('|') if x.strip()]
        if not items:
            return f"Your {m.group('l')} list is empty{_c()}."
        return f"{len(items)} on your {m.group('l')} list: " + ', '.join(items[:6]) + (f", plus {len(items) - 6} more" if len(items) > 6 else '') + f"{_c()}."
    return None


def _extras(s, raw):
    m = re.match(r"^(?:bring|pull|get|put|show|switch)(?: me)?(?: up)? (?P<a>[a-z0-9][a-z0-9 ]*?) (?:to the front|in front|to the foreground|up front|on top)$|^(?:bring|pull) (?:up )?(?P<a2>[a-z0-9][a-z0-9 ]*?) (?:to the front|forward)$", s)
    if m:
        name = (m.group('a') or m.group('a2')).strip()
        if name and not re.search(r'\b(this|that|it|them|window|tab|page|all|everything)\b', name):
            if zc._open_app(name.title() if name == name.lower() and len(name.split()) > 1 else name):
                return f"Bringing {name.title() if name == name.lower() else name} to the front{_c()}."
        return None
    m = re.match(r"^(?:go|switch|jump|move) to (?:the )?(?P<n>first|second|third|fourth|fifth|sixth|seventh|eighth|last) tab$|^(?:go|switch|jump) to tab (?P<d>[1-9])$", s)
    if m:
        n = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5, 'sixth': 6, 'seventh': 7, 'eighth': 8, 'last': 9}.get(m.group('n') or '') or int(m.group('d'))
        b = zc._browser()
        zc._osa(f'tell application "{b}" to activate\n' + _se(f'keystroke "{n}" using command down'))
        return f"Switched tab{_c()}."
    if re.match(r"^(?:show|open|pull up|bring up|find) (?:me )?(?:my |the )?(?:recent|recents|recent files|recent documents|recently opened files)$", s):
        zc._osa('tell application "Finder" to activate')
        zc._osa(_se('keystroke "f" using {command down, shift down}'))
        return f"Showing your recent files in Finder{_c()}."
    return None


# ---------------------------------------------------------------- screen time + "summarize my day" (Screen Time db and Zuka's own log; all on this Mac)
_SCREEN = re.compile(r"^(?:(?:what is|whats|show|check|tell me|give me|read) )?(?:my )?screen ?time(?: (?:today|so far|for today))?$|"
                     r"^how (?:long|much time|many hours|many minutes) (?:was i|have i been|did i spend|have i spent|am i|did i use|have i used|did i (?:stay|stayed))(?: (?:on|in|using|at))? (?P<app>[a-z0-9 ]+?)(?: today| so far)?$")
_DAYSUM = re.compile(r"^(?:summari[sz]e|recap|sum up|wrap up) (?:my |the )?(?:day|today)(?: so far)?$|^what did i (?:do|get done|work on|finish|achieve)(?: so far)?(?: today)?$|"
                     r"^(?:how was|how s) my day(?: so far)?$|^(?:my )?day (?:summary|recap|so far)$|^what have i (?:done|been doing)(?: today| so far)?$")
_TASK_SAY = {'clickup check': 'ClickUp checks', 'music': 'music', 'messages': 'messages', 'reminders': 'reminders', 'start day': 'starting your day', 'edit mode': 'editing',
             'weather': 'weather', 'calendar': 'your calendar', 'time': 'the time', 'open app': 'opening apps', 'close apps': 'closing apps', 'volume/system': 'Mac settings'}
_SITES = {'instagram', 'youtube', 'facebook', 'twitter', 'x', 'linkedin', 'reddit', 'netflix', 'gmail', 'chatgpt', 'whatsapp web', 'tiktok', 'amazon'}


def _list_say(xs):
    return xs[0] if len(xs) == 1 else ', '.join(xs[:-1]) + ' and ' + xs[-1]


def _hm(secs):
    h, m = divmod(int(secs) // 60, 60)
    return ' '.join(x for x in (f"{h} hour{'s' if h != 1 else ''}" if h else '', f"{m} minute{'s' if m != 1 else ''}" if m else '') if x) or 'under a minute'


def _top_apps(per, n=3):
    import zuka_learn as zl
    return [(zl.app_name(b) or b.split('.')[-1].title(), v) for b, v in sorted(per.items(), key=lambda x: -x[1])[:n] if v >= 60]


def _screen_time(s):
    import zuka_learn as zl
    m = _SCREEN.match(s)
    if not m:
        return None
    per, ok = zl.usage_today()
    if not ok:
        return f"I can't read Screen Time on this Mac{_c()}. {zc.NAME()} needs Full Disk Access for that."
    total = sum(per.values())
    if total < 60:
        return f"I don't see any app usage for today yet{_c()}."
    app = (m.groupdict().get('app') or '').strip()
    if app and app not in ('my mac', 'mac', 'the mac', 'my computer', 'computer', 'my laptop', 'laptop', 'my phone'):
        words = [w for w in app.split() if w not in ('the', 'my', 'app')]
        hit = sum(v for b, v in per.items() if words and all(w in ((zl.app_name(b) or '') + ' ' + b).lower() for w in words))
        if hit >= 60:
            return f"You've spent {_hm(hit)} on {app.title()} today{_c()}."
        if app in _SITES:   # Screen Time lists apps, not websites: the browser is the closest honest answer
            br = sorted(((v, zl.app_name(b) or b) for b, v in per.items() if b.lower() in zl.BROWSER_BUNDLES), reverse=True)
            return (f"Screen Time only tracks apps, not sites{_c()}. {br[0][1]} was open for {_hm(br[0][0])} today." if br and br[0][0] >= 60 else
                    f"Screen Time only tracks apps, not sites{_c()}, and I don't see a browser in today's usage.")
        return f"I don't see {app} in today's usage{_c()}."
    top = _top_apps(per)
    return f"Your screen time today is {_hm(total)}{_c()}. Top apps: {_list_say([f'{n}, {_hm(v)}' for n, v in top])}."


def _day_summary(s):
    import zuka_learn as zl
    if not _DAYSUM.match(s):
        return None
    tasks = [(t, k) for t, k in zl.today_tasks() if not _DAYSUM.match(zc._norm(t))]
    per, ok = zl.usage_today()
    bits = []
    if tasks:
        cnt = {}
        for _, k in tasks: cnt[k] = cnt.get(k, 0) + 1
        top = [_TASK_SAY[k] for k, _ in sorted(((k, c) for k, c in cnt.items() if k), key=lambda x: -x[1])[:3]]
        bits.append(f"Today you've asked me {len(tasks)} thing{'s' if len(tasks) != 1 else ''}" + (f", mostly {_list_say(top)}" if top else '') + f"{_c()}.")
    total = sum(per.values())
    if ok and total >= 60:
        top = [f"{n}" for n, _ in _top_apps(per)]
        bits.append(f"You've been on your Mac for {_hm(total)}, mostly in {_list_say(top)}.")
    return ' '.join(bits) or f"I don't have anything logged for today yet{_c()}."


# ---------------------------------------------------------------- entry
_MATCHERS = (
    lambda s, raw: _screen_time(s),
    lambda s, raw: _day_summary(s),
    lambda s, raw: _what_can_you_do() if _CAN_DO.match(s) else None,
    lambda s, raw: _apps_and_windows(s),
    lambda s, raw: _system(s),
    lambda s, raw: _media(s, raw),
    lambda s, raw: _browser_ui(s, raw),
    lambda s, raw: _files(s, raw),
    lambda s, raw: _people(s, raw),
    lambda s, raw: _add_event(s, raw),
    lambda s, raw: _calendar_more(s, raw),
    lambda s, raw: _extras(s, raw),
    lambda s, raw: _lists(s, raw),
    lambda s, raw: _notes(s, raw),
    lambda s, raw: _clipboard(s, raw),
    lambda s, raw: _time_in(s),
    lambda s, raw: _dates(s, raw),
    lambda s, raw: _convert(s, raw),
    lambda s, raw: _translate(s, raw),
    lambda s, raw: _news(s),
    lambda s, raw: _fun(s, raw),
)


# ---- YouTube / YouTube Music as the player (when Apple Music or Spotify isn't running)
_YT_CMDS = [
    (re.compile(r"^(?:pause|stop|hold)(?: the| this)? (?:music|song|track|video|youtube)$|^pause(?: it| youtube)?$|^stop it$"), "pause",
     "(function(){var v=document.querySelector('video');if(!v)return 'none';v.pause();return 'ok'})()", "Paused{c}."),
    (re.compile(r"^(?:play|resume|continue|unpause)(?: the| this)? (?:music|song|track|video|youtube)$|^(?:resume|unpause|play it|continue playing)$"), "play",
     "(function(){var v=document.querySelector('video');if(!v)return 'none';v.play();return 'ok'})()", "Playing{c}."),
    (re.compile(r"^(?:next|skip)(?: the| this)? (?:song|track|video)$|^skip(?: this| it)?$|^next(?: one)?$|^play (?:the )?next (?:song|one|video)$"), "next",
     "(function(){var b=document.querySelector('.next-button, .ytp-next-button');if(b){b.click();return 'ok'}return 'none'})()", "Next one{c}."),
    (re.compile(r"^(?:previous|last|go back a|back a)(?: the)? (?:song|track|video)$|^play the previous (?:song|track|video)$|^(?:previous|go back|previous one|last one)$"), "previous",
     "(function(){var b=document.querySelector('.previous-button, .ytp-prev-button');var v=document.querySelector('video');if(b&&b.offsetParent){b.click();return 'ok'}if(v){v.currentTime=0;return 'ok'}return 'none'})()", "Going back{c}."),
    (re.compile(r"^(?:no )?(?:play (?:it|this|that|the song|the video) again|replay(?: it| this| the song| the video)?|restart (?:the |this )?(?:song|video|track)|start (?:it |the song |this )?(?:over|from the (?:start|beginning))|again)$"), "replay",
     "(function(){var v=document.querySelector('video');if(!v)return 'none';v.currentTime=0;v.play();return 'ok'})()", "From the top{c}."),
    (re.compile(r"^(?:what(?:s| is) (?:this song|playing|this)|which song is (?:this|playing)|what song is (?:this|playing))$"), "what",
     "(function(){var t=document.querySelector('.title.ytmusic-player-bar, h1.ytd-watch-metadata, #title h1');return t?t.innerText.trim():document.title.replace(/ - YouTube( Music)?$/,'')})()", None),
]


_YT_WHAT = next(js for _, k, js, _ in _YT_CMDS if k == 'what')
_APP_KINDS = {'next': 'next track', 'previous': 'previous track', 'replay': None}   # skip / back / again on Music or Spotify (AppleScript)


def _yt_exec(js):
    """(host, out) from the first YouTube tab that answers js; (None, None) when there is no tab or no browser."""
    b = zc._workflow()['browser']
    for host in ('music.youtube.com', 'youtube.com/watch', 'youtube.com'):
        try: out = zc._tab_exec(b, host, js)
        except Exception: continue
        if out == 'NOBROWSER': return None, None
        if out not in ('NOTAB', 'none', '', None): return host, out
    return None, None


def _app_ctl(kind, a):
    if kind == 'replay':
        zc._osa(f'tell application "{a}" to set player position to 0', 6)
        zc._osa(f'tell application "{a}" to play', 6)
    else:
        zc._osa(f'tell application "{a}" to {_APP_KINDS[kind]}', 8)


def _youtube_player(s, raw=''):
    for rx, kind, js, reply in _YT_CMDS:
        if not rx.match(s): continue
        apps = bool(_players())
        if apps and kind not in _APP_KINDS and kind != 'what': return None   # a music app is running: its own controls answer
        a = _playing() if apps and kind in _APP_KINDS else None
        if a:   # skip / back / replay: the app that is playing
            _app_ctl(kind, a)
            return reply.format(c=zc.call_suffix())
        host, out = _yt_exec(js)
        if host:
            return f"That's {out}{zc.call_suffix()}." if kind == 'what' else reply.format(c=zc.call_suffix())
        if apps and kind in _APP_KINDS and _player():   # nothing playing and no YouTube tab: still drive the open app
            _app_ctl(kind, _player())
            return reply.format(c=zc.call_suffix())
        return None
    return None


def handle(t, raw=''):
    """A short spoken reply, or None when this isn't something the Mac can do for free (or it isn't sure)."""
    try:
        raw = raw if isinstance(raw, str) and raw.strip() else (t if isinstance(t, str) else '')
        # the same filler stripped from the raw words, so names and emails keep their spelling
        raw = re.sub(r"(?i)^(?:(?:hey|ok|okay|um+|uh+|zuka|please|kindly|just|so|and|then|also|go ahead and|(?:can|could|would|will) (?:you|u)(?: please)?|i (?:want|need|would like|wanna) you to|i want to|i wanna|lets|you can|you could|i'd like you to)[ ,]+)+", '', raw.strip())
        raw = re.sub(r"(?i)(?:[ ,]+(?:please|for me|right now|real quick|quickly|thanks|thank you|if you can))+[ .!?]*$", '', raw).strip()
        s = _tidy(t)
        if not s:
            return None
        for fn in [_youtube_player] + list(_MATCHERS):
            r = fn(s, raw)
            if r:
                return r
        return None
    except Exception:
        return None
