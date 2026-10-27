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
    'keepOpen': ['Claude'],    # apps "close all apps" / "done for the day" leave running (the assistant and Finder always stay)
}
TASK_DEFAULTS = {'folder': None, 'nameFormat': '{date}_{batch}_{name}_{type}', 'dateFormat': '%d%b%y',
                 'types': {}, 'defaultType': 'Video', 'subfolders': [], 'exports': {}}
def _setting(key, default):
    """A Settings value read at call time (the assistant's name and what it calls the user live in settings.json)."""
    try:
        path = os.path.join(os.environ.get('ATTICUS_DIR') or os.path.join(os.path.expanduser('~'), '.config/atticus'), 'settings.json')
        with open(path) as f:
            value = json.load(f).get(key)
        return value.strip() if isinstance(value, str) and value.strip() else default
    except (OSError, ValueError, AttributeError):
        return default


def NAME(): return _setting('assistantName', 'Zuka')   # what the assistant is called


def _raw(key):
    try:
        path = os.path.join(os.environ.get('ATTICUS_DIR') or os.path.join(os.path.expanduser('~'), '.config/atticus'), 'settings.json')
        with open(path) as f: return json.load(f).get(key)
    except (OSError, ValueError, AttributeError):
        return None


def _packaged(): return bool(os.environ.get('WAVELENGTH_RUNTIME'))


def CALL():
    """What it calls the user. The packaged app has no default name: '' until its first-run setup is done (setupDone)."""
    name = _setting('userCallName', '' if _packaged() else 'J')
    if name == 'J' and _packaged() and _raw('setupDone') is not True: return ''
    return name


def clean_call(text, call=None):
    """Replies are written as if there is a call name ("Done, {CALL()}."). With none, drop the gap it leaves:
    "Done, ." -> "Done.", "Hey !" -> "Hey!", "Hi , how" -> "Hi, how". Untouched when there is a name."""
    if not isinstance(text, str) or (CALL() if call is None else call): return text
    text = re.sub(r',\s*(?=[.?!])', '', text)       # "Done, ."  "Hello, !"
    text = re.sub(r'[ \t]+(?=[,.?!])', '', text)    # "Hey !"  "Hi , how"
    return re.sub(r'[ \t]{2,}', ' ', text)


def call_suffix():
    """", Sam" to append to a sentence, or '' when there is no call name."""
    return f', {CALL()}' if CALL() else ''


NO_TASKS = "Task folders aren't set up for you yet, {call}. You can set them up in your setup."
FAIL = "That one slipped past me, {call}. Try again in a moment."


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
    if isinstance(data.get('keepOpen'), list): w['keepOpen'] = [x for x in data['keepOpen'] if isinstance(x, str)]
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


def _asks_health(t):
    """Long ways of asking whether she's working ("I want to check if you can access the Mac and everything is right",
    "just checking everything is okay") -> the real local check (internet, voice, Claude sign-in)."""
    if not 6 <= len(t.split()) <= 25 or re.search(r"\b(?:website|site|page|code|video|project|file|email|order|payment|account)\b", t):
        return False
    asks = re.search(r"\b(?:check(?:ing)?|test(?:ing)?|make sure|see if|is|are|everything|all)\b", t)
    state = re.search(r"\b(?:ok|okay|alright|all right|working|right|fine|set ?up|good|access(?: the mac)?|hear me|there)\b", t)
    about = re.search(r"\b(?:you|everything|all|it|this|that|mac|zuka|setup|set up)\b", t)
    return bool(asks and state and about and re.search(r"\b(?:everything|you|zuka|mac|setup|set up|this|that|it)\b.*\b(?:ok|okay|alright|working|right|fine|set ?up|good|access)\b", t))


def _asks_inbox(t):
    """Any natural way of asking whether there are messages ("do you have any messages", "did anyone message me",
    "got any texts", "check my messages please") — but never a request to write or send one."""
    t = re.sub(r"^(?:(?:hey|ok|okay|so|um|uh|please|can you|could you|would you|will you|just|zuka|and)\s+)+", "", t)
    if re.search(r"\b(?:send|write|reply|text (?:him|her|them)|message (?:him|her|them)|tell|say|draft|compose|forward|delete)\b", t):
        return False
    noun = r"(?:messages?|texts?|mails?|e-?mails?|dms?|whatsapps?|notifications?|inbox)"
    if re.search(r"\b(?:the|this|that|these|those)\s+" + noun + r"\b", t):   # one specific message ("who was the email from") is not the inbox summary
        return False
    return bool(re.search(r"\b(?:any|anything|new|unread|check|got|have|did|someone|anyone|who|what|which|read)\b.*\b" + noun + r"\b", t)
                or re.search(r"\bdid (?:anyone|someone|somebody) (?:message|text|mail|email|write to|call) me\b", t)
                or re.fullmatch(r"(?:my )?" + noun + r"(?: please)?", t))


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
        app = _installed_app(s if isinstance(s, str) else '', label)
        if app:   # installed as an app: the app, not a tab
            _open_installed(app); bits.append(label)
        elif url:
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
        return f"Morning, {CALL()}. You haven't set up a start-of-day routine yet, but you can in your setup." + pre
    return f"Morning, {CALL()}. {_say_list(bits)} {'is' if len(bits) == 1 else 'are'} up." + pre


def _edit_mode():
    em = _workflow()['editMode']
    if not em['apps'] and not em['openTaskFolder']:
        return f"Edit mode isn't set up for you yet, {CALL()}. You can set it up in your setup."
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
        return NO_TASKS.format(call=CALL())
    if not tk['exports']:
        return f"I don't have export folders set up for you yet, {CALL()}. You can set them in your setup."
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
        return NO_TASKS.format(call=CALL())
    batch, rest = m.group(6), m.group(7).split()
    typ = tk['defaultType']
    for n in (3, 2, 1):
        if len(rest) >= n and ''.join(rest[-n:]) in tk['types']:
            typ, rest = tk['types'][''.join(rest[-n:])], rest[:-n]
            break
    if not rest:
        return f"What should I call it, {CALL()}? Say new task, the number, then a name."
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


# Tools that are installed as Mac apps open as the app, never a browser tab ("Drive" = the Google Drive app's folder)
_TOOL_APPS = {'slack': 'Slack', 'chatgpt': 'ChatGPT', 'discord': 'Discord', 'spotify': 'Spotify', 'clickup': 'ClickUp',
              'drive': 'Google Drive', 'notion': 'Notion', 'zoom': 'zoom.us', 'teams': 'Microsoft Teams', 'whatsapp': 'WhatsApp',
              'telegram': 'Telegram', 'figma': 'Figma', 'canva': 'Canva', 'capcut': 'CapCut', 'claude': 'Claude'}


def _installed_app(key, label=''):
    """The installed Mac app for this tool, or None (then the website is used)."""
    name = _TOOL_APPS.get(key) or _TOOL_APPS.get((label or '').lower())
    if not name: return None
    for d in ('/Applications', os.path.expanduser('~/Applications'), '/System/Applications'):
        if os.path.isdir(os.path.join(d, name + '.app')): return name
    return None


def _open_installed(app):
    if app == 'Google Drive':   # Drive for desktop: open the synced Drive folder in Finder
        base = os.path.expanduser('~/Library/CloudStorage')
        try: drv = sorted(d for d in os.listdir(base) if d.startswith('GoogleDrive'))
        except OSError: drv = []
        if drv:
            mine = os.path.join(base, drv[0], 'My Drive')
            _run(['open', mine if os.path.isdir(mine) else os.path.join(base, drv[0])], 10); return True
    return _run(['open', '-a', app], 10).returncode == 0


def _open_tool(key):
    label, url = _workflow()['tools'].get(key, (_TOOL_APPS.get(key, key.title()), ''))
    app = _installed_app(key, label)
    if app:
        return f"{label}'s up." if _open_installed(app) else f"I couldn't open {label}, {CALL()}."
    if not url: return None
    host = re.sub(r'^https?://', '', url).split('/')[0]
    ok = _focus_or_open(host, url)
    return f"{label}'s up." if ok else f"I couldn't open {label}, {CALL()}."


WEB = {'youtube': ('YouTube', 'https://www.youtube.com'), 'you tube': ('YouTube', 'https://www.youtube.com'), 'youtube music': ('YouTube Music', 'https://music.youtube.com'),
       'yt music': ('YouTube Music', 'https://music.youtube.com'), 'google drive': ('Google Drive', 'https://drive.google.com'), 'google docs': ('Google Docs', 'https://docs.google.com'),
       'google sheets': ('Google Sheets', 'https://sheets.google.com'), 'google slides': ('Google Slides', 'https://slides.google.com'), 'google meet': ('Google Meet', 'https://meet.google.com'),
       'google': ('Google', 'https://www.google.com'), 'instagram': ('Instagram', 'https://www.instagram.com'), 'insta': ('Instagram', 'https://www.instagram.com'),
       'facebook': ('Facebook', 'https://www.facebook.com'), 'linkedin': ('LinkedIn', 'https://www.linkedin.com'), 'twitter': ('X', 'https://x.com'),
       'netflix': ('Netflix', 'https://www.netflix.com'), 'github': ('GitHub', 'https://github.com'), 'claude': ('Claude', 'https://claude.ai'),
       'figma': ('Figma', 'https://www.figma.com'), 'canva': ('Canva', 'https://www.canva.com'), 'notion': ('Notion', 'https://www.notion.so'),
       'amazon': ('Amazon', 'https://www.amazon.in'), 'flipkart': ('Flipkart', 'https://www.flipkart.com'), 'higgsfield': ('Higgsfield', 'https://higgsfield.ai')}
_OPEN_WEB = re.compile(r"^(?:open|launch|start|go to|pull up|bring up|show|take me to)(?: up)?(?: me)? (?:my |the )?(?P<w>" + '|'.join(re.escape(k) for k in sorted(WEB, key=len, reverse=True)) + r")(?: tab| site| page| website| web| app| dot com)?$")


def _open_web(key):
    """"open YouTube" / "open Google Drive": an installed app of that name if there is one, else the site in the workflow browser (focus the tab if it's open)."""
    label, url = WEB[key]
    app = _installed_app(key, label)
    if app:
        return f"{label}'s up." if _open_installed(app) else f"I couldn't open {label}, {CALL()}."
    host = re.sub(r'^https?://', '', url).split('/')[0]
    return f"{label}'s up." if _focus_or_open(host, url) else f"I couldn't open {label}, {CALL()}."


def _unread():
    try:
        info = _parse_titles(_browser_titles())
        reply = _unread_reply(info)
        try:
            import zuka_apps
            extra = zuka_apps.badge_sentence()
            if extra:
                reply += ' ' + extra
        except Exception:
            pass
        offer = [k for k, v in (('whatsapp', info['whatsapp']), ('gmail', sum(n for _, n in info['gmail']))) if v]
        offer += [k for k in ('slack', 'discord') if re.search(r'\d+ on ' + k + r'\b', reply, re.I)]   # their badge counts are in the reply: reading them is on offer too
        if offer:
            _set_offer(offer)
            reply += OFFER_TEXT
        return reply
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
        if not titles: return f"I opened {label}, {CALL()}. It's still loading; ask me again in a second."
    n = _badge(titles)
    if not n: return f"Nothing new on {label}, {CALL()}."
    if key in INBOX:
        _set_offer([key])
    return f"{label} shows {_num(n)} new, {CALL()}." + (" That's messages and notifications together." if key == 'linkedin' else '') + (OFFER_TEXT if key in INBOX else '')


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
    py = '/usr/bin/python3'
    rt = os.environ.get('WAVELENGTH_RUNTIME')
    if rt and os.path.exists(os.path.join(rt, 'voice', 'make-greetings.py')):   # packaged app: its own Python and script
        maker, py = os.path.join(rt, 'voice', 'make-greetings.py'), os.path.join(rt, 'python', 'bin', 'python3')
    if key != old and os.path.isdir(greet):
        if not os.path.isdir(keep): shutil.copytree(greet, keep)   # the greetings she was set up with, kept once
        if key == 'warm':   # back to her own voice: her original greetings, not a re-recording
            shutil.rmtree(greet); shutil.copytree(keep, greet)
        elif os.path.exists(maker):   # re-record the greetings in the new voice once the sample has played
            subprocess.Popen(['/bin/sh', '-c', f'sleep 15; exec "{py}" -I "{maker}"'], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    label = VOICES[key]
    return f"Okay, this is my {label} voice. Hi {CALL()}, how do I sound? Say keep it, or try another one."


def _voice_list():
    now = _pick().get('pick', 'warm')
    names = [v + (" (that's me now)" if k == now else '') for k, v in VOICES.items()]
    return "I can sound " + ', '.join(names[:-1]) + ', or ' + names[-1] + ". Say try, and the name."


# ---- end of the day: "close all apps", "we're done for the day", "shut down"
KEEP_IDS = {'com.atticus.app', 'com.apple.finder'}   # the assistant itself, and Finder (macOS keeps it running)
SHUTDOWN_FILE = os.path.expanduser('~/.config/atticus/shutdown-offer.json')
_CLOSE_ALL = re.compile(r"^(?:please )?(?:close|quit|shut) (?:all|everything|every app|all (?:of )?(?:the |my )?(?:running |open |opened )?(?:apps|applications|programs|windows))"
                        r"(?: (?:that are |which are )?(?:running|open|opened))?(?: (?:in the background|behind|on the mac|on my mac))?$|^close everything down$")
_DONE_DAY = re.compile(r"\bdone for (?:the day|today)\b|\bcall it a day\b|\bwrap (?:it )?up for (?:the day|today)\b|\bend of (?:the )?day\b|\bthat(?: is|s) (?:all|it) for (?:the day|today)\b|\blog(?:ging)? off for (?:the day|today)\b")
_SHUTDOWN = re.compile(r"^(?:please )?(?:shut ?down|turn off|power off|power down)(?: (?:the|my) (?:mac|computer|laptop|system))?(?: now)?$")
_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|yes please|yes shut (?:it )?down|shut (?:it )?down|please do)$")


def _running_apps():
    """[(name, bundle id)] of apps with a Dock icon, as System Events lists them."""
    out = _osa('tell application "System Events"\nset r to ""\nrepeat with p in (every process whose background only is false)\n'
               'set r to r & (name of p) & tab & (bundle identifier of p) & linefeed\nend repeat\nreturn r\nend tell')
    return [tuple(l.split('\t', 1)) for l in (out or '').splitlines() if '\t' in l]


def _close_all():
    """Ask every app to quit (never force), wait for them; -> (closed names, still open names)."""
    keep = {k.lower() for k in _workflow().get('keepOpen', ['Claude'])}
    targets = [(n, b) for n, b in _running_apps() if b not in KEEP_IDS and n.lower() not in keep and b != 'missing value']
    for n, b in targets:
        _osa(f'ignoring application responses\ntell application id "{b}" to quit\nend ignoring')
    left = targets
    for _ in range(40):   # up to 20 s: apps with unsaved work show a save prompt and stay
        running = {b for _, b in _running_apps()}
        left = [(n, b) for n, b in targets if b in running]
        if not left: break
        time.sleep(0.5)
    return [n for n, b in targets if (n, b) not in left], [n for n, _ in left]


def _and_list(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ', '.join(xs[:-1]) + ' and ' + xs[-1]


def _close_reply(closed, left):
    said = (f"Closed {_and_list(closed[:4])}" + (f" and {len(closed) - 4} more" if len(closed) > 4 else '') + '.') if closed else "Nothing else was open."
    if left: said += f" {_and_list(left)} {'is' if len(left) == 1 else 'are'} asking to save, so I left {'it' if len(left) == 1 else 'them'} open."
    return said


def _offer_shutdown():
    try:
        os.makedirs(os.path.dirname(SHUTDOWN_FILE), exist_ok=True)
        with open(SHUTDOWN_FILE, 'w') as f: json.dump({'at': time.time()}, f)
    except OSError: pass


def _shutdown_offered():
    try:
        with open(SHUTDOWN_FILE) as f: at = json.load(f).get('at', 0)
        os.remove(SHUTDOWN_FILE)
        return time.time() - at <= 90
    except (OSError, ValueError, AttributeError): return False


def _shut_down():
    _osa('tell application "System Events" to shut down')   # the normal Shut Down: apps still asking to save stop it, nothing is forced
    return f"Shutting down. Good night, {CALL()}."


def _end_of_day(t):
    if _YES.match(t) and _shutdown_offered():
        return _shut_down()
    if _DONE_DAY.search(t):
        closed, left = _close_all()
        if left: return _close_reply(closed, left) + " Save those and say shut down when you're ready."
        _offer_shutdown()
        return f"Good work today, {CALL()}. " + _close_reply(closed, left) + " Shut down the Mac too?"
    if _CLOSE_ALL.match(t):
        return _close_reply(*_close_all())
    if _SHUTDOWN.match(t):
        _offer_shutdown()
        return f"Shut down the Mac, {CALL()}? Unsaved work stops it. Say yes to go ahead."
    return None


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
        return f"Nothing left on your calendar today, {CALL()}." if today_only else "Nothing on your calendar for the next week."
    if today_only:
        top = evs[:3]
        s = '; '.join(f"{t} at {_clock(d)}" for d, t in top)
        extra = f", plus {len(evs) - 3} more" if len(evs) > 3 else ''
        return f"{len(evs)} left today: {s}{extra}."
    d, t = evs[0]
    when = 'happening now' if d <= now else _in(d - now)
    return f"Next up: {t} at {_clock(d)}, {when}." if d > now else f"{t} is {when}, started at {_clock(d)}."


# ---------------------------------------------------------------- everyday basics
# Free, local answers for everyday asks so they never reach Claude. Each matches only when confident; else None.
import ast
import operator
import shlex
import socket
import urllib.parse
import urllib.request

UA = 'curl/8.4.0'


def _get_text(url, timeout=4):
    """GET a URL as text. None on any failure."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', 'replace')
    except Exception:
        return None


def _get_json(url, timeout=4):
    """GET a URL as JSON. None on any failure."""
    txt = _get_text(url, timeout)
    try:
        return json.loads(txt) if txt else None
    except ValueError:
        return None


def _spawn(args):
    """Start a detached background process (survives Zuka)."""
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                     start_new_session=True)


def _now():
    return datetime.now()


def _tcp(host, port, timeout):
    try:
        socket.create_connection((host, port), timeout).close()
        return True
    except Exception:
        return False


_RT = os.environ.get('WAVELENGTH_RUNTIME', '')   # set by the packaged Wavelength.app: its own Python, voice scripts and model
_RT_SAY = os.path.join(_RT, 'voice', 'atticus-say') if _RT else ''
VOICE_SOCK = os.path.expanduser('~/Library/Caches/Wavelength/voice/voice.sock' if _RT_SAY and os.access(_RT_SAY, os.X_OK) else '~/.local/share/chatterbox/voice.sock')
SAY = _RT_SAY if _RT_SAY and os.access(_RT_SAY, os.X_OK) else os.path.expanduser('~/.local/share/chatterbox/atticus-say')
CLAUDE_BIN = os.path.expanduser('~/.local/bin/claude')


# ---- number words -> digits ("fifteen percent of twenty four hundred" -> "15 percent of 2400")
_UNITS = {w: i for i, w in enumerate('one two three four five six seven eight nine'.split(), 1)}
_TEENS = {w: 10 + i for i, w in enumerate('ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split())}
_TENS = {w: 10 * i for i, w in enumerate('twenty thirty forty fifty sixty seventy eighty ninety'.split(), 2)}


def _words_to_digits(s):
    toks = s.split(' ')
    out, i = [], 0
    while i < len(toks):
        w = toks[i]
        if w not in _UNITS and w not in _TEENS and w not in _TENS and w not in ('zero', 'hundred', 'thousand'):
            out.append(w)
            i += 1
            continue
        total, cur, last, used, seen_th = 0, 0, None, 0, False
        j = i
        while j < len(toks):
            w = toks[j]
            if w == 'and' and last in ('hundred', 'thousand') and j + 1 < len(toks) and (
                    toks[j + 1] in _UNITS or toks[j + 1] in _TEENS or toks[j + 1] in _TENS):
                j += 1
                continue
            if w == 'zero':
                if last is not None: break
                cat, v = 'unit', 0
            elif w in _UNITS:
                if last in ('unit', 'teen'): break
                cat, v = 'unit', _UNITS[w]
            elif w in _TEENS:
                if last in ('unit', 'teen', 'tens'): break
                cat, v = 'teen', _TEENS[w]
            elif w in _TENS:
                if last in ('unit', 'teen', 'tens'): break
                cat, v = 'tens', _TENS[w]
            elif w == 'hundred':
                if last not in ('unit', 'teen', 'tens') or cur == 0 or cur >= 100: break
                cat, v = 'hundred', None
            elif w == 'thousand':
                if seen_th or last is None: break
                cat, v = 'thousand', None
            else:
                break
            if cat == 'hundred':
                cur *= 100
            elif cat == 'thousand':
                total += cur * 1000
                cur, seen_th = 0, True
            else:
                cur += v
            last = cat
            j += 1
            used = j - i
        if used == 0:
            out.append(toks[i])
            i += 1
            continue
        out.append(str(total + cur))
        i = i + used if j == i + used else j
    return ' '.join(out)


def _clean(raw):
    """Lowercase request keeping digits, decimals, colons and math symbols; number words become digits."""
    s = (raw if isinstance(raw, str) else '').lower().replace('’', "'")
    s = re.sub(r"\b(what|that|how)'?s\b", r'\1s', s)
    s = s.replace('×', ' times ').replace('÷', ' divided by ')
    s = re.sub(r'\$\s*(\d[\d.,]*)', r'\1 dollars', s)
    s = re.sub(r'₹\s*(\d[\d.,]*)', r'\1 rupees', s)
    s = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', s)
    s = s.replace('%', ' percent ')
    s = re.sub(r"[^a-z0-9.:+\-*/^() ]+", ' ', s)
    s = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', s)
    s = re.sub(r'(?<!\d):|:(?!\d)', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return _words_to_digits(s)


# ---- math (safe AST walker, no eval)
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}


def _walk(n):
    if isinstance(n, ast.Expression):
        return _walk(n.body)
    if isinstance(n, ast.Constant) and type(n.value) in (int, float):
        return n.value
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = _walk(n.operand)
        return -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        a, b = _walk(n.left), _walk(n.right)
        if isinstance(n.op, ast.Pow) and (abs(b) > 100 or (abs(a) > 1e9 and b > 3)):
            raise ValueError('too big')
        r = _BIN[type(n.op)](a, b)
        if isinstance(r, complex):
            raise ValueError('complex')
        return r
    raise ValueError('unsupported')


def _safe_eval(expr):
    if len(expr) > 120:
        raise ValueError('long')
    return _walk(ast.parse(expr, mode='eval'))


def _fmt_num(v, dec=4):
    if abs(v - round(v)) < 1e-9:
        return f'{int(round(v)):,}'
    return f'{v:,.{dec}f}'.rstrip('0').rstrip('.')


_MATH_PRE = re.compile(r"^(?:hey zuka |zuka )?(?:please )?(?:(?:what is|whats|calculate|compute|work out|solve|how much is|what do you get for)\s+)?(?:the answer to )?(?:the )?")
_MATH_POST = re.compile(r"\s+(?:please|equals?|equal to|is)$")


def _math(raw):
    s = _clean(raw)
    s = _MATH_PRE.sub('', s)
    s = _MATH_POST.sub('', s)
    if not s or not re.search(r'\d', s):
        return None
    for a, b in ((r'\bmultiplied by\b|\bmultiply by\b|\btimes\b', ' * '), (r'\bdivided by\b|\bover\b', ' / '),
                 (r'\bplus\b', ' + '), (r'\bminus\b', ' - '), (r'\bto the power of\b|\bto the power\b', ' ^ '),
                 (r'\bsquared\b', ' ^ 2 '), (r'\bcubed\b', ' ^ 3 '), (r'\bsquare root of\b', ' sqrt '),
                 (r'\bpercent of\b|\bpct of\b', ' pct '), (r'(?<=\d)\s*x\s*(?=\d)', ' * ')):
        s = re.sub(a, b, s)
    s = re.sub(r'sqrt\s*(\d+(?:\.\d+)?)', r'(\1)^0.5', s)
    s = s.replace('^', '**').replace('pct', '*0.01*')
    s = re.sub(r'\s+', ' ', s).strip()
    if not re.fullmatch(r'[\d\s.+\-*/()]+', s) or not re.search(r'[+\-*/]', s) or re.fullmatch(r'[-+]?\s*[\d.]+', s):
        return None
    try:
        v = _safe_eval(s)
    except ZeroDivisionError:
        return f"I can't divide by zero, {CALL()}."
    except Exception:
        return None
    if abs(v) > 1e15 or v != v:
        return None
    return f"That's {_fmt_num(v)}, {CALL()}."


# ---- time, date, day
_TIME_Q = re.compile(r"^(?:what time is it|whats the time|what is the time|what time is it now|whats the time now|what is the time now|what is the time right now|whats the time right now|what is the time currently|current time|the time|time now|tell me the time|what time is it right now|got the time)(?: please)?$")
_DATE_Q = re.compile(r"^(?:whats|what is) (?:the )?(?:date|todays date|today s date)(?: today| now)?$|^(?:whats|what is) todays? date$|^what date is it(?: today)?$|^todays date$|^what is today s date$|^whats today s date$|^today s date$")
_DAY_Q = re.compile(r"^(?:what|which) day is it(?: today)?$|^whats the day(?: today)?$|^what day is today$|^what day is it today$")


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _time_reply(t):
    d = _now()
    if _TIME_Q.match(t):
        return f"It's {_clock(d)}, {CALL()}."
    if _DATE_Q.match(t):
        return f"It's {d.strftime('%A')} the {_ordinal(d.day)} of {d.strftime('%B')}, {CALL()}."
    if _DAY_Q.match(t):
        return f"It's {d.strftime('%A')}, {CALL()}."
    return None


# ---- weather
_WEATHER = re.compile(r"^(?:(?:hows|whats|what is|how is|tell me|give me|check) (?:the )?)?(?:weather|forecast)(?: like)?(?: (?:today|right now|now|outside|out there|currently))?"
                      r"(?: (?:in|for|at) (?P<city>[a-z][a-z ]*?))?(?: (?:today|right now|now))?$")
_TMRW = re.compile(r"^(?:(?:hows|whats|what is|how is|tell me|give me|check) )?(?:the )?(?:weather|forecast)(?: like)?(?: for)? tomorrow(?: (?:in|for|at) (?P<city>[a-z][a-z ]*?))?$|"
                   r"^(?:(?:whats|what is|how is|hows) )?tomorrow s? ?(?:weather|forecast)(?: (?:in|for|at) (?P<city2>[a-z][a-z ]*?))?$|^tomorrow(?: s)? weather$")
_TMRW_RAIN = re.compile(r"^(?:(?:is it|will it|is it going to|is it gonna|going to|do you think it will|do you think it ll) )(?:rain|raining|be raining|be rainy|be wet)(?: tomorrow| tomorrow morning| tomorrow evening)$|^(?:will|is) tomorrow (?:be )?(?:rainy|wet|raining)$|^(?:will it|is it going to) rain tomorrow$")
_RAIN = re.compile(r"^(?:is it going to|is it gonna|will it|is it|going to|is it gonna) rain(?:ing)?(?: today| right now| now| later| outside)?$")
_TEMP = re.compile(r"^(?:whats |what is )?(?:the )?temperature(?: outside| out there| right now| today| now)?$|^how (?:hot|cold|warm) is it(?: outside| right now| today)?$")
_WX = re.compile(r"^(?P<c>.+?)\s+(?P<t>[+-]?\d+)\s*°C\s+feels\s+(?P<f>[+-]?\d+)\s*°C,\s*(?P<p>[\d.]+)\s*mm rain", re.I)


def _deg(n):
    n = int(n)
    return f"{'minus ' if n < 0 else ''}{abs(n)}°C"


def _weather(kind, city=None):
    url = 'https://wttr.in/' + (urllib.parse.quote(city) if city else '') + '?format=%C+%t+feels+%f,+%p+rain'
    txt = _get_text(url)
    if not txt:
        return f"I can't reach the weather right now, {CALL()}."
    m = _WX.match(txt.strip())
    if not m:
        return f"I couldn't find the weather for {city.title()}, {CALL()}." if city else f"I can't reach the weather right now, {CALL()}."
    cond, tt, ff, mm = m.group('c').strip().lower(), m.group('t'), m.group('f'), float(m.group('p'))
    place = f"In {city.title()} right now" if city else 'Right now'
    if kind == 'rain':
        if mm > 0:
            return f"Yes, it's raining {'in ' + city.title() + ' ' if city else ''}right now, {CALL()}. {cond.capitalize()}, {_deg(tt)}."
        return f"No rain right now, {CALL()}. It's {cond}, {_deg(tt)}."
    if kind == 'temp':
        return f"It's {_deg(tt)} outside, {CALL()}. Feels like {_deg(ff)}."
    return f"{place} it's {cond}, {_deg(tt)}, feels like {_deg(ff)}." + (f" There's some rain, {mm:g} millimetres." if mm > 0 else '')


def _tomorrow(kind, city=None):
    """Tomorrow's forecast from wttr.in (free, no key): high/low, the day's look, the best chance of rain."""
    d = _get_json('https://wttr.in/' + (urllib.parse.quote(city) if city else '') + '?format=j1')
    try:
        day = d['weather'][1]
        hi, lo = int(day['maxtempC']), int(day['mintempC'])
        hours = day['hourly']
        cond = hours[min(4, len(hours) - 1)]['weatherDesc'][0]['value'].strip().lower()   # the noon slot
        chance = max(int(h.get('chanceofrain') or 0) for h in hours)
    except Exception:
        return f"I can't reach the forecast right now, {CALL()}."
    where = f" in {city.title()}" if city else ''
    if kind == 'rain':
        return (f"Probably, {CALL()}. {chance} percent chance of rain tomorrow{where}, {cond}." if chance >= 50 else
                f"Maybe a shower, {CALL()}. {chance} percent chance of rain tomorrow{where}." if chance >= 25 else
                f"Unlikely, {CALL()}. Only {chance} percent chance of rain tomorrow{where}, {cond}.")
    return f"Tomorrow{where} it'll be {cond}, {_deg(lo)} to {_deg(hi)}" + (f", with a {chance} percent chance of rain" if chance >= 20 else '') + f", {CALL()}."


# ---- quick facts (Wikipedia) and definitions
_FACT_SKIP = set("my your this that these those it me our today s latest new screen file folder email message task calling going doing "
                 "happening there here now next tomorrow yesterday wrong up on".split())
_MATH_WORDS = {'plus', 'minus', 'times', 'divided', 'multiplied', 'percent', 'squared', 'cubed', 'root', 'power', 'over'}
_FACT = re.compile(r"^(?:who is|who was|whos|what is|what are|what was|tell me about|whats)\s+(?:an? |the )?(?P<topic>.+)$")
_CAPITAL = re.compile(r"^(?:(?:what is|whats) )?(?:the )?capital(?: city)? of (?P<c>[a-z][a-z ]*)$")
_DEFINE = re.compile(r"^(?:define|definition of|meaning of|what is the meaning of|whats the meaning of|what does (?P<w2>[a-z]+) mean|what is the definition of)(?: (?P<w1>[a-z]+))?$")


def _wiki(query):
    q = urllib.parse.quote(query)
    data = _get_json('https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=' + q + '&format=json&srlimit=1')
    try:
        title = data['query']['search'][0]['title']
    except Exception:
        return None
    s = _get_json('https://en.wikipedia.org/api/rest_v1/page/summary/' + urllib.parse.quote(title.replace(' ', '_'), safe=''))
    if not isinstance(s, dict) or s.get('type') == 'disambiguation':
        return None
    ex = re.sub(r'\s*\([^)]*\)', '', s.get('extract') or '').strip()
    if not ex:
        return None
    sents = re.split(r'(?<=[a-z0-9\)][.!?])\s+(?=[A-Z])', ex)
    out = sents[0]
    if len(sents) > 1 and len(out) + 1 + len(sents[1]) <= 300:
        out += ' ' + sents[1]
    if len(out) > 300:
        cut = out[:300]
        k = max(cut.rfind('; '), cut.rfind(', '))
        out = (cut[:k] if k > 120 else cut.rsplit(' ', 1)[0]).rstrip(',;:') + '.'
    return out


def _fact(t, raw):
    m = _CAPITAL.match(t)
    if m:
        return _wiki('capital of ' + m.group('c').strip())
    m = _FACT.match(t)
    if not m:
        return None
    topic = m.group('topic').strip()
    words = topic.split()
    if not words or len(words) > 6 or not re.search(r'[a-z]', topic):
        return None
    if _FACT_SKIP & set(words) or _MATH_WORDS & set(words) or (len(words) == 1 and words[0].endswith('ing')):
        return None
    if _math(raw):
        return None
    return _wiki(topic)


def _define(t):
    m = _DEFINE.match(t)
    if not m:
        return None
    w = m.group('w2') or m.group('w1')
    if not w or w in _FACT_SKIP or w in ('it', 'that', 'this'):
        return None
    d = _get_json('https://api.dictionaryapi.dev/api/v2/entries/en/' + urllib.parse.quote(w))
    try:
        df = d[0]['meanings'][0]['definitions'][0]['definition'].strip().rstrip('.')
    except Exception:
        return None
    return f"{w.capitalize()}: {df}." if df else None


# ---- currency
_CUR = {'dollar': 'USD', 'dollars': 'USD', 'usd': 'USD', 'us dollar': 'USD', 'us dollars': 'USD', 'bucks': 'USD', 'american dollars': 'USD',
        'rupee': 'INR', 'rupees': 'INR', 'inr': 'INR', 'indian rupee': 'INR', 'indian rupees': 'INR',
        'euro': 'EUR', 'euros': 'EUR', 'eur': 'EUR', 'pound': 'GBP', 'pounds': 'GBP', 'gbp': 'GBP', 'sterling': 'GBP',
        'british pound': 'GBP', 'british pounds': 'GBP', 'dirham': 'AED', 'dirhams': 'AED', 'aed': 'AED',
        'yen': 'JPY', 'jpy': 'JPY', 'canadian dollar': 'CAD', 'canadian dollars': 'CAD', 'cad': 'CAD',
        'australian dollar': 'AUD', 'australian dollars': 'AUD', 'aud': 'AUD', 'singapore dollar': 'SGD', 'singapore dollars': 'SGD', 'sgd': 'SGD',
        'franc': 'CHF', 'francs': 'CHF', 'swiss franc': 'CHF', 'swiss francs': 'CHF', 'chf': 'CHF', 'yuan': 'CNY', 'rmb': 'CNY', 'cny': 'CNY',
        'riyal': 'SAR', 'riyals': 'SAR', 'saudi riyal': 'SAR', 'saudi riyals': 'SAR', 'sar': 'SAR', 'baht': 'THB', 'thb': 'THB',
        'ringgit': 'MYR', 'myr': 'MYR', 'won': 'KRW', 'krw': 'KRW', 'taka': 'BDT', 'bdt': 'BDT', 'rand': 'ZAR', 'zar': 'ZAR'}
_CUR_NAME = {'USD': ('US dollar', 'US dollars'), 'INR': ('rupee', 'rupees'), 'EUR': ('euro', 'euros'),
             'GBP': ('pound', 'pounds'), 'AED': ('dirham', 'dirhams'), 'JPY': ('yen', 'yen'), 'CAD': ('Canadian dollar', 'Canadian dollars'),
             'AUD': ('Australian dollar', 'Australian dollars'), 'SGD': ('Singapore dollar', 'Singapore dollars'), 'CHF': ('Swiss franc', 'Swiss francs'),
             'CNY': ('yuan', 'yuan'), 'SAR': ('Saudi riyal', 'Saudi riyals'), 'THB': ('baht', 'baht'), 'MYR': ('ringgit', 'ringgit'),
             'KRW': ('won', 'won'), 'BDT': ('taka', 'taka'), 'ZAR': ('rand', 'rand')}
_CURRENCY = re.compile(r"^(?:(?:please )?convert |how much is |what is |whats |how many |what s )?(?P<n>\d+(?:\.\d+)?) (?P<a>[a-z]+(?: [a-z]+)?) (?:to|in|into) (?P<b>[a-z]+(?: [a-z]+)?)$|"
                       r"^(?:please )?convert (?P<a2>[a-z]+(?: [a-z]+)?) (?:to|into) (?P<b2>[a-z]+(?: [a-z]+)?)$|"
                       r"^(?:(?:what is|whats|what s|check) )?(?:the )?(?P<a3>[a-z]+(?: [a-z]+)?) (?:to|in) (?P<b3>[a-z]+(?: [a-z]+)?)(?: (?:exchange )?rate)$|"
                       r"^(?:(?:what is|whats|what s) )?(?:the )?(?:(?:exchange )?rate|price) of (?P<a4>[a-z]+(?: [a-z]+)?) (?:in|to) (?P<b4>[a-z]+(?: [a-z]+)?)$")
FX_TTL = 6 * 3600


def _fx_rates(base):
    """{code: rate} for 1 base, from open.er-api.com (free, no key). Cached 6 h under ATTICUS_DIR; None when offline with no fresh cache."""
    path = os.path.join(os.environ.get('ATTICUS_DIR') or os.path.expanduser('~/.config/atticus'), 'fx-rates.json')
    try:
        with open(path) as f: cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict): cache = {}
    c = cache.get(base)
    if isinstance(c, dict) and time.time() - c.get('at', 0) < FX_TTL and isinstance(c.get('rates'), dict):
        return c['rates']
    d = _get_json('https://open.er-api.com/v6/latest/' + base)
    try:
        rates = {k: float(v) for k, v in d['rates'].items()}
    except Exception:
        return None
    cache[base] = {'at': time.time(), 'rates': rates}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f: json.dump(cache, f)
    except OSError: pass
    return rates


def _currency(raw):
    m = _CURRENCY.match(_clean(raw))
    if not m:
        return None
    g = m.groupdict()
    a, b = (g.get('a') or g.get('a2') or g.get('a3') or g.get('a4')), (g.get('b') or g.get('b2') or g.get('b3') or g.get('b4'))
    a, b = _CUR.get(a), _CUR.get(b)
    if not a or not b or a == b:
        return None
    rates = _fx_rates(a)
    try:
        rate = float(rates[b])
    except Exception:
        return None
    n = float(g['n']) if g.get('n') else 1.0
    out = n * rate
    one = lambda c, v: _CUR_NAME[c][0] if abs(v - 1) < 1e-9 else _CUR_NAME[c][1]
    res = _fmt_num(out, 0 if out >= 100 else 2)
    return f"{_fmt_num(n)} {one(a, n)} is about {res} {one(b, round(out, 2))}, {CALL()}."


# ---- volume
_BIT = r"(?:(?:a )?(?:bit|little|lot|notch|touch)|slightly|some|more|abit)"
_VOL_UP = re.compile(r"^(?:(?:turn|make|get|bump|crank|put|pump|take|bring|set)(?: it| the (?:volume|sound|audio|music)| volume| sound| audio)?(?: " + _BIT + r")? ?(?:up|louder|higher)|"
                     r"turn up(?: the)?(?: volume| sound| audio| music)?|(?:increase|raise|boost|up)(?: the)?(?: volume| sound| audio)?|volume (?:" + _BIT + r" )?(?:up|higher|louder)|louder|" + _BIT + r" louder|sound up|too (?:quiet|low|soft|silent))(?: " + _BIT + r")?$")
_VOL_DOWN = re.compile(r"^(?:(?:turn|make|get|bring|put|take|set)(?: it| the (?:volume|sound|audio|music)| volume| sound| audio)?(?: " + _BIT + r")? ?(?:down|quieter|lower|softer)|"
                       r"turn down(?: the)?(?: volume| sound| audio| music)?|(?:decrease|reduce|lower|drop)(?: the)?(?: volume| sound| audio)?|volume (?:" + _BIT + r" )?(?:down|lower|quieter)|quieter|softer|" + _BIT + r" (?:quieter|softer|lower)|sound down|too (?:loud|noisy|high))(?: " + _BIT + r")?$")
_VOL_MUTE = re.compile(r"^(?:mute|mute (?:it|the sound|the volume|the mac|sound))$")
_VOL_UNMUTE = re.compile(r"^(?:unmute|unmute (?:it|the sound|the volume|the mac|sound))$")
_VOL_MAX = re.compile(r"^(?:max(?:imum)? volume|full volume|volume (?:to )?(?:max|full|maximum)|turn it up (?:all the way|to max))$")
_VOL_SET = re.compile(r"^(?:set |put |make )?(?:the )?volume (?:to |at )?(\d{1,3})(?: percent)?$")


def _volume(t, raw):
    s = _clean(raw)
    s = re.sub(r"[^a-z0-9 ]", '', s)
    m = _VOL_SET.match(s)
    if m:
        n = max(0, min(100, int(m.group(1))))
        _osa(f'set volume output volume {n}')
        return f"Volume at {n}, {CALL()}."
    if _VOL_MAX.match(t):
        _osa('set volume output volume 100')
        return f"Volume's at max, {CALL()}."
    if _VOL_MUTE.match(t):
        _osa('set volume output muted true')
        return f"Muted, {CALL()}."
    if _VOL_UNMUTE.match(t):
        _osa('set volume output muted false')
        return f"Unmuted, {CALL()}."
    up, down = _VOL_UP.match(t), _VOL_DOWN.match(t)
    if not (up or down):
        return None
    try:
        cur = int(_osa('output volume of (get volume settings)'))
    except Exception:
        return f"I can't change the volume on this output, {CALL()}."
    n = max(0, min(100, cur + (12 if up else -12)))
    _osa(f'set volume output volume {n}' + (' without output muted' if False else '') + ('\nset volume output muted false' if up else ''))
    return f"Volume at {n}, {CALL()}."


# ---- timer
_DUR = r"(?P<n>\d+(?:\.\d+)?|an?|half an?)\s*(?P<u>seconds?|secs?|minutes?|mins?|hours?|hrs?)"
_DUR0 = r"(?:\d+(?:\.\d+)?|an?|half an?)\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)"
_TIMER = re.compile(r"^(?:(?:set|start|put|make|create) )?(?:me )?(?:a |an )?(?:timer|countdown)(?: for| of)? " + _DUR0 + r"$|^(?:set|start|put) (?:a |an )?" + _DUR0 + r" timer$|^timer " + _DUR0 + r"$")


def _dur_secs(m):
    n = m.group('n')
    v = 0.5 if n.startswith('half') else (1.0 if n in ('a', 'an') else float(n))
    u = m.group('u')[0]
    return int(round(v * {'s': 1, 'm': 60, 'h': 3600}[u]))


def _human_dur(secs):
    if secs % 3600 == 0:
        n, u = secs // 3600, 'hour'
    elif secs % 60 == 0:
        n, u = secs // 60, 'minute'
    else:
        n, u = secs, 'second'
    return f"{n} {u}{'' if n == 1 else 's'}"


def _timer(raw):
    s = re.sub(r"(?: (?:for me|please|once|na|yaar))+$", '', _clean(raw))
    m = _TIMER.match(s)
    if not m:
        return None
    # the duration groups repeat per alternative; find the one that matched
    m2 = re.search(_DUR, s)
    secs = _dur_secs(m2)
    if secs < 1 or secs > 86400:
        return f"I can set timers up to a day, {CALL()}."
    say = SAY if os.access(SAY, os.X_OK) else None
    speak = f"{shlex.quote(SAY)} -- \"Time's up{call_suffix()}.\"" if say else f"/usr/bin/say \"Time's up{call_suffix()}.\""
    note = f'display notification "Time\'s up{call_suffix()}." with title "{NAME()} timer"'
    _spawn(['/bin/sh', '-c', f"sleep {secs}; /usr/bin/osascript -e {shlex.quote(note)}; {speak}"])
    return f"Timer set for {_human_dur(secs)}, {CALL()}."


# ---- reminders
_REM_IN = re.compile(r"^remind me (?:to )?(?P<task>.+?) in " + _DUR + r"$")
_REM_AT = re.compile(r"^remind me (?:to )?(?P<task>.+?)(?P<day> tomorrow| today| tonight)?(?: at (?P<h>\d{1,2})(?:[: ]?(?P<mi>\d{2}))? ?(?P<ap>am|pm|a m|p m)?)(?P<day2> tomorrow| today| tonight)?$")
_REM_TOMORROW = re.compile(r"^remind me (?:to )?(?P<task>.+?) tomorrow$")
_REM_TONIGHT = re.compile(r"^remind me (?:to )?(?P<task>.+?) (?:tonight|this evening)$")   # no clock time: 9 pm


def _as_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


REMINDERS = os.path.join(os.environ.get('ATTICUS_DIR') or os.path.expanduser('~/.config/atticus'), 'reminders.json')   # the reminders Zuka made (id, task, when): only these can be cancelled by voice
_CANCEL_REM = re.compile(r"^(?:cancel|delete|remove|clear|forget|scrap|drop)(?: (?:all|every|my|the|that|this|last|latest|previous|recent|newest|one|a|reminder))*? ?reminders?(?: i just (?:made|set|gave))?$")
PENDING = os.path.join(os.environ.get('ATTICUS_DIR') or os.path.expanduser('~/.config/atticus'), 'pending.json')   # a half-given reminder waiting for its missing part (90 s)
_WHEN = r"(?:(?:tomorrow |today |tonight )?at \d{1,2}(?:[: ]?\d{2})? ?(?:am|pm|a m|p m)?(?: tomorrow| today| tonight)?|tomorrow|today|tonight|in (?:\d+|an?|half an?|a couple of) [a-z ]+?)"


def _pending(new=None, clear=False):
    try:
        if clear or new is not None:
            if new is None: os.remove(PENDING)
            else:
                os.makedirs(os.path.dirname(PENDING), exist_ok=True)
                with open(PENDING, 'w') as f: json.dump({**new, 'at': time.time()}, f)
            return None
        with open(PENDING) as f: d = json.load(f)
        return d if time.time() - d.get('at', 0) <= 90 else None
    except (OSError, ValueError):
        return None


def _rem_log(new=None, items=None):
    try:
        with open(REMINDERS) as f: cur = json.load(f)
    except (OSError, ValueError):
        cur = []
    if not isinstance(cur, list): cur = []
    if new: cur.append(new)
    if items is not None: cur = items
    if new or items is not None:
        try:
            os.makedirs(os.path.dirname(REMINDERS), exist_ok=True)
            with open(REMINDERS, 'w') as f: json.dump(cur[-30:], f)
        except OSError: pass
    return cur


def _cancel_remind(t):
    """'cancel my reminder' = the latest one Zuka set; 'cancel all reminders' = every one it set that is still waiting."""
    p = _pending()
    if p and p.get('kind') == 'remind':
        _pending(clear=True)
        return f"Okay, I dropped the half-made reminder{call_suffix()}."
    allr = bool(re.search(r"\b(?:all|every)\b", t)) or t.endswith('reminders') and not re.search(r"\b(?:last|latest|previous|recent|newest|that|this|the)\b", t)
    logged = [r for r in _rem_log() if isinstance(r, dict) and r.get('id')]
    if not logged:
        return f"I haven't set any reminders you could cancel, {CALL()}."
    gone, keep = [], list(logged)
    for r in (logged[::-1] if allr else logged[-1:]):
        try: _osa('tell application "Reminders" to delete (first reminder whose id is %s)' % _as_str(r['id']), 15)
        except Exception: pass   # already done or removed by hand: just drop it from the list
        gone.append(r); keep.remove(r)
    _rem_log(items=keep)
    names = [r.get('task') or 'a reminder' for r in gone]
    return (f"Cancelled {len(gone)} reminders: {', '.join(names[:3])}{' and more' if len(names) > 3 else ''}{call_suffix()}." if len(gone) > 1 else
            f"Cancelled your reminder {names[0] if names[0].startswith(('about ', 'of ')) else 'to ' + names[0]}{call_suffix()}.")


def _remind_words(low):
    """How people say it -> "remind me to <task> <when>", or ('ask-task', when) / ('ask-when', task) when a part is missing."""
    i = low.find('remind me')
    if i < 0: return None
    low = low[i:].strip()
    low = re.sub(r"^remind me that ", 'remind me to ', low)   # "about X" stays "about X": "I'll remind you about the meeting"
    m = re.match(r"^remind me (" + _WHEN + r")(?: (?:that|to|about|of) | )(.+)$", _words_to_digits(low))
    if m and not re.match(r"^(?:at|in|tomorrow|today|tonight)\b", m.group(2)):   # "remind me tomorrow that I call Mom" -> task first, when last
        low = f"remind me to {re.sub(r'^(?:i (?:have|need) to|to|that) ', '', m.group(2))} {m.group(1)}"
    else:
        low = _words_to_digits(low) if re.match(r"^remind me (?:" + _WHEN + r")$", _words_to_digits(low)) else low
    if re.fullmatch(r"remind me(?: to)?", low): return ('ask-task', '')
    m = re.fullmatch(r"remind me (" + _WHEN + r")", low)
    if m: return ('ask-task', m.group(1))
    if not re.search(r"\b(?:tomorrow|today|tonight)\b| at \d| in (?:\d|an? |half)", _words_to_digits(low)):
        return ('ask-when', re.sub(r"^remind me (?:to )?", '', low).strip())
    return low


_REM_NOUN = re.compile(r"(?i)^(?:(?:set|add|create|make|put|schedule|save|give me|i need)(?: me)?(?: up)?(?: an?| another| one| the)?(?: new| quick)? |(?:an? )?)reminder(?: (?:for|to|about|that|on|at))? ?(?P<r>.*)$")


def _reminder_noun(raw):
    """"set a reminder for 5 pm" / "set a reminder to call Alex tomorrow" / "reminder to stretch at 6" -> "remind me ..." (None if it isn't that)."""
    m = _REM_NOUN.match(re.sub(r"\s+", ' ', (raw or '').strip().rstrip('.!?')))
    if not m or 'remind me' in raw.lower():
        return None
    r = m.group('r').strip()
    if not r:
        return 'remind me'
    low = r.lower()
    if re.match(r"\d+(?:\.\d+)? ?(?:min|minute|minutes|hour|hours|hr|hrs|sec|seconds)\b|(?:an?|half an?) (?:hour|minute)", low):
        return 'remind me in ' + r
    if re.match(r"\d{1,2}(?:[: ]\d{2})? ?(?:am|pm|a m|p m)?\b", low) and not re.match(r"\d+ (?:things|items)", low):
        return 'remind me at ' + r
    return 'remind me ' + ('to ' + r if not re.match(r"(?:to|about|tomorrow|today|tonight|in|at|that)\b", low) else r)


def _remind(raw):
    low = re.sub(r"\s+", ' ', raw.lower().replace('’', "'")).strip().rstrip('.!?')
    low = _remind_words(low)
    if low is None:
        return None
    if isinstance(low, tuple):   # a part is missing: ask for it and keep the rest for the answer
        kind, part = low
        if kind == 'ask-task':
            _pending({'kind': 'remind', 'when': part})
            return f"Sure{call_suffix()}. What should I remind you about{(' ' + part) if part else ''}?"
        _pending({'kind': 'remind', 'task': part})
        return f"When should I remind you {part if part.startswith(('about ', 'of ')) else 'to ' + part}{call_suffix()}?"
    low = re.sub(r"\bremind me to\b", 'remind me to', low)
    now = _now()
    m = _REM_IN.match(_words_to_digits(low)) if re.search(r' in (?:\d|an? |half|[a-z]+ (?:min|hour|sec))', low) else None
    # task text must come from the original words; only the duration needs digits
    if m:
        task = re.match(r"^remind me (?:to )?(.+) in [^ ]+(?: [^ ]+){0,3}$", low)
        idx = low.rfind(' in ')
        task = re.sub(r"^remind me (?:to )?", '', low[:idx]).strip()
        when, label = now + timedelta(seconds=_dur_secs(m)), f"in {_human_dur(_dur_secs(m))}"
    else:
        fixed = _words_to_digits(low)
        m = _REM_AT.match(fixed)
        mt = None if m else _REM_TOMORROW.match(low)
        mn = None if m or mt else _REM_TONIGHT.match(low)
        if not m and not mt and not mn:
            return None
        if mn:
            task, h, mi, ap, tomorrow = mn.group('task'), 9, 0, 'pm', False
        elif mt:
            task, h, mi, ap, tomorrow = mt.group('task'), 9, 0, 'am', True
        else:
            idx = low.rfind(' at ')
            tail = low[idx:]
            task = re.sub(r"^remind me (?:to )?", '', low[:idx]).strip()
            task = re.sub(r"\s+(tomorrow|today|tonight)$", '', task)
            h, mi = int(m.group('h')), int(m.group('mi') or 0)
            ap = (m.group('ap') or '').replace(' ', '')
            day = (m.group('day') or m.group('day2') or '').strip()
            tomorrow = day == 'tomorrow' or ' tomorrow' in tail
            if h > 23 or mi > 59 or (ap and not 1 <= h <= 12):
                return None
            if day == 'tonight' and not ap:
                ap = 'pm'
        if ap == 'pm' and h < 12:
            h += 12
        elif ap == 'am' and h == 12:
            h = 0
        base = now.replace(second=0, microsecond=0)
        if mt or mn or ap or h > 12 or h == 0:
            when = base.replace(hour=h, minute=mi) + timedelta(days=1 if tomorrow else 0)
            if not tomorrow and when <= now:
                when += timedelta(days=1)
        else:   # no am/pm: the soonest future reading of that hour
            cands = [base.replace(hour=(h % 12) + off, minute=mi) + timedelta(days=1 if tomorrow else 0) for off in (0, 12)]
            if tomorrow:
                when = cands[0] if 7 <= h <= 11 else cands[1]
            else:
                fut = sorted(c for c in cands if c > now) or [min(cands) + timedelta(days=1)]
                when = fut[0]
        day_word = 'tomorrow' if when.date() > now.date() else 'today'
        label = f"{day_word} at {_clock(when)}"
    if not task:
        return None
    script = ('set d to current date\nset day of d to 1\nset year of d to %d\nset month of d to %d\nset day of d to %d\n'
              'set hours of d to %d\nset minutes of d to %d\nset seconds of d to 0\n'
              'tell application "Reminders"\nset r to make new reminder with properties {name:%s, remind me date:d}\nreturn id of r\nend tell'
              % (when.year, when.month, when.day, when.hour, when.minute, _as_str(task)))
    try:
        rid = _osa(script, 20)
        if rid: _rem_log({'id': rid, 'task': task, 'when': label})
    except Exception:
        return f"I couldn't add that to Reminders, {CALL()}. Allow {NAME()} under Privacy & Security, Reminders."
    return f"Okay, I'll remind you {task if task.startswith(('about ', 'of ')) else 'to ' + task} {label}, {CALL()}."


# ---- screenshot, lock, folders
_SHOT = re.compile(r"^(?:take (?:a )?)?(?:screenshot|screen shot|screen capture)$")
_SHOT_AREA = re.compile(r"^(?:take (?:a )?)?(?:screenshot|screen shot)(?: of)? (?:a |the |part of the |an? )?(?:part|area|selection|portion|region)(?: of (?:the |my )?screen)?$|^(?:take (?:a )?)?(?:partial|area|selection) screenshot$")
_LOCK = re.compile(r"^(?:lock (?:my |the )?(?:screen|mac|computer|laptop|macbook))$")
_SCREEN_OFF = re.compile(r"^(?:turn off (?:the |my )?(?:screen|display)|sleep (?:the |my )?display|put (?:the |my )?(?:screen|display) to sleep|screen off|display off)$")
_FOLDER = re.compile(r"^open (?:my |the )?(?P<f>downloads|desktop|documents|movies|pictures|music|home)(?: folder)?$")


def _screenshot(area):
    path = os.path.expanduser(f"~/Desktop/Screenshot {_now().strftime('%Y-%m-%d at %H.%M.%S')}.png")
    r = _run(['screencapture'] + (['-i'] if area else ['-x']) + [path], 60 if area else 10)
    if r.returncode != 0:
        return f"I couldn't take it, {CALL()}. Allow {NAME()} under Privacy & Security, Screen Recording."
    if area and not os.path.exists(path):
        return f"No screenshot taken, {CALL()}."
    return f"Screenshot saved to your Desktop, {CALL()}."


# ---- music
_MUSIC = [(re.compile(r"^(?:pause|stop|hold)(?: the| this| my)? (?:music|song|track|playing|playback)$|^(?:pause|pause it|stop it|hold it|pause this|pause that)$"), 'pause', 'Paused, {call}.'),
          (re.compile(r"^(?:play|resume|continue|unpause)(?: the| this| my)? (?:music|song|track)$|^(?:resume|unpause|play|resume it|continue)$"), 'play', 'Playing, {call}.'),
          (re.compile(r"^(?:next|skip)(?: the| this)? (?:song|track)(?: please)?$|^skip this$|^(?:next|skip)(?: it| one| this one| the song)?$|^play (?:the )?next(?: song| one| track)?$"), 'next track', 'Next one, {call}.'),
          (re.compile(r"^(?:previous|last|go back a|back a)(?: the)? (?:song|track)$|^play the previous (?:song|track)$|^(?:go (?:back )?to )?(?:the )?(?:previous|last) (?:song|track|one)$|^previous(?: one)?$|^play (?:the )?previous(?: one)?$"), 'previous track', 'Going back, {call}.')]


def _music(t):
    for rx, cmd, reply in _MUSIC:
        if t in ('resume', 'unpause') and cmd == 'play':
            pass
        if rx.match(t):
            break
    else:
        return None
    running = [a for a in ('Music', 'Spotify') if _run(['pgrep', '-x', a], 3).returncode == 0]
    if not running:
        return None
    pick = None
    for a in running:   # prefer whichever is playing right now
        try:
            if _osa(f'tell application "{a}" to return (player state as text)', 5).lower().startswith('play'):
                pick = a
                break
        except Exception:
            continue
    pick = pick or running[0]
    _osa(f'tell application "{pick}" to {cmd}', 8)
    return reply.format(call=CALL())


# ---- presence / health
_PRESENT = re.compile(r"^(?:hello |hey |hi )?(?:can you hear me|are you there|you there|test|testing(?: testing)?(?: one two)?|are you working|checking if (?:it|this|that) (?:is )?working|is (?:it|this|that) working)$")
_DEEP = re.compile(r"^is everything (?:ok|okay|alright|working|fine)(?: on the (?:mac|cloud))?$")


def _voice_up():
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect(VOICE_SOCK)
        s.sendall(b'{"ping":1}\n')
        ok = b'ok' in s.recv(64)
        s.close()
        return ok
    except Exception:
        return False


def _claude_signed_in():
    for exe in (CLAUDE_BIN, 'claude'):
        try:
            r = _run([exe, 'auth', 'status'], 8)
            return bool(json.loads(r.stdout or '{}').get('loggedIn'))
        except Exception:
            continue
    return False


def _health(deep):
    online = _tcp('api.anthropic.com', 443, 1.2)
    voice = _voice_up()
    signed = _claude_signed_in() if deep else None
    if online and voice and signed is not False:
        if deep:
            return f"All good, {CALL()}. Online, voice is up, and Claude is signed in."
        return f"I'm here, {CALL()}. Online, and the voice is up."
    bad = []
    if not online:
        bad.append("I can't reach the internet")
    if not voice:
        bad.append("the voice isn't answering")
    if signed is False:
        bad.append("Claude isn't signed in")
    return f"Not quite, {CALL()}. " + _say_list([b[0].upper() + b[1:] if i == 0 else b for i, b in enumerate(bad)]) + '.'


# ---- spell
_SPELL = re.compile(r"^(?:spell|how do you spell|how to spell|spell the word|how do i spell) (?P<w>[a-z]+)$")


def _basics(t, raw):
    """Everyday basics. None unless confident. Never raises."""
    try:
        if _PRESENT.match(t):
            return _health(False)
        if _DEEP.match(t):
            return _health(True)
        m = _SPELL.match(t)
        if m:
            return '-'.join(m.group('w').upper()) + '.'
        r = _volume(t, raw)
        if r:
            return r
        r = _timer(raw)
        if r:
            return r
        if _CANCEL_REM.match(t):
            return _cancel_remind(t)
        rw = _reminder_noun(raw)
        if rw:
            return _remind(rw)
        if 'remind me' in t:
            return _remind(raw)
        if _SHOT_AREA.match(t):
            return _screenshot(True)
        if _SHOT.match(t):
            return _screenshot(False)
        if _LOCK.match(t):
            _run(['pmset', 'displaysleepnow'], 5)
            return f"Locking up, {CALL()}."
        if _SCREEN_OFF.match(t):
            _run(['pmset', 'displaysleepnow'], 5)
            return f"Screen off, {CALL()}."
        m = _FOLDER.match(t)
        if m:
            f = m.group('f')
            _run(['open', os.path.expanduser('~' if f == 'home' else '~/' + f.capitalize())], 10)
            return f"Opening {'your home folder' if f == 'home' else f.capitalize()}, {CALL()}."
        r = _music(t)
        if r:
            return r
        r = _time_reply(t)
        if r:
            return r
        m = _TMRW.match(t)
        if m:
            return _tomorrow('day', (m.group('city') or m.group('city2') or '').strip() or None)
        if _TMRW_RAIN.match(t):
            return _tomorrow('rain')
        m = _WEATHER.match(t)
        if m:
            return _weather('now', (m.group('city') or '').strip() or None)
        if _RAIN.match(t):
            return _weather('rain')
        if _TEMP.match(t):
            return _weather('temp')
        r = _currency(raw)
        if r:
            return r
        r = _define(t)
        if r:
            return r
        r = _math(raw)
        if r:
            return r
        return _fact(t, raw)
    except Exception:
        return None


# ---------------------------------------------------------------- "who messaged me": read-only inbox readers
OFFER_FILE = os.path.expanduser('~/.config/atticus/offer.json')
OFFER_TEXT = " Want me to read who they're from?"
OFFER_WINDOW = 180


def _set_offer(sites):
    try:
        os.makedirs(os.path.dirname(OFFER_FILE), exist_ok=True)
        with open(OFFER_FILE, 'w') as f:
            json.dump({'sites': list(sites), 'at': time.time()}, f)
    except OSError:
        pass


def _take_offer():
    """The sites offered in the last 3 minutes (and clears the offer), else None."""
    try:
        with open(OFFER_FILE) as f:
            d = json.load(f)
        os.remove(OFFER_FILE)
    except (OSError, ValueError):
        return None
    if isinstance(d, dict) and time.time() - d.get('at', 0) <= OFFER_WINDOW and d.get('sites'):
        return [s for s in d['sites'] if s in INBOX or s in ('slack', 'discord')]
    return None


_LI_JS = ("(function(){var rows=[].slice.call(document.querySelectorAll('li.msg-conversation-listitem'));"
          "var items=rows.map(function(r){var q=function(s){var e=r.querySelector(s);return e?(e.innerText||'').trim():''};"
          "var ci=r.querySelector('.msg-conversation-card__convo-item,[class*=convo-item]');"
          "var un=!!((ci&&/unread/i.test(ci.className))||r.querySelector('.notification-badge--show,[class*=unread-count]'));"
          "return {name:q('[class*=participant-names]'),snippet:q('[class*=message-snippet]'),time:q('time'),unread:un}});"
          "return JSON.stringify({rs:document.readyState,len:(document.body.innerText||'').length,n:rows.length,items:items})})()")
_WA_JS = ("(function(){var ps=document.querySelector('#pane-side');var rows=ps?[].slice.call(ps.querySelectorAll('[role=listitem],[role=row]')):[];"
          "var seen={},items=[];rows.forEach(function(r){var sp=r.querySelectorAll('span[title]');var name=sp[0]?sp[0].getAttribute('title'):'';"
          "if(!name||seen[name])return;seen[name]=1;var un=[].slice.call(r.querySelectorAll('[aria-label]')).some(function(e){return /unread message/i.test(e.getAttribute('aria-label'))});"
          "var ls=(r.innerText||'').split('\\n').map(function(x){return x.trim()});var tm=ls.filter(function(x){return /^(\\d{1,2}:\\d{2}(\\s?[ap]m)?|yesterday|today|(mon|tues?|wed(nes)?|thu(rs)?|fri|sat(ur)?|sun)(day)?|\\d{1,2}[\\/.-]\\d{1,2}[\\/.-]\\d{2,4})$/i.test(x)})[0]||'';"
          "items.push({name:name,snippet:sp[1]?sp[1].getAttribute('title'):'',unread:un,time:tm,me:ls.indexOf('(You)')>=0})});"
          "return JSON.stringify({rs:document.readyState,len:(document.body.innerText||'').length,n:items.length,items:items})})()")
_GM_JS = ("(function(){var rows=[].slice.call(document.querySelectorAll('tr.zE'));"
          "var items=rows.map(function(r){var s=r.querySelector('.yW span[email]');var sub=r.querySelector('.bog');"
          "return {name:s?(s.getAttribute('name')||s.innerText||'').trim():'',subject:sub?(sub.innerText||'').trim():'',unread:true}});"
          "return JSON.stringify({rs:document.readyState,len:(document.body.innerText||'').length,n:items.length,items:items,any:document.querySelectorAll('tr.zA').length})})()")


def _snip(s, n=40):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n].rsplit(' ', 1)[0].rstrip(',;:-') + '…'


def _names(names):
    names = names[:5]
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ', and ' + names[-1]


def _fmt_linkedin(items):
    unread = [i for i in items if i.get('unread') and not (i.get('snippet') or '').lower().startswith('you:')]
    spons = [i for i in unread if (i.get('snippet') or '').lower().startswith('sponsored')]
    real = [i for i in unread if i not in spons]
    if not real and not spons:
        return f"Nothing new on LinkedIn, {CALL()}."
    tail = f", plus {len(spons)} sponsored" if spons else ''
    if not real:
        return f"On LinkedIn, just {len(spons)} sponsored, {CALL()}."
    first = real[0]
    late = f" Latest message: {first['name']}, '{_snip(first.get('snippet'))}'" + (f", at {first['time']}." if first.get('time') else '.')
    if len(real) == 1:
        return f"On LinkedIn, {first['name']} sent one{tail}.{late}"
    return f"On LinkedIn, {len(real)} unread: {_names([i['name'] for i in real])}{tail}.{late}"


_EMOJI = re.compile('[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d\u202a-\u202e]')


def _wa_clean(s):
    return re.sub(r'\s+', ' ', _EMOJI.sub('', s or '')).strip()


def _wa_when(tm):
    tm = (tm or '').strip()
    return '' if not tm else (f"at {tm}" if re.match(r'\d{1,2}:\d{2}', tm) else tm.lower() if tm.lower() in ('yesterday', 'today') else f"on {tm}")


def _fmt_whatsapp(items):
    """Up to 5 chats whose last message is theirs, unread ones first (the list is newest first): "Athar: 'are you coming?', 7:40."."""
    theirs = [i for i in items if not i.get('me')]
    un = [i for i in theirs if i.get('unread')]
    if not theirs:
        return f"Nothing new on WhatsApp, {CALL()}."
    bits = []
    for i in (un or theirs)[:5]:
        w = _wa_when(i.get('time'))
        bits.append(f"{_wa_clean(i['name']) or 'Someone'}: '{_snip(_wa_clean(i.get('snippet')), 50) or 'a message'}'" + (f", {w}" if w else ''))
    head = f"{len(un)} unread chat{'s' if len(un) != 1 else ''} on WhatsApp" + (f", newest {len(bits)}" if len(un) > len(bits) else '') if un else "Nothing unread on WhatsApp. Latest chats"
    return f"{head}. " + '. '.join(bits) + '.'


def _fmt_gmail(items):
    if not items:
        return f"Nothing unread in your Gmail, {CALL()}."
    bits = [(i['name'] or 'Someone') + (f", about {_snip(i['subject'])}" if i.get('subject') else '') for i in items[:5]]
    return f"Gmail: {len(items)} unread: " + '; '.join(bits) + '.'


# site -> (label, tab URL fragment, inbox URL, js, formatter, may open a tab when none is open)
INBOX = {'linkedin': ('LinkedIn', 'linkedin.com/messaging', 'https://www.linkedin.com/messaging/', _LI_JS, _fmt_linkedin, True),
         'whatsapp': ('WhatsApp', 'web.whatsapp.com', 'https://web.whatsapp.com/', _WA_JS, _fmt_whatsapp, False),
         'gmail': ('Gmail', 'mail.google.com', 'https://mail.google.com/mail/u/0/#inbox', _GM_JS, _fmt_gmail, False)}


def _tab_exec(b, host, js, goto=None):
    """Run js in the first tab whose URL contains host (read-only, never activates it). With goto, only points that
    tab at the inbox URL instead. Returns the script's text, or NOBROWSER / NOTAB."""
    safari = _is_safari(b)
    act = f'set URL of t to {_as_str(goto)}\nreturn "RELOADING"' if goto else (
        f'return (do JavaScript {_as_str(js)} in t)' if safari else f'return (execute t javascript {_as_str(js)})')
    return _osa('if application "%s" is not running then return "NOBROWSER"\ntell application "%s"\n repeat with w in windows\n'
                '  repeat with t in tabs of w\n   if (URL of t) contains "%s" then\n%s\n   end if\n  end repeat\n end repeat\nend tell\nreturn "NOTAB"'
                % (b, b, host, act), 15)


def _open_bg(b, url):
    """New tab in the background; the tab you're on stays active."""
    if _is_safari(b):
        _osa('tell application "%s"\n if (count of windows) = 0 then make new document\n set w to front window\n set ct to current tab of w\n'
             ' tell w to make new tab with properties {URL:%s}\n set current tab of w to ct\nend tell' % (b, _as_str(url)), 15)
    else:
        _osa('tell application "%s"\n if (count of windows) = 0 then make new window\n set w to front window\n set ai to active tab index of w\n'
             ' tell w to make new tab with properties {URL:%s}\n set active tab index of w to ai\nend tell' % (b, _as_str(url)), 15)


def _poll(b, host, js, tries=8):
    """Read until the page has rows and has finished loading (up to ~8 s). -> parsed dict or None."""
    data = None
    for _ in range(tries):
        time.sleep(1)
        try:
            data = json.loads(_tab_exec(b, host, js))
        except Exception:
            data = None
        if isinstance(data, dict) and data.get('n') and data.get('rs') == 'complete':
            return data
    return data if isinstance(data, dict) else None


def _read_inbox(key, may_open=None):
    label, host, url, js, fmt, can_open = INBOX[key]
    b = _browser()
    sb = _short(b)
    try:
        raw = _tab_exec(b, host, js)
        if raw == 'NOBROWSER':
            return f"{sb} isn't open, {CALL()}."
        if raw == 'NOTAB':
            if not (can_open if may_open is None else may_open):
                return f"{label} isn't open in {sb}, {CALL()}."
            _open_bg(b, url)
            data = _poll(b, host, js)
        else:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get('len', 0) < 300:   # a sleeping tab: wake the same tab on its inbox
                _tab_exec(b, host, js, goto=url)
                data = _poll(b, host, js)
    except Exception as e:
        if 'javascript' in str(e).lower() and not _is_safari(b):
            return f"I can't read {sb} tabs yet, {CALL()}. In {sb}, turn on View, Developer, Allow JavaScript from Apple Events."
        if 'javascript' in str(e).lower():
            return f"I can't read Safari tabs yet, {CALL()}. In Safari, turn on Develop, Allow JavaScript from Apple Events."
        return f"I couldn't read {label}, {CALL()}."
    if not isinstance(data, dict) or not isinstance(data.get('items'), list) or (not data['items'] and key != 'gmail'):
        return f"I couldn't read {label}'s list, {CALL()}." if key == 'whatsapp' else f"I couldn't read {label}, {CALL()}."
    if key == 'gmail' and not data['items'] and not data.get('any') and data.get('len', 0) < 300:
        return f"I couldn't read Gmail, {CALL()}."
    return fmt(data['items'])


_WHO = re.compile(r"^who (?:has |all )?(?:messaged|texted|emailed|mailed|wrote|dm ?e?d|sent)(?: me)?(?: (?:on|in|from) (?P<s>linkedin|whatsapp|gmail|mail|email))?(?: today| lately| just now| recently)?$")
_READ_MSGS = re.compile(r"^(?:read|show) (?:me )?(?:my )?(?P<s>linkedin|whatsapp|gmail) (?:messages|dms|mail|emails?|inbox)$")
_FOLLOW = re.compile(r"^(?:who are they from|who sent them|who are they|read them|read them out|read them to me|who is it from|whos it from|who from)$")
_YES = re.compile(r"^(?:yes|yes please|yeah|yep|sure|go ahead|please do|yes go ahead|ok|okay|yes read them)$")


def _site_key(s):
    return {'mail': 'gmail', 'email': 'gmail', 'emails': 'gmail'}.get(s, s)


def _inbox_phrase(t):
    """'who messaged me', 'read my linkedin messages', and the follow-up 'yes' / 'read them' after an offer."""
    m = _WHO.match(t) or _READ_MSGS.match(t)
    if m:
        s = m.groupdict().get('s') or ('gmail' if re.search(r'\b(?:e?mailed|mail)\b', t) else None)   # "who emailed me" = Gmail only
        if s:
            return _read_inbox(_site_key(s))
        out = [r for r in (_read_inbox(k, False) for k in INBOX) if r and "isn't open" not in r]
        return ' '.join(out) if out else f"LinkedIn, WhatsApp and Gmail aren't open in your browser, {CALL()}."
    if _FOLLOW.match(t) or _YES.match(t):
        sites = _take_offer()
        if not sites:
            return None   # a bare yes with no fresh offer may answer an approval card
        import zuka_work
        return ' '.join(_read_inbox(k, True if k == 'whatsapp' else None) if k in INBOX else zuka_work._chat(k) for k in sites)
    return None


# ---------------------------------------------------------------- entry
def handle(t, raw=None):
    said = _handle(t, raw)
    if said is None:   # the wider set of free Mac commands (zuka_more.py), last, so the commands above win
        try:
            import zuka_work, zuka_more
            r0 = raw if isinstance(raw, str) and raw.strip() else (t if isinstance(t, str) else '')   # what was really said (case kept) when the caller has it
            said = zuka_work.handle(_norm(t), r0) or zuka_more.handle(_norm(t), r0)
        except ImportError: pass
        except Exception: said = FAIL.format(call=CALL()) if '{call}' in FAIL else None
    return clean_call(said)


def _handle(t, said=None):
    try:
        raw = t if isinstance(t, str) else ''
        spoken = said if isinstance(said, str) and said.strip() else raw   # exactly as said (case kept): messages are sent in these words
        t = _norm(t)
        try:   # a yes / no / which-one for a message waiting to be sent comes before every other yes/no handler
            import zuka_msg
            r = zuka_msg.confirm(t)
            if r: return r
        except Exception: pass
        try:   # learned phrasings -> the phrasing that works; free taste-music requests are played and answered here
            import zuka_learn
            t = zuka_learn.alias(t)
            if t.startswith(zuka_learn.SAID): return t[len(zuka_learn.SAID):]
        except Exception: pass
        if not t:
            return None
        p = _pending()
        if p and p.get('kind') == 'remind' and not t.startswith(('remind me', 'cancel', 'never mind', 'nevermind', 'stop')):
            _pending(clear=True)   # the answer to "What should I remind you about?" / "When should I remind you?"
            said = _remind(f"remind me to {raw.strip().rstrip('.!?')} {p['when']}" if 'when' in p else f"remind me to {p['task']} {raw.strip().rstrip('.!?')}")
            if said: return said
        elif p and t.startswith(('cancel', 'never mind', 'nevermind')):
            _pending(clear=True); return f"Okay, no reminder{call_suffix()}."
        said = _end_of_day(t)
        if said:
            return said
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
        m = _OPEN_WEB.match(t)
        if m and m.group('w') in WEB:
            return _open_web(m.group('w'))
        try:
            import zuka_msg
            r = zuka_msg.handle(t, spoken)   # read / send WhatsApp, Slack, Discord (a send always waits for a spoken yes)
        except ImportError:
            r = None
        if r:
            return r
        try:
            import zuka_work
            r = zuka_work.handle_chat(t)   # Slack / Discord are read from the apps themselves
        except ImportError:
            r = None
        if r:
            return r
        r = _inbox_phrase(t)
        if r:
            return r
        if _asks_health(t):
            return _health(True)
        if _UNREAD.match(t) or _asks_inbox(t):
            return _unread()
        if _VOICE_LIST.match(t):
            return _voice_list()
        m = _VOICE_SET.match(t)
        if m and m.group(1) in _ALIASES:
            return _set_voice(_ALIASES[m.group(1)])
        if _KEEP.match(t) and time.time() - _pick().get('at', 0) < 600:
            return f"Done, {CALL()}. That's my voice now."
        sites = _sites()
        m = _site_re(sites).match(t)
        if m and t != m.group(1):   # a bare site name is not a check
            return _site(m.group(1))
        if _CAL_NEXT.match(t):
            return _calendar(False)
        if _CAL_TODAY.match(t):
            return _calendar(True)
        return _basics(t, raw)
    except Exception:
        return FAIL.format(call=CALL())
