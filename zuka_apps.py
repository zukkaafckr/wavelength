"""Local app readers for Zuka: read the owner's installed Mac apps directly, free (no API, no token, no browser).

Everything goes through the signed Wavelength binary (`Atticus --hands read <App>`), which has Accessibility permission,
plus the Dock's accessibility tree for unread badges. Navigation clicks only (Home, Go back, DMs); nothing that changes data.
"""
import json
import os
import re
import subprocess
import time

APP = os.path.expanduser('~/Applications/Atticus.app/Contents/MacOS/Atticus')
CHAT_APPS = {'slack': 'Slack', 'discord': 'Discord'}
BADGE_APPS = ('Slack', 'Discord', 'ClickUp', 'Mail', 'Messages', 'WhatsApp')
MONTHS = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec'
DATE = rf"(?:(?:{MONTHS}) \d{{1,2}}(?:, \d{{4}})?|Today|Yesterday|\d+\s?(?:m|h|d|w|min|hr|mo)\b(?: ago)?|\d{{1,2}}:\d{{2}}\s?[ap]m)"
FOCUS_KEEP = {'Slack', 'Discord', 'ClickUp'}


def _run(args, timeout=15):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return subprocess.CompletedProcess(args, 1, '', 'failed')


# ---------------------------------------------------------------- process / focus / badges
def running(name):
    r = _run(['pgrep', '-f', f'/{name}.app/Contents/MacOS/'], 5)
    return r.returncode == 0 and bool((r.stdout or '').strip())


def frontmost():
    r = _run(['osascript', '-e', 'tell application "System Events" to name of first process whose frontmost is true'], 5)
    return (r.stdout or '').strip() if r.returncode == 0 else ''


def refocus(prev):
    """Give focus back to the app the owner was using (Slack and Discord grab it when launched)."""
    if prev and frontmost() != prev:
        _run(['osascript', '-e', f'tell application "{prev}" to activate'], 5)


_DOCK_JS = ('const se=Application("System Events");const items=se.processes.byName("Dock").lists[0].uiElements();'
            'items.map(i=>{let n="",s="";try{n=i.name()}catch(e){};try{s=String(i.attributes.byName("AXStatusLabel").value())}catch(e){};'
            'return n+"\\t"+s}).join("\\n")')


def parse_dock(out):
    res = {}
    for line in (out or '').splitlines():
        name, _, label = line.partition('\t')
        label = label.strip()
        if not name or not label or label in ('null', 'missing value'):
            continue
        m = re.search(r'\d+', label)
        res[name.strip()] = int(m.group()) if m else 1   # a dot badge counts as one
    return res


def badges(names=BADGE_APPS):
    """Dock badge counts for the named apps that currently show one: {'ClickUp': 54}. {} when none or unreadable."""
    r = _run(['osascript', '-l', 'JavaScript', '-e', _DOCK_JS], 10)
    if r.returncode != 0:
        return {}
    allb = parse_dock(r.stdout)
    return {n: c for n, c in allb.items() if n in names and c > 0}


def badge_sentence():
    """'On your apps: 73 on Discord, 54 in ClickUp, and 1 on Slack.' for running apps with a badge, else ''."""
    b = {n: c for n, c in badges(('Slack', 'Discord', 'ClickUp')).items() if running(n)}
    if not b:
        return ''
    bits = [f"{c} in ClickUp" if n == 'ClickUp' else f"{c} on {n}" for n, c in sorted(b.items(), key=lambda x: -x[1])]
    return 'On your apps: ' + (bits[0] if len(bits) == 1 else ', '.join(bits[:-1]) + ', and ' + bits[-1]) + '.'


# ---------------------------------------------------------------- hands
def hands(args, timeout=20, head=False):
    """head=True reads only the first screenful (fast, ~0.3 s): enough to learn which page the app is on."""
    if head:
        try:
            return subprocess.run([APP, '--hands'] + args, capture_output=True, text=True, timeout=timeout,
                                  env=dict(os.environ, ATTICUS_HANDS_HEAD='1'))
        except Exception:
            return subprocess.CompletedProcess(args, 1, '', 'failed')
    return _run([APP, '--hands'] + args, timeout)


def hands_read(name, pages=1, head=False):
    """-> {'text','page','window','web'} read from the app's accessibility tree, or None."""
    out = None
    for i in range(max(1, pages)):
        r = hands(['read', name] + (['more'] if i else []), head=head)
        try:
            d = json.loads(r.stdout)
        except ValueError:
            return out
        if out is None:
            out = {'text': d.get('text', ''), 'page': d.get('page', ''), 'window': d.get('window', ''), 'web': bool(d.get('web'))}
        else:
            out['text'] += '\n' + d.get('text', '')
        if not d.get('incomplete'):
            break
    return out


def find_node(see_out, label):
    """The id of the best control for label in `see` output: an exact Link/Button/PopUpButton first (so a big Row that merely contains
    the word is never clicked), then one that starts with it. None if absent."""
    nodes = []
    for line in (see_out or '').splitlines():
        m = re.match(r'^\[(\d+)\] (\w+) "(.*?)"(?: = .*)? \(at', line)
        if m:
            nodes.append((m.group(1), m.group(2), m.group(3)))
    for ok in (lambda r, t: r in ('Link', 'Button', 'PopUpButton', 'MenuItem') and t == label,
               lambda r, t: r in ('Link', 'Button', 'PopUpButton') and (t.startswith(label + ' ') or t.endswith(' ' + label))):
        for i, r, t in nodes:
            if ok(r, t):
                return i
    return None


def hands_click(name, label):
    """Navigation click by label. `see` first so the click targets the app's current pid/window; clicks the matching control by id."""
    seen = hands(['see', name])
    target = find_node(seen.stdout, label)
    if target is None:
        return False
    return hands(['click', target]).returncode == 0


def ensure_running(name, wait=25):
    """Launch in the background if needed, then wait until its web content is readable. -> True when ready."""
    if running(name):
        return True
    _run(['open', '-g', '-a', name], 10)
    end = time.time() + wait
    while time.time() < end:
        d = hands_read(name)
        if d and d['web'] and len(d['text']) > 200:
            return True
        time.sleep(1.5)
    return False


def _wait_page(name, needle, wait=8):
    end = time.time() + wait
    d = None
    while time.time() < end:
        time.sleep(1)
        d = hands_read(name, 1, head=True)
        if d and needle in (d['page'] + ' ' + d['window']):
            return True
    return False


def read_app(name, view=None, pages=1, view_pages=2):
    """Read an installed app. Starts it in the background if needed. view (navigation clicks only, then restored):
    ClickUp 'inbox' (sidebar Inbox), Slack 'dms' (DMs tab). -> {'text','page','window','view_text'} or None if unreadable."""
    prev = frontmost()
    try:
        if not ensure_running(name):
            return None
        base = hands_read(name, pages)
        if base is None:
            return None
        if view:
            nav = {'inbox': ('Inbox', '/inbox'), 'dms': ('DMs', '')}.get(view)
            if nav and nav[1] in base['page'] and nav[1]:
                base['view_text'] = base['text']
            elif nav and hands_click(name, nav[0]):
                moved = _wait_page(name, nav[1], 6) if nav[1] else (time.sleep(2) or True)
                if not moved and name == 'ClickUp':   # the sidebar's Home panel was collapsed: open it, then Inbox
                    hands_click(name, 'Home'); time.sleep(1)
                    moved = hands_click(name, 'Inbox') and _wait_page(name, nav[1], 6)
                v = hands_read(name, view_pages) if moved else None
                base['view_text'] = v['text'] if v else ''
                if moved and name == 'ClickUp':
                    hands_click(name, 'Go back')   # return the app to the view the owner had open (only if we actually moved)
                    _wait_page(name, base['page'].rsplit('/', 1)[-1] or base['page'], 6)
                elif moved and name == 'Slack':
                    hands_click(name, 'Home')
        return base
    finally:
        refocus(prev)


def open_view(name, view=None):
    """Bring the app up (for 'open them'); ClickUp lands on its inbox via the Home link."""
    _run(['open', '-a', name], 10)
    if view == 'inbox':
        time.sleep(1.5)
        hands_click(name, 'Home')
    return True


# ---------------------------------------------------------------- ClickUp parsing
_TAIL = re.compile(rf"\s*({DATE})(?:\s+(\d+) unread notifications?)?$")


def inbox_total(text):
    m = re.search(r'(\d+) unread\b', text or '')
    return int(m.group(1)) if m else None


def parse_clickup_inbox(text):
    """Inbox rows -> [{'task','status','date','count','message','mentions','assigned'}]. Reads the aggregate line ClickUp
    exposes per notification ("Change status Current status: s <Task> <@who> <message> <date> <n> unread notifications")."""
    lines = [l.strip() for l in (text or '').split('\n')]
    heads = [i for i, l in enumerate(lines) if len(l) > 12 and _TAIL.search(l) and not l.startswith(('http', 'Primary', 'Last '))
             and (l.startswith('Change status') or len(l) > 25)]
    items = []
    for n, i in enumerate(heads):
        agg = lines[i]
        window = lines[i + 1:(heads[n + 1] if n + 1 < len(heads) else i + 40)][:40]
        tail = _TAIL.search(agg)
        rest = agg[:tail.start()]
        status = next((m.group(1) for m in (re.match(r'Current status: (.+)$', w) for w in window) if m), '')
        if rest.startswith('Change status'):
            rest = re.sub(r'^Change status(?: Current status: ' + re.escape(status) + r')?\s*', '', rest, flags=re.I) if status else rest[len('Change status'):].strip()
        cands = [w for w in window if len(w) >= 3 and (rest == w or rest.startswith(w + ' ')) and not w.startswith('@')]
        task = max(cands, key=len) if cands else rest
        if not cands and ' @' in rest:
            task = rest.split(' @', 1)[0]
        msg = rest[len(task):].strip() if rest.startswith(task) else ''
        msg = re.sub(r'(?:fb\.me)+', '', msg).strip()
        msg = re.sub(r'^TA\s*$', '', msg)
        who = re.match(r'^(\w[\w ]*?) assigned (?:this task )?to you', msg)
        items.append({'task': task, 'status': status, 'date': tail.group(1), 'count': int(tail.group(2) or 0), 'message': msg,
                      'mentions': re.findall(r'@([A-Z][\w]*(?: [A-Z][\w]*)?)', msg),
                      'assigned': bool(re.search(r'\bassign', msg, re.I)), 'who': who.group(1) if who else ''})
    return items


def parse_clickup_board(text, me=''):
    """Ads Board list text -> [{'name','group','people'}]. Groups come from "<STATUS> / Collapse group / N" headers."""
    lines = [l.strip() for l in (text or '').split('\n')]
    group, tasks, cur = '', [], None
    for i, l in enumerate(lines):
        if i + 1 < len(lines) and lines[i + 1] == 'Collapse group' and l:
            group, cur = l, None
            continue
        m = re.match(r'Change status for (.+)$', l)
        if m:
            if cur is None or cur['name'] != m.group(1):
                cur = {'name': m.group(1), 'group': group, 'people': []}
                tasks.append(cur)
            continue
        m = re.match(r'remove (.+)$', l)
        if m and cur is not None and m.group(1) not in cur['people']:
            cur['people'].append(m.group(1))
    me = (me or '').strip().lower()
    for t in tasks:
        t['mine'] = bool(me) and any(me in p.lower() for p in t['people'])
    return tasks


def clickup_snapshot(me=''):
    """Read the ClickUp app: board tasks from the open list view, plus the Inbox. -> dict or None when unreadable."""
    base = read_app('ClickUp', view='inbox', pages=1)
    if not base:
        return None
    inbox = base.get('view_text') or ''
    board_ok = '/v/l/' in base.get('page', '')
    return {'inbox': parse_clickup_inbox(inbox), 'unread': inbox_total(inbox),
            'board': parse_clickup_board(base['text'], me) if board_ok else [],
            'team': (re.search(r'clickup\.com/(\d+)/', base.get('page', '')) or [None, ''])[1]}


# ---------------------------------------------------------------- Slack / Discord parsing
def parse_discord(text):
    lines = [l.strip() for l in (text or '').split('\n')]
    dms, servers, seen = [], [], set()
    for l in lines:
        m = re.match(r'unread, (.+?) \((?:direct|group) message\)', l)
        if m and m.group(1) not in seen:
            seen.add(m.group(1)); dms.append(m.group(1))
            continue
        m = re.match(r'(\d+) mentions?, (.+)$', l) or re.match(r'Unread messages, (.+)$', l)
        if m and l not in seen:
            seen.add(l)
            nm = m.group(m.re.groups).split(',')[0].strip()   # drop ", Voice call active" style suffixes
            servers.append(f'{nm} ({m.group(1)} mention{"" if m.group(1) == "1" else "s"})' if m.re.groups == 2 else nm)
    return {'dms': dms, 'servers': servers}


def parse_slack(text, window=''):
    lines = [l.strip() for l in (text or '').split('\n')]
    unread, tabs = [], {}
    for i, l in enumerate(lines):
        m = re.match(r'^(.+?) \((?:has )?(\d+) (?:new )?(?:notifications?|unread|mentions?)\)', l) or re.match(r'^(.+?),? \((\d+) unread\)', l)
        if m and m.group(1) not in unread:
            unread.append(m.group(1))
        elif re.search(r'\bunread\b', l, re.I) and not re.match(r'^Unread mentions$|^unread', l, re.I) and len(l) < 80 and l not in unread:
            unread.append(l)
        if l in ('Home', 'DMs', 'Activity', 'Files', 'To-dos') and i + 2 < len(lines) and lines[i + 1].isdigit() and lines[i + 2] == l:
            tabs[l] = int(lines[i + 1])
    t = re.search(r'(\d+) new items?', window or '')
    return {'unread': unread, 'tabs': tabs, 'new_items': int(t.group(1)) if t else 0}


_UI_NOISE = re.compile(r'^(?:Home|DMs|Activity|Files|To-dos|Search|Messages|Show history|Help|Actions|More|Draft|Filter|Unreads|Threads|Huddles)\b', re.I)


def slack_dm_lines(text, limit=5):
    """Best-effort: the DM list rows after the DMs tab opens (name, preview). Raw lines, noise removed."""
    out = []
    for l in (text or '').split('\n'):
        l = l.strip()
        if len(l) > 6 and not _UI_NOISE.match(l) and not l.startswith('http') and l not in out:
            out.append(l)
    return out[1:limit + 1]


def chat_status(key):
    """Slack/Discord: badge + unread rows read from the app. -> dict(app, badge, unread list, dms list, running_before) or None."""
    name = CHAT_APPS[key]
    was = running(name)
    badge = badges().get(name, 0)
    base = read_app(name)
    if not base:
        return None
    if key == 'discord':
        p = parse_discord(base['text'])
        return {'app': name, 'badge': badge, 'unread': p['dms'] + p['servers'], 'dms': p['dms'], 'servers': p['servers'], 'was_running': was}
    p = parse_slack(base['text'], base['window'])
    dm_lines = []
    if p['tabs'].get('DMs'):
        v = read_app(name, view='dms')
        dm_lines = slack_dm_lines((v or {}).get('view_text', ''))
    return {'app': name, 'badge': badge or p['new_items'], 'unread': p['unread'], 'dms': dm_lines, 'tabs': p['tabs'], 'was_running': was}
