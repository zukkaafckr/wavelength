"""Free (no-AI) one-phrase commands for Zuka. Public API: handle(t) -> str | None.

t is the already-normalised lowercase request. Returns a short spoken reply, or None
when the phrase is not one of these commands. Never raises.
"""
import json
import os
import re
import shutil
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

DOWNLOADS = Path.home() / 'Downloads'
APP = os.path.expanduser('~/Applications/Atticus.app/Contents/MacOS/Atticus')
BRAVE = 'Brave Browser'
PREMIERE = 'Adobe Premiere Pro 2026'
MEDIA_ENCODER = 'Adobe Media Encoder 2026'
TASK_RE = re.compile(r'^\d{2}[A-Z]{3}\d{2}_\d+_.+$')
VIDEO_EXT = ('.mp4', '.mov')
SUBFOLDERS = ['00_Reference/Product', '02_Images', '03_StepCards', '04_VO_Audio/_raw',
              '04_VO_Audio/_timings', '05_Premiere', '05_TextFrames', '06_Exports/Premiere',
              '06_Exports/Submagic']
GMAIL_URL = 'https://mail.google.com/mail/u/0/#inbox'
CLICKUP_URL = 'https://app.clickup.com'
TOOLS = {
    'submagic': ('Submagic', 'https://app.submagic.co'),
    'higgsfield': ('Higgsfield', 'https://higgsfield.ai'),
    'atria': ('Atria', 'https://app.tryatria.com'),
    'clickup': ('ClickUp', 'https://app.clickup.com'),
    'drive': ('Drive', 'https://drive.google.com'),
    'gmail': ('Gmail', 'https://mail.google.com'),
    'whatsapp': ('WhatsApp', 'https://web.whatsapp.com'),
    'chatgpt': ('ChatGPT', 'https://chatgpt.com'),
}
TYPES = {'video': 'Video', 'iteration': 'Iteration', 'hookiteration': 'HookIteration',
         'ugc': 'UGC', 'static': 'Static'}
FAIL = "That one slipped past me, J. Try again in a moment."


# ---------------------------------------------------------------- helpers
def _norm(t):
    t = (t if isinstance(t, str) else '').lower().replace("’", "'")
    t = re.sub(r"\blet'?s\b", 'lets', t)
    t = re.sub(r"\b(what|that|how)'?s\b", r'\1s', t)
    t = re.sub(r"[^a-z0-9#@ ]+", ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _run(args, timeout=10, inp=None):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=inp)


def _osa(script, timeout=8):
    r = _run(['osascript', '-e', script], timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or 'osascript failed').strip())
    return (r.stdout or '').strip()


def _open_app(name):
    return _run(['open', '-a', name], 10).returncode == 0


def _open_brave(url):
    return _run(['open', '-a', BRAVE, url], 10).returncode == 0


def _newest_task_folder():
    try:
        dirs = [p for p in DOWNLOADS.iterdir() if p.is_dir() and TASK_RE.match(p.name)]
    except OSError:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _batch_of(folder):
    return folder.name.split('_')[1]


def _open_folder(p):
    return _run(['open', str(p)], 10).returncode == 0


def _num(n):
    return f'{n:,}'


# ---------------------------------------------------------------- brave tabs
def _brave_titles():
    """Titles of every Brave tab (one per line). [] if Brave isn't running."""
    script = ('if application "Brave Browser" is not running then return ""\n'
              'set out to ""\n'
              'tell application "Brave Browser"\n'
              ' repeat with w in windows\n'
              '  repeat with ti in (get title of every tab of w)\n'
              '   set out to out & ti & linefeed\n'
              '  end repeat\n'
              ' end repeat\n'
              'end tell\n'
              'return out')
    out = _osa(script)
    return [x.strip() for x in out.split('\n') if x.strip()]


def _parse_titles(titles):
    """-> {'whatsapp': int|None, 'gmail': [(name, int)]}. None/[] means tab not open."""
    wa, gm = None, []
    for ti in titles:
        m = re.match(r'^\((\d[\d,]*)\)\s*WhatsApp', ti)
        if m:
            wa = (wa or 0) + int(m.group(1).replace(',', ''))
            continue
        if re.match(r'^WhatsApp\b', ti) and wa is None:
            wa = 0
            continue
        m = re.match(r'^Inbox(?:\s*\((\d[\d,]*)\))?\s*-\s*([^\s@]+)@\S+\s*-\s*Gmail', ti)
        if m:
            n = int(m.group(1).replace(',', '')) if m.group(1) else 0
            gm.append((m.group(2), n))
    return {'whatsapp': wa, 'gmail': gm}


def _unread_reply(info):
    wa, gm = info['whatsapp'], info['gmail']
    parts, missing = [], []
    if wa is None:
        missing.append('WhatsApp')
    else:
        parts.append('nothing unread on WhatsApp' if wa == 0 else f'{_num(wa)} unread on WhatsApp')
    if not gm:
        missing.append('Gmail')
    elif len(gm) == 1:
        n = gm[0][1]
        parts.append('your Gmail inbox is clear' if n == 0 else f'{_num(n)} unread in your Gmail')
    else:
        parts += [(f'{_num(n)} unread in {nm}' if n else f'nothing unread in {nm}') for nm, n in gm]
    if not parts:
        return "Neither WhatsApp nor Gmail is open in Brave. Say open whatsapp, or open gmail."
    text = parts[0][0].upper() + parts[0][1:]
    if len(parts) > 1:
        text += ', ' + ', '.join(parts[1:-1]) + (', ' if len(parts) > 2 else '') + 'and ' + parts[-1]
    text += '.'
    if missing:
        text += f" {' and '.join(missing)} isn't open. Say open {missing[0].lower()}."
    return text


def _cheap_unread():
    try:
        info = _parse_titles(_brave_titles())
        if info['whatsapp'] is None and not info['gmail']:
            return ''
        return ' ' + _unread_reply(info)
    except Exception:
        return ''


def _focus_or_open(host, url):
    script = ('if application "Brave Browser" is not running then return "none"\n'
              'tell application "Brave Browser"\n'
              ' repeat with wi from 1 to (count of windows)\n'
              '  set w to window wi\n'
              '  if (count of tabs of w) > 1 then\n'
              '   repeat with ti from 1 to (count of tabs of w)\n'
              f'    if (URL of tab ti of w) contains "{host}" then\n'
              '     set active tab index of w to ti\n'
              '     set index of w to 1\n'
              '     activate\n'
              '     return "found"\n'
              '    end if\n'
              '   end repeat\n'
              '  end if\n'
              ' end repeat\n'
              'end tell\n'
              'return "none"')
    try:
        if _osa(script) == 'found':
            return True
    except Exception:
        pass
    return _open_brave(url)


# ---------------------------------------------------------------- commands
_START = re.compile(r"^(start (my|the) (day|work)|start work|lets (start|begin)( (work|the day|my day|working))?|"
                    r"(good )?morning( lets)?( start| begin| setup| set up| routine)( work| my day| the day)?|"
                    r"morning (setup|set up|routine)|begin (my|the) day|kick ?off (my|the) day)$")
_EDIT = re.compile(r"^(edit mode|lets edit|editing time|time to edit|editing mode|lets get editing)$")
_EXPORT = re.compile(r"^(export check|check (my |the )?exports|how many exports( (are there|do i have|are done))?|exports? count|count (my |the )?exports)$")
_OPEN = re.compile(r"^open (up )?(my |the )?(" + '|'.join(TOOLS) + r")( tab| site| page| app| website)?$")
_UNREAD = re.compile(r"^(any(thing)? new( messages| mail| emails?)?|(do i have )?any (new |unread )?(messages|mail|emails?|whatsapps?)( for me)?|"
                     r"(check|read) (my )?(whatsapp|gmail|mail|emails?|messages|inbox)( messages| unread)?|unread( messages| mail| emails?)?|"
                     r"how many (unread|new)( messages| mails?| emails?)?( do i have)?|whats new|new (messages|mail|emails?))$")
_CAL_NEXT = re.compile(r"^(whats |what is )?(my |the )?next (meeting|event|call)( is)?( today)?$|^when is my next (meeting|event|call)$")
_CAL_TODAY = re.compile(r"^((whats|what is) )?(on )?(my )?(calendar|schedule|agenda)( for)? today$|^(any |do i have any |what )?(my )?meetings( do i have)?( today)?( do i have)?$|"
                        r"^(whats|what is) (on )?(my )?(calendar|schedule|agenda)( today)?$|^(whats|what is) my (schedule|agenda|calendar)( today)?$|^my (schedule|agenda|meetings)( today)?$")
_NEWTASK = re.compile(r"^(new|create|make|add|start) (a |the )?(new )?task( folder)?( number| #)? ?#?(\d{2,4}) (.+)$")


def _start_day():
    pre = _cheap_unread()
    _open_brave(GMAIL_URL)
    _open_brave(CLICKUP_URL)
    folder = _newest_task_folder()
    if folder:
        _open_folder(folder)
    _open_app(PREMIERE)
    bits = ['Gmail', 'ClickUp'] + ([f'your {_batch_of(folder)} folder'] if folder else []) + ['Premiere']
    return f"Morning, J. {', '.join(bits[:-1])} and {bits[-1]} are up." + pre


def _edit_mode():
    _open_app(PREMIERE)
    _open_app(MEDIA_ENCODER)
    folder = _newest_task_folder()
    if folder:
        _open_folder(folder)
        return f"Edit mode. Premiere, Media Encoder and your {_batch_of(folder)} folder are up."
    return "Edit mode. Premiere and Media Encoder are up. I couldn't find a task folder."


def _count_videos(d):
    try:
        return sum(1 for f in d.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXT)
    except OSError:
        return None


def _export_check():
    folder = _newest_task_folder()
    if not folder:
        return "I can't find a task folder in Downloads."
    a = _count_videos(folder / '06_Exports' / 'Premiere')
    b = _count_videos(folder / '06_Exports' / 'Submagic')
    if a is None and b is None:
        return f"Task {_batch_of(folder)} has no exports folders yet."
    fa = 'no Premiere folder' if a is None else f'{a} in Premiere'
    fb = 'no Submagic folder' if b is None else f'{b} in Submagic'
    return f"Task {_batch_of(folder)}: {fa}, {fb}."


def _camel(words):
    return ''.join(w[:1].upper() + w[1:] for w in words)


def _unsplit(camel):
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', camel)


def _new_task(m):
    batch, rest = m.group(6), m.group(7).split()
    typ = 'Video'
    if len(rest) >= 2 and rest[-2] + rest[-1] == 'hookiteration':
        typ, rest = 'HookIteration', rest[:-2]
    elif len(rest) >= 1 and rest[-1] in TYPES:
        typ, rest = TYPES[rest[-1]], rest[:-1]
    if not rest:
        return "What should I call it, J? Say new task, the number, then a name."
    name = _camel(rest)
    now = datetime.now()
    stamp = f"{now:%d}{now:%b}{now:%y}".upper()
    folder = DOWNLOADS / f"{stamp}_{batch}_{name}_{typ}"
    try:
        dup = [p for p in DOWNLOADS.iterdir() if p.is_dir() and p.name.split('_')[1:2] == [batch]]
    except OSError:
        dup = []
    if folder.exists() or dup:
        return f"Task {batch} already exists in Downloads, so I left it alone."
    for sub in SUBFOLDERS:
        (folder / sub).mkdir(parents=True, exist_ok=True)
    _open_folder(folder)
    return f"Done. Task {batch}, {_unsplit(name)}, is ready in Downloads."


def _open_tool(key):
    label, url = TOOLS[key]
    host = re.sub(r'^https?://', '', url).split('/')[0]
    ok = _focus_or_open(host, url)
    return f"{label}'s up." if ok else f"I couldn't open {label}, J."


def _unread():
    try:
        return _unread_reply(_parse_titles(_brave_titles()))
    except Exception:
        return "I couldn't read your Brave tabs. Is Brave open?"


# ---- any site's unread badge: "check linkedin", "any new messages on instagram"
SITES = {'linkedin': ('LinkedIn', 'linkedin.com', 'https://www.linkedin.com/messaging/'),
         'instagram': ('Instagram', 'instagram.com', 'https://www.instagram.com/direct/inbox/'),
         'insta': ('Instagram', 'instagram.com', 'https://www.instagram.com/direct/inbox/'),
         'facebook': ('Facebook', 'facebook.com', 'https://www.facebook.com/'),
         'messenger': ('Messenger', 'messenger.com', 'https://www.messenger.com/'),
         'slack': ('Slack', 'slack.com', 'https://app.slack.com/'),
         'discord': ('Discord', 'discord.com', 'https://discord.com/channels/@me'),
         'twitter': ('X', 'x.com', 'https://x.com/notifications'),
         'clickup': ('ClickUp', 'clickup.com', 'https://app.clickup.com'),
         'telegram': ('Telegram', 'telegram.org', 'https://web.telegram.org/'),
         'whatsapp': ('WhatsApp', 'whatsapp.com', 'https://web.whatsapp.com'),
         'gmail': ('Gmail', 'mail.google.com', 'https://mail.google.com/mail/u/0/#inbox')}
_SITE = re.compile(r"^(?:(?:any(?:thing)? |check |read |see |show |whats )?(?:new |unread )?(?:messages? |notifications? |dms? |mail |updates? )?(?:on |in |from )?(?:my )?)"
                   r"(" + '|'.join(sorted(SITES, key=len, reverse=True)) + r")(?: messages?| notifications?| dms?| inbox| updates?)?(?: for me)?$")


def _tab_titles(host):
    """Titles of Brave tabs whose address contains host."""
    script = ('if application "Brave Browser" is not running then return ""\n'
              'set out to ""\n'
              'tell application "Brave Browser"\n'
              ' repeat with w in windows\n'
              '  repeat with tb in tabs of w\n'
              f'   if (URL of tb) contains "{host}" then set out to out & (title of tb) & linefeed\n'
              '  end repeat\n'
              ' end repeat\n'
              'end tell\n'
              'return out')
    return [x.strip() for x in _osa(script).split('\n') if x.strip()]


def _badge(titles):
    for ti in titles:
        m = re.match(r'^\((\d[\d,]*)\+?\)', ti) or re.search(r'\((\d[\d,]*)\)', ti)
        if m: return int(m.group(1).replace(',', ''))
    return 0


def _site(key):
    label, host, url = SITES[key]
    titles = _tab_titles(host)
    if not titles:   # not open: open it quietly, give it a moment to load its badge, then read
        _open_brave(url)
        for _ in range(8):
            time.sleep(1)
            titles = _tab_titles(host)
            if titles and _badge(titles): break
        if not titles: return f"I opened {label}, J. It's still loading; ask me again in a second."
    n = _badge(titles)
    if not n: return f"Nothing new on {label}, J."
    return f"{label} shows {_num(n)} new, J." + (" That's messages and notifications together. Want me to read who they're from?" if key == 'linkedin' else '')


# ---- her voice: "voice options", "try the british voice", "keep it"
VOICE_PICK = os.path.expanduser('~/.config/atticus/voice.json')
ZUKA_DIR = os.path.expanduser('~/.local/share/zuka')
VOICES = {'warm': 'warm', 'bright': 'bright', 'smooth': 'smooth', 'calm': 'calm', 'british': 'British', 'indian': 'Indian',
          'jarvis': 'Jarvis', 'deep': 'deep male', 'friendly-male': 'friendly male', 'indian-male': 'Indian male'}
_ALIASES = {'warm': 'warm', 'default': 'warm', 'original': 'warm', 'normal': 'warm', 'usual': 'warm', 'old': 'warm', 'your old': 'warm',
            'bright': 'bright', 'fun': 'bright', 'excited': 'bright', 'smooth': 'smooth', 'calm': 'calm', 'soft': 'calm',
            'british': 'british', 'english': 'british', 'uk': 'british', 'indian': 'indian', 'desi': 'indian', 'indian female': 'indian',
            'jarvis': 'jarvis', 'butler': 'jarvis', 'british male': 'jarvis', 'deep': 'deep', 'deep male': 'deep', 'male deep': 'deep',
            'male': 'friendly-male', 'friendly male': 'friendly-male', 'guy': 'friendly-male', 'boy': 'friendly-male',
            'indian male': 'indian-male', 'desi male': 'indian-male'}
_VOICE_LIST = re.compile(r"^(voice options|(what|which) (other )?voices( (do you have|can you do|are there|you got))?|"
                         r"(list|show)( me)? (your |the )?voices|change (your|the) voice|other voices|your voices)$")
_VOICE_SET = re.compile(r"^(?:try|use|switch to|go back to|change (?:your |the )?voice to|set (?:your |the )?voice to|sound like|speak in|talk in)"
                        r" (?:the |a |an |your )?(.+?)(?: voice| accent| one)?$")
_KEEP = re.compile(r"^(keep (it|this|that|this voice|that voice|this one|that one)|i like (it|this|this one|that one)|perfect keep it|yes keep it)$")


def _pick():
    try:
        with open(VOICE_PICK) as f: return json.load(f)
    except (OSError, ValueError): return {}


def _set_voice(key):
    old = _pick().get('pick', 'warm')
    os.makedirs(os.path.dirname(VOICE_PICK), exist_ok=True)
    with open(VOICE_PICK, 'w') as f: json.dump({'pick': key, 'at': time.time()}, f)
    greet, keep = os.path.join(ZUKA_DIR, 'greetings'), os.path.join(ZUKA_DIR, 'greetings-original')
    maker = os.path.join(ZUKA_DIR, 'greetings-maker', 'make-greetings.py')
    if key != old and os.path.isdir(greet):
        if not os.path.isdir(keep): shutil.copytree(greet, keep)   # the greetings she was set up with, kept once
        if key == 'warm':   # back to her own voice: her original greetings, not a re-recording
            shutil.rmtree(greet); shutil.copytree(keep, greet)
        elif os.path.exists(maker):   # re-record the greetings in the new voice once the sample has played
            subprocess.Popen(['/bin/sh', '-c', f'sleep 15; exec /usr/bin/python3 -I "{maker}"'], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    label = VOICES[key]
    return f"Okay, this is my {label} voice. Hi J, how do I sound? Say keep it, or try another one."


def _voice_list():
    now = _pick().get('pick', 'warm')
    names = [v + (" (that's me now)" if k == now else '') for k, v in VOICES.items()]
    return "I can sound " + ', '.join(names[:-1]) + ', or ' + names[-1] + ". Say try, and the name."


# ---- calendar
def _dt(s):
    d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    return d.astimezone() if d.tzinfo else d.astimezone()


def _clock(d):
    h = d.hour % 12 or 12
    ap = 'am' if d.hour < 12 else 'pm'
    return f"{h} {ap}" if d.minute == 0 else f"{h}:{d.minute:02d} {ap}"


def _in(delta):
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return 'right now'
    if mins < 60:
        return f"in {mins} minute{'s' if mins != 1 else ''}"
    h, m = divmod(mins, 60)
    if h >= 24:
        return 'tomorrow' if h < 48 else f'in {h // 24} days'
    return f"in {h} hour{'s' if h != 1 else ''}" + (f" {m} minutes" if m else '')


def _calendar_events(frm, to):
    r = _run([APP, '--calendar'], 20, json.dumps({"action": "list", "from": frm.isoformat(timespec='seconds'),
                                                  "to": to.isoformat(timespec='seconds')}))
    data = json.loads(r.stdout or '{}')
    return data


def _calendar(today_only):
    now = datetime.now().astimezone()
    if today_only:
        frm = now.replace(hour=0, minute=0, second=0, microsecond=0)
        to = frm + timedelta(days=1)
    else:
        frm, to = now, now + timedelta(days=7)
    data = _calendar_events(frm, to)
    if data.get('need') == 'calendar':
        return "I need Calendar access first. Allow it in System Settings, Privacy, Calendars."
    if not data.get('calendars'):
        return ("Your Mac's Calendar has no accounts yet. Add your Google account in System Settings, "
                "Internet Accounts, and I'll read your meetings for free.")
    evs = []
    for e in data.get('events') or []:
        try:
            if e.get('allDay'):
                continue
            s, en = _dt(e['start']), _dt(e['end'])
            if en > now:
                evs.append((s, e.get('title') or 'Untitled'))
        except Exception:
            continue
    evs.sort(key=lambda x: x[0])
    if not evs:
        return "Nothing left on your calendar today, J." if today_only else "Nothing on your calendar for the next week."
    if today_only:
        top = evs[:3]
        s = '; '.join(f"{t} at {_clock(d)}" for d, t in top)
        extra = f", plus {len(evs) - 3} more" if len(evs) > 3 else ''
        return f"{len(evs)} left today: {s}{extra}."
    d, t = evs[0]
    when = 'happening now' if d <= now else _in(d - now)
    return f"Next up: {t} at {_clock(d)}, {when}." if d > now else f"{t} is {when}, started at {_clock(d)}."


# ---------------------------------------------------------------- entry
def handle(t):
    try:
        t = _norm(t)
        if not t:
            return None
        if _START.match(t):
            return _start_day()
        m = _NEWTASK.match(t)
        if m:
            return _new_task(m)
        if _EDIT.match(t):
            return _edit_mode()
        if _EXPORT.match(t):
            return _export_check()
        m = _OPEN.match(t)
        if m:
            return _open_tool(m.group(3))
        if _UNREAD.match(t):
            return _unread()
        if _VOICE_LIST.match(t):
            return _voice_list()
        m = _VOICE_SET.match(t)
        if m and m.group(1) in _ALIASES:
            return _set_voice(_ALIASES[m.group(1)])
        if _KEEP.match(t) and time.time() - _pick().get('at', 0) < 600:
            return "Done, J. That's my voice now."
        m = _SITE.match(t)
        if m and t != m.group(1):   # a bare site name is not a check
            return _site(m.group(1))
        if _CAL_NEXT.match(t):
            return _calendar(False)
        if _CAL_TODAY.match(t):
            return _calendar(True)
        return None
    except Exception:
        return FAIL
