"""Free (no-AI) one-phrase commands for Zuka. Public API: handle(t) -> str | None.

t is the already-normalised lowercase request. Returns a short spoken reply, or None
when the phrase is not one of these commands. Never raises.
"""
import copy
import functools
import json
import os
import re
import shutil
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

APP = os.path.expanduser('~/Applications/Atticus.app/Contents/MacOS/Atticus')
VIDEO_EXT = ('.mp4', '.mov')
WORKFLOW = os.path.expanduser('~/.config/atticus/workflow.json')   # per-person setup; see workflow.example.json

# Browsers Zuka can drive. Chromium ones share one AppleScript dictionary; Safari differs (tab name, current tab).
BROWSER_IDS = {'com.brave.browser': 'Brave Browser', 'com.google.chrome': 'Google Chrome',
               'company.thebrowser.browser': 'Arc', 'com.microsoft.edgemac': 'Microsoft Edge',
               'com.apple.safari': 'Safari'}
BROWSER_SHORT = {'Brave Browser': 'Brave', 'Google Chrome': 'Chrome', 'Microsoft Edge': 'Edge'}
CHROMIUM = ('Brave Browser', 'Google Chrome', 'Arc', 'Microsoft Edge')

# What a person with no workflow.json gets: nothing work-specific.
DEFAULTS = {
    'browser': None,   # None = the Mac's default browser
    'tools': {'gmail': ['Gmail', 'https://mail.google.com'],
              'whatsapp': ['WhatsApp', 'https://web.whatsapp.com'],
              'drive': ['Drive', 'https://drive.google.com'],
              'chatgpt': ['ChatGPT', 'https://chatgpt.com']},
    'startDay': {'sites': ['gmail'], 'apps': [], 'openTaskFolder': False},
    'editMode': {'apps': [], 'openTaskFolder': False},
    'tasks': None,     # None = task folders not set up
    'music': 'top hits mix',   # what "play a song" puts on when no song is named (YouTube search words)
}
TASK_DEFAULTS = {'folder': None, 'nameFormat': '{date}_{batch}_{name}_{type}', 'dateFormat': '%d%b%y',
                 'types': {}, 'defaultType': 'Video', 'subfolders': [], 'exports': {}}
NO_TASKS = "Task folders aren't set up for you yet, J. You can set them up in your setup."
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


@functools.lru_cache(maxsize=1)
def _default_browser():
    """The Mac's default browser (https handler) as an app name; Safari if unknown."""
    try:
        out = _run(['defaults', 'read', 'com.apple.LaunchServices/com.apple.launchservices.secure', 'LSHandlers'], 5).stdout or ''
        for blk in re.findall(r'\{[^{}]*\}', out):
            if re.search(r'LSHandlerURLScheme\s*=\s*"?https"?\s*;', blk):
                m = re.search(r'LSHandlerRole(?:All|Viewer)\s*=\s*"?([\w.\-]+)"?\s*;', blk)
                if m and m.group(1).lower() in BROWSER_IDS:
                    return BROWSER_IDS[m.group(1).lower()]
    except Exception:
        pass
    return 'Safari'


def _str_list(v):
    return [x for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []


def _workflow():
    """This person's setup from WORKFLOW merged over DEFAULTS. Never raises; bad or missing file = defaults."""
    try:
        with open(WORKFLOW) as f:
            data = json.load(f)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    w = copy.deepcopy(DEFAULTS)
    b = data.get('browser')
    w['browser'] = b.strip() if isinstance(b, str) and b.strip() else _default_browser()
    if isinstance(data.get('music'), str) and data['music'].strip(): w['music'] = data['music'].strip()
    tools = data.get('tools')
    if isinstance(tools, dict):
        w['tools'] = {str(k).lower().strip(): [v[0], v[1]] for k, v in tools.items()
                      if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, str) and x for x in v)}
    for key, bools in (('startDay', ('sites', 'apps')), ('editMode', ('apps',))):
        d = data.get(key)
        if isinstance(d, dict):
            for k in bools:
                if k in d and isinstance(d[k], list):
                    w[key][k] = [x for x in d[k] if isinstance(x, str) or (isinstance(x, list) and len(x) == 2)] if k == 'sites' else _str_list(d[k])
            if isinstance(d.get('openTaskFolder'), bool):
                w[key]['openTaskFolder'] = d['openTaskFolder']
    t = data.get('tasks')
    if isinstance(t, dict) and isinstance(t.get('folder'), str) and t['folder'].strip():
        tk = copy.deepcopy(TASK_DEFAULTS)
        tk['folder'] = Path(os.path.expanduser(t['folder'].strip()))
        for k in ('nameFormat', 'dateFormat', 'defaultType'):
            if isinstance(t.get(k), str) and t[k].strip():
                tk[k] = t[k].strip()
        if '{batch}' not in tk['nameFormat']:
            tk['nameFormat'] = TASK_DEFAULTS['nameFormat']
        if isinstance(t.get('types'), dict):
            tk['types'] = {str(k).lower().replace(' ', ''): str(v) for k, v in t['types'].items() if v}
        tk['subfolders'] = _str_list(t.get('subfolders'))
        if isinstance(t.get('exports'), dict):
            tk['exports'] = {str(k): v for k, v in t['exports'].items() if isinstance(v, str) and v.strip()}
        w['tasks'] = tk
    return w


def _browser():
    return _workflow()['browser']


def _short(b):
    return BROWSER_SHORT.get(b, b)


def _is_safari(b):
    return b.lower().startswith('safari')


def _app_short(name):
    """'Adobe Foo Pro 2026' -> 'Foo' for speech."""
    n = re.sub(r'^Adobe\s+', '', name.strip())
    n = re.sub(r'\s+\d{4}$', '', n)
    return re.sub(r'\s+Pro$', '', n) or name


def _open_browser(url):
    return _run(['open', '-a', _browser(), url], 10).returncode == 0


def _task_re(tk):
    """Regex for a task folder name under the configured nameFormat (group 'batch')."""
    fmt = tk['nameFormat']
    fmt = fmt[:fmt.index('{batch}') + len('{batch}')]
    date = ''.join({'d': r'\d{2}', 'b': '[A-Za-z]{3}', 'B': '[A-Za-z]+', 'y': r'\d{2}', 'Y': r'\d{4}', 'm': r'\d{2}',
                    'j': r'\d{3}', 'a': '[A-Za-z]{3}', 'A': '[A-Za-z]+'}.get(c, '[^_]+?') if prev == '%' else ('' if c == '%' else re.escape(c))
                   for prev, c in zip(' ' + tk['dateFormat'], tk['dateFormat']))
    out, i = '', 0
    for m in re.finditer(r'\{(\w+)\}', fmt):
        out += re.escape(fmt[i:m.start()])
        out += {'date': date, 'batch': r'(?P<batch>\d+)'}.get(m.group(1), '.+?')
        i = m.end()
    return re.compile('^' + out + re.escape(fmt[i:]) + '.+$')


def _newest_task_folder():
    tk = _workflow()['tasks']
    if not tk:
        return None
    try:
        rx = _task_re(tk)
        dirs = [p for p in tk['folder'].iterdir() if p.is_dir() and rx.match(p.name)]
    except OSError:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _batch_of(folder):
    m = _task_re(_workflow()['tasks']).match(folder.name)
    return m.group('batch') if m else folder.name


def _open_folder(p):
    return _run(['open', str(p)], 10).returncode == 0


def _num(n):
    return f'{n:,}'


# ---------------------------------------------------------------- browser tabs
def _titles_script(b, cond=None):
    """AppleScript listing tab titles (one per line); cond = optional host filter on the tab URL."""
    tw = 'name' if _is_safari(b) else 'title'
    body = ('  repeat with ti in (get %s of every tab of w)\n   set out to out & ti & linefeed\n  end repeat\n' % tw) if not cond else \
           ('  repeat with tb in tabs of w\n   if (URL of tb) contains "%s" then set out to out & (%s of tb) & linefeed\n  end repeat\n' % (cond, tw))
    return ('if application "%s" is not running then return ""\nset out to ""\ntell application "%s"\n'
            ' repeat with w in windows\n%s end repeat\nend tell\nreturn out' % (b, b, body))


def _browser_titles():
    """Titles of every tab in the browser (one per line). [] if it isn't running."""
    out = _osa(_titles_script(_browser()))
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
        return f"Neither WhatsApp nor Gmail is open in {_short(_browser())}. Say open whatsapp, or open gmail."
    text = parts[0][0].upper() + parts[0][1:]
    if len(parts) > 1:
        text += ', ' + ', '.join(parts[1:-1]) + (', ' if len(parts) > 2 else '') + 'and ' + parts[-1]
    text += '.'
    if missing:
        text += f" {' and '.join(missing)} isn't open. Say open {missing[0].lower()}."
    return text


def _cheap_unread():
    try:
        info = _parse_titles(_browser_titles())
        if info['whatsapp'] is None and not info['gmail']:
            return ''
        return ' ' + _unread_reply(info)
    except Exception:
        return ''


def _focus_script(b, host):
    if _is_safari(b):
        head, guard, tail = ' repeat with wi from 1 to (count of windows)\n  set w to window wi\n', '', ''
        sel = '     set current tab of w to tab ti of w\n'
        loop = '   repeat with ti from 1 to (count of tabs of w)\n'
    else:
        head = ' repeat with wi from 1 to (count of windows)\n  set w to window wi\n  if (count of tabs of w) > 1 then\n'
        tail = '  end if\n'
        sel = '     set active tab index of w to ti\n'
        loop = '   repeat with ti from 1 to (count of tabs of w)\n'
    return ('if application "%s" is not running then return "none"\ntell application "%s"\n' % (b, b) + head + loop +
            f'    if (URL of tab ti of w) contains "{host}" then\n' + sel +
            '     set index of w to 1\n     activate\n     return "found"\n    end if\n   end repeat\n' + tail +
            ' end repeat\nend tell\nreturn "none"')


def _focus_or_open(host, url):
    try:
        if _osa(_focus_script(_browser(), host)) == 'found':
            return True
    except Exception:
        pass
    return _open_browser(url)


# ---------------------------------------------------------------- commands
_START = re.compile(r"^(start (my|the) (day|work)|start work|lets (start|begin)( (work|the day|my day|working))?|"
                    r"(good )?morning( lets)?( start| begin| setup| set up| routine)( work| my day| the day)?|"
                    r"morning (setup|set up|routine)|begin (my|the) day|kick ?off (my|the) day)$")
_EDIT = re.compile(r"^(edit mode|lets edit|editing time|time to edit|editing mode|lets get editing)$")
_EXPORT = re.compile(r"^(export check|check (my |the )?exports|how many exports( (are there|do i have|are done))?|exports? count|count (my |the )?exports)$")
def _open_re(tools):
    return re.compile(r"^open (up )?(my |the )?(" + '|'.join(re.escape(k) for k in sorted(tools, key=len, reverse=True)) + r")( tab| site| page| app| website)?$")


_UNREAD = re.compile(r"^(any(thing)? new( messages| mail| emails?)?|(do i have )?any (new |unread )?(messages|mail|emails?|whatsapps?)( for me)?|"
                     r"(check|read) (my )?(whatsapp|gmail|mail|emails?|messages|inbox)( messages| unread)?|unread( messages| mail| emails?)?|"
                     r"how many (unread|new)( messages| mails?| emails?)?( do i have)?|whats new|new (messages|mail|emails?))$")
_CAL_NEXT = re.compile(r"^(whats |what is )?(my |the )?next (meeting|event|call)( is)?( today)?$|^when is my next (meeting|event|call)$")
_CAL_TODAY = re.compile(r"^((whats|what is) )?(on )?(my )?(calendar|schedule|agenda)( for)? today$|^(any |do i have any |what )?(my )?meetings( do i have)?( today)?( do i have)?$|"
                        r"^(whats|what is) (on )?(my )?(calendar|schedule|agenda)( today)?$|^(whats|what is) my (schedule|agenda|calendar)( today)?$|^my (schedule|agenda|meetings)( today)?$")
_NEWTASK = re.compile(r"^(new|create|make|add|start) (a |the )?(new )?task( folder)?( number| #)? ?#?(\d{2,4}) (.+)$")


def _site_ref(w, s):
    if isinstance(s, (list, tuple)) and len(s) == 2:
        return s[0], s[1]
    t = w['tools'].get(str(s).lower())
    return (t[0], t[1]) if t else (None, None)


def _say_list(bits):
    return bits[0] if len(bits) == 1 else ', '.join(bits[:-1]) + ' and ' + bits[-1]


def _start_day():
    w = _workflow()
    sd = w['startDay']
    pre = _cheap_unread()
    bits = []
    for s in sd['sites']:
        label, url = _site_ref(w, s)
        if url:
            _open_browser(url)
            bits.append(label)
    folder = _newest_task_folder() if sd['openTaskFolder'] else None
    if folder:
        _open_folder(folder)
        bits.append(f'your {_batch_of(folder)} folder')
    for a in sd['apps']:
        _open_app(a)
        bits.append(_app_short(a))
    if not bits:
        return "Morning, J. You haven't set up a start-of-day routine yet, but you can in your setup." + pre
    return f"Morning, J. {_say_list(bits)} {'is' if len(bits) == 1 else 'are'} up." + pre


def _edit_mode():
    em = _workflow()['editMode']
    if not em['apps'] and not em['openTaskFolder']:
        return "Edit mode isn't set up for you yet, J. You can set it up in your setup."
    for a in em['apps']:
        _open_app(a)
    names = [_app_short(a) for a in em['apps']]
    folder = _newest_task_folder() if em['openTaskFolder'] else None
    if folder:
        _open_folder(folder)
        return f"Edit mode. {_say_list(names + [f'your {_batch_of(folder)} folder'])} {'is' if len(names) == 0 else 'are'} up."
    verb = 'is' if len(names) == 1 else 'are'
    tail = " I couldn't find a task folder." if em['openTaskFolder'] else ''
    return f"Edit mode. {_say_list(names)} {verb} up.{tail}" if names else "Edit mode." + tail


def _count_videos(d):
    try:
        return sum(1 for f in d.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXT)
    except OSError:
        return None


def _export_check():
    tk = _workflow()['tasks']
    if not tk:
        return NO_TASKS
    if not tk['exports']:
        return "I don't have export folders set up for you yet, J. You can set them in your setup."
    folder = _newest_task_folder()
    if not folder:
        return f"I can't find a task folder in {tk['folder'].name}."
    counts = {label: _count_videos(folder / rel) for label, rel in tk['exports'].items()}
    if all(c is None for c in counts.values()):
        return f"Task {_batch_of(folder)} has no exports folders yet."
    parts = [f'no {label} folder' if c is None else f'{c} in {label}' for label, c in counts.items()]
    return f"Task {_batch_of(folder)}: {', '.join(parts)}."


def _camel(words):
    return ''.join(w[:1].upper() + w[1:] for w in words)


def _unsplit(camel):
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', camel)


def _new_task(m):
    tk = _workflow()['tasks']
    if not tk:
        return NO_TASKS
    batch, rest = m.group(6), m.group(7).split()
    typ = tk['defaultType']
    for n in (3, 2, 1):
        if len(rest) >= n and ''.join(rest[-n:]) in tk['types']:
            typ, rest = tk['types'][''.join(rest[-n:])], rest[:-n]
            break
    if not rest:
        return "What should I call it, J? Say new task, the number, then a name."
    name = _camel(rest)
    now = datetime.now()
    stamp = now.strftime(tk['dateFormat']).upper()
    base = tk['folder']
    folder = base / tk['nameFormat'].format(date=stamp, batch=batch, name=name, type=typ)
    rx = _task_re(tk)
    try:
        dup = [p for p in base.iterdir() if p.is_dir() and (lambda mm: mm and mm.group('batch') == batch)(rx.match(p.name))]
    except OSError:
        dup = []
    if folder.exists() or dup:
        return f"Task {batch} already exists in {base.name}, so I left it alone."
    folder.mkdir(parents=True, exist_ok=True)
    for sub in tk['subfolders']:
        (folder / sub).mkdir(parents=True, exist_ok=True)
    _open_folder(folder)
    return f"Done. Task {batch}, {_unsplit(name)}, is ready in {base.name}."


def _open_tool(key):
    label, url = _workflow()['tools'][key]
    host = re.sub(r'^https?://', '', url).split('/')[0]
    ok = _focus_or_open(host, url)
    return f"{label}'s up." if ok else f"I couldn't open {label}, J."


def _unread():
    try:
        return _unread_reply(_parse_titles(_browser_titles()))
    except Exception:
        sb = _short(_browser())
        return f"I couldn't read your {sb} tabs. Is {sb} open?"


# ---- any site's unread badge: "check linkedin", "any new messages on instagram"
SITES = {'linkedin': ('LinkedIn', 'linkedin.com', 'https://www.linkedin.com/messaging/'),
         'instagram': ('Instagram', 'instagram.com', 'https://www.instagram.com/direct/inbox/'),
         'insta': ('Instagram', 'instagram.com', 'https://www.instagram.com/direct/inbox/'),
         'facebook': ('Facebook', 'facebook.com', 'https://www.facebook.com/'),
         'messenger': ('Messenger', 'messenger.com', 'https://www.messenger.com/'),
         'slack': ('Slack', 'slack.com', 'https://app.slack.com/'),
         'discord': ('Discord', 'discord.com', 'https://discord.com/channels/@me'),
         'twitter': ('X', 'x.com', 'https://x.com/notifications'),
         'telegram': ('Telegram', 'telegram.org', 'https://web.telegram.org/'),
         'whatsapp': ('WhatsApp', 'whatsapp.com', 'https://web.whatsapp.com'),
         'gmail': ('Gmail', 'mail.google.com', 'https://mail.google.com/mail/u/0/#inbox')}


def _sites():
    """Built-in sites plus this person's own tools (so 'check <tool>' reads its badge too)."""
    out = dict(SITES)
    for k, (label, url) in _workflow()['tools'].items():
        host = re.sub(r'^https?://(www\.)?', '', url).split('/')[0]
        out.setdefault(k, (label, host, url))
    return out


def _site_re(sites):
    return re.compile(r"^(?:(?:any(?:thing)? |check |read |see |show |whats )?(?:new |unread )?(?:messages? |notifications? |dms? |mail |updates? )?(?:on |in |from )?(?:my )?)"
                      r"(" + '|'.join(re.escape(k) for k in sorted(sites, key=len, reverse=True)) + r")(?: messages?| notifications?| dms?| inbox| updates?)?(?: for me)?$")


def _tab_titles(host):
    """Titles of browser tabs whose address contains host."""
    return [x.strip() for x in _osa(_titles_script(_browser(), host)).split('\n') if x.strip()]


def _badge(titles):
    for ti in titles:
        m = re.match(r'^\((\d[\d,]*)\+?\)', ti) or re.search(r'\((\d[\d,]*)\)', ti)
        if m: return int(m.group(1).replace(',', ''))
    return 0


def _site(key):
    label, host, url = _sites()[key]
    titles = _tab_titles(host)
    if not titles:   # not open: open it quietly, give it a moment to load its badge, then read
        _open_browser(url)
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
        tools = _workflow()['tools']
        m = _open_re(tools).match(t) if tools else None
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
        sites = _sites()
        m = _site_re(sites).match(t)
        if m and t != m.group(1):   # a bare site name is not a check
            return _site(m.group(1))
        if _CAL_NEXT.match(t):
            return _calendar(False)
        if _CAL_TODAY.match(t):
            return _calendar(True)
        return None
    except Exception:
        return FAIL
