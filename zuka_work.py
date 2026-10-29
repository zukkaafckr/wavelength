"""Zuka's daily-workflow commands, all free (no Claude): ClickUp assignments, tracker pages, WhatsApp detail.

zuka_commands.handle() calls handle(t, raw) before zuka_more. t = normalised lowercase words, raw = what was said.
Returns a short spoken reply or None. Work-specific values (ClickUp ids, tracker links) come from the person's
workflow.json keys `clickup` and `trackers`; nothing here is hard-coded to one person. Read-only: nothing is sent or changed.
Run `python3 zuka_work.py --check-clickup` for the scheduled check (prints only when there is something new).
"""
import json
import os
import plistlib
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zuka_commands as zc  # noqa: E402
import zuka_apps as apps  # noqa: E402

API = 'https://api.clickup.com/api/v2'
NO_KEY_NEEDED = "No key needed. I read the ClickUp app on your Mac directly."
OFFER_WINDOW = 180
DAY_MS = 24 * 3600 * 1000
SAY = os.path.expanduser('~/.local/share/chatterbox/atticus-say')


def _c():
    return zc.call_suffix()


def _dir():
    return os.environ.get('ATTICUS_DIR') or os.path.join(os.path.expanduser('~'), '.config/atticus')


def _seen_file(): return os.path.join(_dir(), 'clickup-seen.json')
def _offer_file(): return os.path.join(_dir(), 'work-offer.json')


def _jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _jsave(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f)
    except OSError:
        pass


def _wf_raw():
    d = _jload(zc.WORKFLOW, {})
    return d if isinstance(d, dict) else {}


def _wf_merge(key, values):
    """Merge values into workflow.json[key], keeping everything else."""
    d = _wf_raw()
    cur = d.get(key) if isinstance(d.get(key), dict) else {}
    cur.update(values)
    d[key] = cur
    _jsave(zc.WORKFLOW, d)


def _cfg():
    c = _wf_raw().get('clickup')
    return c if isinstance(c, dict) else {}


# ---------------------------------------------------------------- ClickUp
class NoToken(Exception):
    pass


def _token():
    r = zc._run(['security', 'find-generic-password', '-s', 'wavelength-clickup', '-a', 'clickup', '-w'], 5)
    tok = (r.stdout or '').strip() if r.returncode == 0 else ''
    if not tok:
        raise NoToken()
    return tok


def _api(path, tok, timeout=10):
    """GET a ClickUp v2 path -> parsed JSON; NoToken on 401/403; None on any other failure."""
    try:
        req = urllib.request.Request(API + path, headers={'Authorization': tok, 'User-Agent': 'curl/8.4.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise NoToken()
        return None
    except Exception:
        return None


def _field_names(task, field_id):
    """Names held by the editor custom field (drop-down / labels / users / text)."""
    for f in task.get('custom_fields') or []:
        if f.get('id') != field_id:
            continue
        v, typ = f.get('value'), f.get('type')
        opts = (f.get('type_config') or {}).get('options') or []
        if v is None or v == '':
            return []
        if typ == 'drop_down':
            return [str(o.get('name') or o.get('label')) for o in opts if o.get('orderindex') == v or o.get('id') == v]
        if typ == 'labels':
            vs = v if isinstance(v, list) else [v]
            return [str(o.get('label') or o.get('name')) for o in opts if o.get('id') in vs]
        if typ == 'users':
            return [str(u.get('username') or u.get('email') or '') for u in (v if isinstance(v, list) else [v]) if isinstance(u, dict)]
        return [str(v)]
    return []


def _is_mine(task, cfg, my_id=None):
    me = (cfg.get('me') or '').strip().lower()
    if not me and not my_id:
        return False
    for a in task.get('assignees') or []:
        if (my_id and str(a.get('id')) == str(my_id)) or (me and me in str(a.get('username') or '').lower()):
            return True
    return any(me and me in n.lower() for n in _field_names(task, cfg.get('editorFieldId')))


def _team_id(tok, cfg):
    if cfg.get('teamId'):
        return cfg['teamId']
    d = _api('/team', tok)
    teams = (d or {}).get('teams') or []
    if teams:
        _wf_merge('clickup', {'teamId': str(teams[0]['id'])})
        return str(teams[0]['id'])
    return None


def _fetch_mine(window_ms=DAY_MS):
    """My tasks in the ads-board list touched in the window. Raises NoToken. -> list of {id,name,status,url,creator,created}."""
    cfg = _cfg()
    if not cfg.get('listId'):
        return None
    tok = _token()
    _team_id(tok, cfg)   # discovered once and cached; not needed for the list call itself
    since = int(time.time() * 1000) - window_ms
    out, page = [], 0
    while page < 5:
        d = _api(f"/list/{cfg['listId']}/task?include_closed=false&subtasks=true&order_by=updated&reverse=true&date_updated_gt={since}&page={page}", tok)
        if d is None:
            return None if page == 0 else out
        tasks = d.get('tasks') or []
        for t in tasks:
            if _is_mine(t, cfg):
                out.append({'id': str(t.get('id')), 'name': (t.get('name') or '').strip(),
                            'status': ((t.get('status') or {}).get('status') or '').strip(),
                            'url': t.get('url') or f"https://app.clickup.com/t/{t.get('id')}",
                            'creator': str((t.get('creator') or {}).get('username') or '')})
        if d.get('last_page', True) or not tasks:
            break
        page += 1
    return out


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _clickup_reply(tasks, new_only, cfg, offer=True, noun='task'):
    ass = (cfg.get('assigner') or '').strip()
    if not tasks:
        return f"Nothing new for you on the ads board{_c()}." if new_only else f"Nothing assigned to you in the last day{_c()}."
    titles = [f"'{t['name']}'" for t in tasks[:3]]
    listed = ' and '.join(titles) if len(titles) < 3 else f"{titles[0]}, {titles[1]}, and {titles[2]}"
    more = f", plus {len(tasks) - 3} more" if len(tasks) > 3 else ''
    by = ass and all(ass.lower() in t['creator'].lower() for t in tasks)
    head = f"{ass.capitalize()} assigned you" if by else "You've got"
    word = ('new ' if new_only and not by else '') + noun
    s = f"{head} {_plural(len(tasks), word)}{' today' if by and not new_only else ''}: {listed}{more}."
    return s + (" Want me to open them?" if offer else '')


def _set_work_offer(urls):
    _jsave(_offer_file(), {'urls': urls, 'at': time.time()})


def _take_work_offer():
    d = _jload(_offer_file(), None)
    try:
        os.remove(_offer_file())
    except OSError:
        pass
    if isinstance(d, dict) and time.time() - d.get('at', 0) <= OFFER_WINDOW and d.get('urls'):
        return d['urls']
    return None


def _open_urls(urls):
    if urls and urls[0] == 'clickup:inbox':
        apps.open_view('ClickUp', 'inbox')
        return f"ClickUp's up{_c()}."
    for u in urls[:5]:
        if 'clickup.com' in u:   # ClickUp always opens in its desktop app, never the browser
            zc._run(['open', '-a', 'ClickUp', u], 10)
        else:
            zc._open_browser(u)
    return f"Opened {_plural(len(urls[:5]), 'task')}{_c()}."


def _has_token():
    """True only if a ClickUp key already sits in the Keychain. Never asked for; the app reader is the default."""
    try:
        r = zc._run(['security', 'find-generic-password', '-s', 'wavelength-clickup', '-a', 'clickup'], 5)
        return r.returncode == 0
    except Exception:
        return False


def _age_days(date, now=None):
    """'Oct 26' / '1:37 pm' / 'Today' -> days old (None if unknown)."""
    now = now or datetime.now()
    d = (date or '').strip()
    if re.match(r'^(?:today|\d{1,2}:\d{2}\s?[ap]m|\d+\s?(?:m|h|min|hr)\b)', d, re.I):
        return 0
    if d.lower() == 'yesterday':
        return 1
    m = re.match(r'^([A-Za-z]{3}) (\d{1,2})(?:, (\d{4}))?$', d)
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3) or now.year}", '%b %d %Y')
    except ValueError:
        return None
    if dt > now and not m.group(3):
        dt = dt.replace(year=dt.year - 1)
    return (now - dt).days


ASSIGN_DAYS = 14
ACTIVE_GROUPS = ('IN PROGRESS', 'NEW REQUEST', 'READY FOR EDITING', 'WAITING FOR BRIEF')


def _snapshot():
    cfg = _cfg()
    snap = apps.clickup_snapshot(cfg.get('me') or '')
    if not snap:
        return None
    mine = [i for i in snap['inbox'] if i['assigned'] and (_age_days(i['date']) is None or _age_days(i['date']) <= ASSIGN_DAYS)]
    snap['assigned'] = [dict(i, key=f"a:{i['task']}|{i['date']}") for i in mine]
    snap['mine'] = [dict(t, key=f"b:{t['name']}") for t in snap['board'] if t['mine'] and t['group'] in ACTIVE_GROUPS + ('IN REVIEW',)]
    snap['active'] = [dict(t, key=f"b:{t['name']}") for t in snap['board'] if t['group'] in ACTIVE_GROUPS]
    return snap


def _quote_list(names):
    q = [f"'{n}'" for n in names[:3]]
    s = ' and '.join(q) if len(q) < 3 else f"{q[0]}, {q[1]}, and {q[2]}"
    return s + (f", plus {len(names) - 3} more" if len(names) > 3 else '')


def _app_reply(snap, new_only, noun, board_all=False, offer=True):
    seen = set(_jload(_seen_file(), []))
    ass = [i for i in snap['assigned'] if not new_only or i['key'] not in seen]
    pool = snap['active'] if board_all else snap['mine']
    brd = [t for t in pool if not new_only or t['key'] not in seen]
    _jsave(_seen_file(), sorted(seen | {i['key'] for i in snap['assigned']} | {t['key'] for t in snap['mine'] + snap['active']}))
    parts = []
    if ass:
        whos = {i['who'] for i in ass if i['who']}
        by = f"{next(iter(whos))} assigned you" if len(whos) == 1 and all(i['who'] for i in ass) else "You've got"
        word = ('new ' if new_only and by == "You've got" else '') + noun
        dates = f", {ass[0]['date']}" if len(ass) == 1 else ''
        parts.append(f"{by} {_plural(len(ass), word)} in your ClickUp inbox: {_quote_list([i['task'] for i in ass])}{dates}.")
    if brd:
        if board_all:
            parts.append(f"On the Ads Board {'new in progress' if new_only else 'in progress'}: {_quote_list([t['name'] for t in brd])}.")
        else:
            parts.append(f"On the Ads Board you're down as editor on {_quote_list([t['name'] for t in brd])}.")
    unread = snap.get('unread')
    if not parts:
        base = "Nothing new for you in ClickUp" if new_only else "Nothing assigned to you in ClickUp in the last two weeks"
        parts.append(base + (f", but {unread} unread notifications are sitting in your inbox." if unread else '.'))
    elif unread:
        parts.append(f"{unread} unread in your inbox overall.")
    if ass or brd or unread:
        if offer:
            _set_work_offer(['clickup:inbox'])
            parts.append("Want me to open ClickUp?")
    return ' '.join(parts).replace('..', '.')


def _clickup(new_only, noun='task', board_all=False):
    snap = _snapshot()
    if snap:
        return _app_reply(snap, new_only, noun, board_all)
    if _has_token() and _cfg().get('listId'):   # silent fallback for owners who already have a key; never asked for
        try:
            tasks = _fetch_mine()
        except NoToken:
            tasks = None
        if tasks is not None:
            seen = set(_jload(_seen_file(), []))
            shown = [t for t in tasks if t['id'] not in seen] if new_only else tasks
            _jsave(_seen_file(), sorted(seen | {t['id'] for t in tasks}))
            if shown:
                _set_work_offer([t['url'] for t in shown])
            return _clickup_reply(shown, new_only, _cfg(), noun=noun)
    return f"I couldn't read the ClickUp app just now{_c()}. Is it signed in?"


def check_clickup():
    """Scheduled check: a spoken summary only when an assignment is new since last seen, else ''. Silent on any problem."""
    try:
        snap = _snapshot()
        if snap:
            seen = set(_jload(_seen_file(), []))
            new = [i for i in snap['assigned'] if i['key'] not in seen]
            out = _app_reply(dict(snap, assigned=new, mine=[], active=[], unread=None), True, 'task', offer=False) if new else ''
            _jsave(_seen_file(), sorted(set(_jload(_seen_file(), [])) | {i['key'] for i in snap['assigned']}))
            return out
        if not _has_token():
            return ''
        tasks = _fetch_mine()
    except Exception:
        return ''
    if not tasks:
        return ''
    seen = set(_jload(_seen_file(), []))
    new = [t for t in tasks if t['id'] not in seen]
    _jsave(_seen_file(), sorted(seen | {t['id'] for t in tasks}))
    return _clickup_reply(new, True, _cfg(), offer=False) if new else ''


def install_clickup_check(times=("15:00",)):
    """Write ~/Library/LaunchAgents/com.wavelength.clickupcheck.plist (Mon-Sat). Does not load it. -> the plist path."""
    cal = []
    for tm in times:
        h, m = (int(x) for x in tm.split(':'))
        cal += [{'Weekday': d, 'Hour': h, 'Minute': m} for d in range(1, 7)]
    script = ('out=$(/usr/bin/python3 "$1" --check-clickup 2>/dev/null); [ -n "$out" ] || exit 0; '
              f'[ -x "{SAY}" ] && "{SAY}" "$out"; '
              '/usr/bin/osascript -e \'on run argv\' -e \'display notification (item 1 of argv) with title "ClickUp"\' -e \'end run\' "$out"')
    plist = {'Label': 'com.wavelength.clickupcheck',
             'ProgramArguments': ['/bin/bash', '-c', script, 'clickupcheck', str(Path(__file__).resolve())],
             'StartCalendarInterval': cal, 'RunAtLoad': False}
    path = Path(os.path.expanduser('~')) / 'Library/LaunchAgents/com.wavelength.clickupcheck.plist'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as f:
        plistlib.dump(plist, f)
    return str(path)


def install_hiring_check(minutes=120, at_mac_secs=600):
    """Write ~/Library/LaunchAgents/com.wavelength.hiringcheck.plist: every `minutes`, and once at load, but only while the person is at
    the Mac (touched keyboard or mouse in the last `at_mac_secs`). Speaks and notifies only when something is new. -> the plist path."""
    script = (f'idle=$(/usr/sbin/ioreg -c IOHIDSystem | /usr/bin/awk \'/HIDIdleTime/ {{print int($NF/1000000000); exit}}\'); [ "${{idle:-0}}" -lt {at_mac_secs} ] || exit 0; '
              'out=$(/usr/bin/python3 "$1" --check-hiring 2>/dev/null); [ -n "$out" ] || exit 0; '
              f'[ -x "{SAY}" ] && "{SAY}" "$out"; '
              '/usr/bin/osascript -e \'on run argv\' -e \'display notification (item 1 of argv) with title "Hiring"\' -e \'end run\' "$out"')
    plist = {'Label': 'com.wavelength.hiringcheck',
             'ProgramArguments': ['/bin/bash', '-c', script, 'hiringcheck', str(Path(__file__).resolve().with_name('zuka_hiring.py'))],
             'StartInterval': minutes * 60, 'RunAtLoad': True}
    path = Path(os.path.expanduser('~')) / 'Library/LaunchAgents/com.wavelength.hiringcheck.plist'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as f:
        plistlib.dump(plist, f)
    return str(path)


_HOW = re.compile(r"^how (?:do i|can i|to) (?:connect|set up|setup|link) click ?up(?: to (?:you|zuka))?$")
_CU = re.compile(r"^(?:did (?P<who>\w+) (?:assign|give|send) me (?:any |a |some )?(?:new )?(?:scripts?|tasks?|work)(?: today| yet)?"
                 r"|(?:are there |is there )?any new (?:scripts?|tasks?)(?: for me)?(?: today)?"
                 r"|(?:what s|whats|what is) assigned to me(?: today)?"
                 r"|check click ?up"
                 r"|(?:any|anything)(?: new)? click ?up (?:tasks?|scripts?|work|updates?|notifications?)(?: for me)?"
                 r"|(?:what|which) (?:tasks?|scripts?|work) (?:do i have|have i got|are (?:there )?(?:for me|assigned to me|on my plate))(?: today| now)?"
                 r"|(?:what s|whats|what is) on my plate(?: today)?"
                 r"|(?:any|anything)(?: new)? (?:scripts?|tasks?|work) for me(?: (?:on|in) click ?up)?"
                 r"|(?:are there |is there |do i have )?any(?:thing)?(?: new)?(?: scripts?| tasks?| work)? (?:on|in) click ?up(?: for me)?"
                 r"|(?:what s|whats|what is) new on the ads board"
                 r"|anything new (?:on|in) click ?up"
                 r"|(?:are there |is there |do i have )?any(?:thing)?(?: new)?(?: scripts?| tasks?| work)? (?:on|in|from) (?:my )?click ?up"
                 r"|(?:what s|whats|what is|what have i got|what do i have)(?: new)? (?:on|in) (?:my )?click ?up"
                 r"|(?:show |read |tell |give )?(?:me )?my click ?up(?: tasks?| scripts?| inbox| board)?"
                 r"|any(?:thing)?(?: new)?(?: scripts?| tasks?| work)? from (?P<who2>\w+)(?: today)?"
                 r"|did (?P<who3>\w+) (?:send|give|assign) me anything(?: today| new)?)$")


# ---------------------------------------------------------------- trackers (the claude.ai page runs in a cross-origin iframe)
def _trackers():
    d = _wf_raw().get('trackers')
    return d if isinstance(d, dict) else {}


_TRK = re.compile(r"^(?:(?P<td>takedown update|hows the takedown tracker|how many ads did i take down|takedown tracker)"
                  r"|(?P<wn>winning ads update|any new winners|hows the winning ads tracker|winning ads tracker))$")


_TRK_OPEN = re.compile(r"^(?:open|show|pull up|bring up|go to)(?: me)?(?: up)?(?: the| my)?(?: hoa)? (?:(?P<td>takedown)|(?P<wn>winning(?: ads?)?|winners?))(?: ads?)?(?: tracker| board| page| sheet)?$")
_TRK_UPD = re.compile(r"^(?:(?:give me |get me |show me |tell me |read me |what s |whats |what is )?(?:an |the |any )?(?:update|status|summary|latest|news) (?:on|of|from|for|in)(?: the| my)?(?: hoa)? |(?:how s|hows|how is|check|read)(?: the| my)?(?: hoa)? )"
                      r"(?:(?P<td>takedown)|(?P<wn>winning(?: ads?)?|winners?))(?: ads?)?(?: tracker| board| page| sheet)?$|"
                      r"^(?:hoa )?(?:(?P<td2>takedown)|(?P<wn2>winning(?: ads?)?|winners?))(?: ads?)? tracker (?:update|status|summary|latest)$")


def _focus_tab(b, key):
    """Bring the browser tab whose URL contains key to the front. True if one was open."""
    saf = zc._is_safari(b)
    pick = 'set current tab of w to t' if saf else 'set active tab index of w to i'
    try:
        out = zc._osa('if application "%s" is not running then return "no"\ntell application "%s"\nrepeat with w in windows\nset i to 0\nrepeat with t in tabs of w\nset i to i + 1\n'
                      'if (URL of t) contains "%s" then\n%s\nset index of w to 1\nactivate\nreturn "yes"\nend if\nend repeat\nend repeat\nend tell\nreturn "no"' % (b, b, key, pick), 15)
    except Exception:
        return False
    return out == 'yes'


def _tracker_text(url, wait=22):
    """Open (or reuse) the tracker tab, wait for it to render, read the window text through the accessibility tree. '' when unreadable."""
    b = zc._workflow()['browser']
    key = url.rstrip('/').rsplit('/', 1)[-1]
    if not _focus_tab(b, key):
        zc._open_browser(url)
    end, last, text = time.time() + wait, -1, ''
    while time.time() < end:
        time.sleep(2)
        d = apps.hands_read(b)
        text = (d or {}).get('text', '') if d else ''
        if len(text) > 400 and len(text) == last: break   # rendered and stable across two reads
        last = len(text)
    return text if len(text) > 200 else ''


def _tracker_say(kind, text):
    lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 3]
    ask = f"Summarise the HOA {'takedown' if kind == 'takedown' else 'winning ads'} tracker: the headline numbers and anything new, in one or two sentences."
    try:
        import zuka_chat
        said = zuka_chat.summarize('\n'.join(lines), ask)
    except Exception:
        said = None
    if said: return said
    pick = [l for l in lines if re.search(r'\d', l) and len(l) > 8 and not re.search(r'(?i)claude|sign in|log ?in|cookie|http', l)][:3] or lines[:3]
    return ('Here is what the tracker says: ' + '. '.join(l.rstrip('.') for l in pick) + f"{_c()}.") if pick else None


def _tracker_open(kind):
    url = _trackers().get(kind)
    if not url:
        return f"The {kind} tracker isn't set up in your workflow yet{_c()}."
    key = url.rstrip('/').rsplit('/', 1)[-1]
    if not _focus_tab(zc._workflow()['browser'], key):
        zc._open_browser(url)
    return f"Opening the {'takedown' if kind == 'takedown' else 'winning ads'} tracker{_c()}."


def _tracker_update(kind):
    url = _trackers().get(kind)
    if not url:
        return f"The {kind} tracker isn't set up in your workflow yet{_c()}."
    text = _tracker_text(url)
    return _tracker_say(kind, text) if text else None   # unreadable: Claude takes it


def _tracker(kind):
    url = _trackers().get(kind)
    if not url:
        return f"The {kind} tracker isn't set up in your workflow yet{_c()}."
    # claude.ai artifacts render inside a sandboxed iframe on another origin: AppleScript JS in the tab sees only the empty
    # outer shell, and the page's data lives behind a private API. So the numbers can't be read without Claude.
    _jsave(_offer_file(), {'urls': [url], 'at': time.time()})
    return f"I can't read the {kind} tracker page right now{_c()}. Want me to open it for you?"


_HIRE = re.compile(r"^(?:check (?:the )?(?:hiring|applicants?|candidates?|assessments?)(?: pipeline| submissions?)?"
                   r"|(?:any|are there any|is there any|did anyone|has anyone)(?: new)? (?:applicants?|candidates?|applications?|assessments?|assessment submissions?|submitted(?: an)? assessments?|submit(?:ted)?(?: an)? assessments?)(?: today| yet| now)?"
                   r"|(?:any|anything) (?:new )?(?:in|on) (?:the )?(?:hiring pipeline|applied)"
                   r"|who (?:applied|submitted)(?: an assessment)?(?: today)?)$")


# ---------------------------------------------------------------- WhatsApp: what did <name> say
_WA_SAY = re.compile(r"^what (?:did|has) (?P<n>[a-z0-9 ]+?) (?:say|said|send|sent|write|wrote|text|texted)(?: to me)?(?: on whatsapp| in whatsapp| over whatsapp)$")
_WA_LATEST = re.compile(r"^(?:latest|recent|new|last) whatsapp (?:messages|chats|texts)$")


def _wa_say(name):
    b = zc._browser()
    sb = zc._short(b)
    try:
        raw = zc._tab_exec(b, 'web.whatsapp.com', zc._WA_JS)
        if raw == 'NOBROWSER':
            return f"{sb} isn't open{_c()}."
        if raw == 'NOTAB':
            return f"WhatsApp isn't open in {sb}{_c()}."
        items = json.loads(raw).get('items') or []
    except Exception as e:
        if 'javascript' in str(e).lower():
            return f"I can't read {sb} tabs yet{_c()}. In {sb}, turn on View, Developer, Allow JavaScript from Apple Events."
        return f"I couldn't read WhatsApp{_c()}."
    want = name.lower().strip()
    hit = next((i for i in items if want in zc._norm(zc._wa_clean(i.get('name')))), None)
    if not hit:
        return f"I don't see a chat with {name} in your WhatsApp list{_c()}."
    w = zc._wa_when(hit.get('time'))
    msg = zc._snip(zc._wa_clean(hit.get('snippet')), 160) or 'a message with no text'
    who = zc._wa_clean(hit['name'])
    if hit.get('me'):
        return f"Your last message to {who} was '{msg}'" + (f", {w}." if w else '.')
    return f"{who} said '{msg}'" + (f", {w}." if w else '.')


# ---------------------------------------------------------------- Slack / Discord (read from the apps, free)
_CHAT = re.compile(r"^(?:(?:any|anything|do i have any|have i got any|got any)(?: new| unread)?(?: messages| dms| notifications)?(?: for me)? (?:on|in|from) (?P<a>slack|discord)"
                   r"|(?:check|read|open and read) (?P<b>slack|discord)(?: messages| dms| notifications)?"
                   r"|who (?:messaged|texted|dmd|dmed|pinged) me (?:on|in) (?P<c>slack|discord)"
                   r"|(?P<d>slack|discord) (?:messages|dms|notifications|unread))(?: please)?$")


def _names(xs, n=4):
    xs = list(xs)
    return _quote_list_plain(xs[:n]) + (f", plus {len(xs) - n} more" if len(xs) > n else '')


def _quote_list_plain(xs):
    return ' and '.join(xs) if len(xs) < 3 else ', '.join(xs[:-1]) + ', and ' + xs[-1]


def _chat(key):
    st = apps.chat_status(key)
    if not st:
        return f"I couldn't read {apps.CHAT_APPS[key]} just now{_c()}. Is it signed in?"
    app, bits = st['app'], []
    if key == 'discord':
        if st['dms']:
            bits.append(f"unread messages from {_names(st['dms'])}")
        if st['servers']:
            bits.append(f"activity in {_names(st['servers'])}")
    else:
        if st['unread']:
            bits.append(f"unread in {_names(st['unread'])}")
        if st['dms']:
            bits.append(f"latest in your DMs: {'; '.join(st['dms'][:3])}")
    if not bits and not st['badge']:
        return f"Nothing unread on {app}{_c()}."
    head = f"{app} shows {st['badge']} on its badge" if st['badge'] else f"{app} has"
    return f"{head}{': ' if bits else ''}{'; '.join(bits)}.".replace(' has.', ' has nothing new.')


def handle_chat(t):
    """'any messages on slack' / 'check discord' -> spoken reply, else None."""
    m = _CHAT.match(zc._norm(t))
    return _chat(next(g for g in m.group('a', 'b', 'c', 'd') if g)) if m else None


# ---------------------------------------------------------------- entry
def handle(t, raw=''):
    try:
        t = zc._norm(t)
        if not t:
            return None
        if _HOW.match(t):
            return NO_KEY_NEEDED
        m = _CU.match(t)
        if m:
            return _clickup('any new' in t or 'anything' in t or 'whats new' in t, 'script' if 'script' in t else 'task', 'ads board' in t)
        m = _TRK_OPEN.match(t)
        if m:
            return _tracker_open('takedown' if m.group('td') else 'winning')
        m = _TRK_UPD.match(t)
        if m:
            return _tracker_update('takedown' if (m.group('td') or m.group('td2')) else 'winning')
        m = _TRK.match(t)
        if m:
            return _tracker('takedown' if m.group('td') else 'winning')
        if _HIRE.match(t):
            import zuka_hiring
            return zuka_hiring.handle_now()
        if _WA_LATEST.match(t):
            return zc._read_inbox('whatsapp')
        m = _WA_SAY.match(t)
        if m:
            return _wa_say(m.group('n'))
        if re.match(r"^(?:yes|yes please|yeah|yep|sure|go ahead|ok|okay|open them|open it)$", t):
            urls = _take_work_offer()
            if urls:
                return _open_urls(urls)
        return None
    except Exception:
        return zc.FAIL.format(call=zc.CALL()) if '{call}' in zc.FAIL else None


if __name__ == '__main__':
    if '--check-clickup' in sys.argv:
        out = check_clickup()
        if out:
            print(out)
