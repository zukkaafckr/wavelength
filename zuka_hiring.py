"""Zuka's hiring check, all free (no Claude): who submitted an assessment, who is new in Applied.

Reads the ClickUp app through its page bridge (zuka_cdp), so it opens lists by their real links instead of clicking at pixels.
Read-only: nothing in ClickUp is changed, and the view the person had open is put back afterwards.
`python3 zuka_hiring.py --check-hiring` prints a spoken line only when something is new; add `--always` to say "nothing new" too.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zuka_cdp as cdp  # noqa: E402

WORKFLOW = os.path.join(os.path.expanduser('~'), '.config/atticus/workflow.json')   # keys: hiring {applied, assessments} = the two list names
_ROLE = re.compile(r'(?i)\b(designer|editor|writer|manager|developer|producer|strategist|marketer|specialist|assistant|artist|animator)\b')
_JS_LINK = """(name=>{const rows=[...document.querySelectorAll('a.row-body[href*="/v/li/"]')];
 const a=rows.find(x=>x.innerText.trim().split('\\n')[0]===name);return a?a.getAttribute('href'):null})(%s)"""
_JS_GO = """(h=>{const a=[...document.querySelectorAll('a.row-body')].find(x=>x.getAttribute('href')===h);if(a){a.click();return true}return false})(%s)"""
_JS_ROWS = """(()=>{const out=[];let group='';
 for(const r of document.querySelectorAll('[data-row-index]')){
  if((r.className||'').includes('vgt-pinned'))continue;
  const k=r.getAttribute('data-row-kind');
  if(k==='group'){const l=r.innerText.split('\\n').map(s=>s.trim()).filter(Boolean);
    const i=l.findIndex(s=>/collapse group|expand group/i.test(s));group=(l[i+1]||l[0]||'').toUpperCase();continue}
  if(k!=='cells')continue;
  const a=r.querySelector('a[data-test="task-row-main__link"]');if(!a)continue;
  const people=[...r.querySelectorAll('[aria-label^="remove "],[title^="remove "]')].map(x=>(x.getAttribute('aria-label')||x.getAttribute('title')).replace(/^remove /,'').trim());
  out.push({name:a.innerText.trim().split('\\n')[0],id:(a.getAttribute('href')||'').split('/').pop(),group,people:[...new Set(people)],
            text:r.innerText.split('\\n').map(s=>s.trim()).filter(Boolean)})}
 return JSON.stringify(out)})()"""


def _dir():
    return os.environ.get('ATTICUS_DIR') or os.path.join(os.path.expanduser('~'), '.config/atticus')


def _seen_file():
    return os.path.join(_dir(), 'hiring-seen.json')


def _jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def lists():
    """(applied list name, assessments list name) from workflow.json `hiring`, or None when this person has no hiring setup."""
    try:
        with open(WORKFLOW) as f:
            h = json.load(f).get('hiring')
        return (h['applied'], h['assessments']) if isinstance(h, dict) and h.get('applied') and h.get('assessments') else None
    except (OSError, ValueError, KeyError):
        return None


def _read_list(tab, name):
    """Open the list named `name` from the sidebar and read its tasks -> list of dicts, or None when it can't be found."""
    href = tab.js(_JS_LINK % json.dumps(name))
    if not href:
        return None
    tab.js(_JS_GO % json.dumps(href))
    want = href.split('/v/li/')[1].split('/')[0]
    end, rows, last = time.time() + 12, None, None
    while time.time() < end:
        time.sleep(1)
        if want not in (tab.js('location.href') or ''):
            continue
        cur = tab.js(_JS_ROWS)
        if tab.js("document.querySelector('[data-row-kind=\"group\"]')!==null") and cur == last:
            rows = json.loads(cur)
            break
        last = cur
    return rows


def _role(task):
    for frag in [task['name']] + task['text']:
        m = _ROLE.search(frag)
        if m and frag not in ('Description',):
            return frag if len(frag) < 60 else m.group(0)
    return ''


def _locked():
    """One check at a time: two at once would both drive the same ClickUp page and both speak. A lock older than 3 minutes is stale."""
    path = os.path.join(_dir(), 'hiring.lock')
    try:
        os.makedirs(_dir(), exist_ok=True)
        if os.path.isdir(path) and time.time() - os.path.getmtime(path) > 180:
            os.rmdir(path)
        os.mkdir(path)
        return path
    except OSError:
        return None


def snapshot():
    """-> {'applied': [...], 'assessments': [...]} or None when ClickUp can't be read (or another check is running). Puts the person's view back."""
    names = lists()
    lock = _locked() if names else None
    if not lock:
        return None
    try:
        return _snapshot(names)
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass


def _snapshot(names):
    if not cdp.ensure_app('ClickUp'):
        return None
    tab = cdp.open_tab('ClickUp')
    if not tab:
        return None
    try:
        before = tab.js('location.href')
        applied = _read_list(tab, names[0])
        assess = _read_list(tab, names[1])
        if applied is None and assess is None:
            return None
        moves = (applied is not None) + (assess is not None)
        tab.js('history.go(-%d)' % moves)
        time.sleep(1.5)
        if (tab.js('location.href') or '') != before:   # history didn't land: open the same list again by its link
            tail = before.split('app.clickup.com')[-1]
            tab.js("(p=>{const a=[...document.querySelectorAll('a')].find(x=>(x.getAttribute('href')||'').endsWith(p));if(a)a.click()})(%s)" % json.dumps(tail))
        done = lambda rows, groups: [dict(t, role=_role(t)) for t in (rows or []) if not groups or t['group'] in groups]  # noqa: E731
        return {'applied': done(applied, ('APPLIED',)),
                'assessments': [t for t in done(assess, None) if not re.search(r'(?i)closed|done|complete', t['group'])]}
    except OSError:
        return None
    finally:
        tab.close()


def _first(name):
    return name.split()[0] if name else name


def _line(t, what):
    who = ' and '.join(_first(p) for p in t['people'])
    return f"{what} {t['name']}" + (f", {t['role']}" if t['role'] else '') + (f", assigned to {who}" if who else ', not assigned to anyone yet')


def speak(snap, new_only=True, always=False):
    """Spoken summary. new_only skips what was already announced; '' when nothing (unless always)."""
    seen = set(_jload(_seen_file(), []))
    sa = [t for t in snap['assessments'] if not new_only or 'a:' + t['id'] not in seen]
    ap = [t for t in snap['applied'] if not new_only or 'p:' + t['id'] not in seen]
    keys = seen | {'a:' + t['id'] for t in snap['assessments']} | {'p:' + t['id'] for t in snap['applied']}
    try:
        os.makedirs(_dir(), exist_ok=True)
        with open(_seen_file(), 'w') as f:
            json.dump(sorted(keys), f)
    except OSError:
        pass
    parts = []
    if sa:
        parts.append('Assessment submitted: ' + '; '.join(_line(t, '') .strip(' ,') for t in sa) + '.')
    if ap:
        parts.append(f"New in Applied: " + '; '.join(_line(t, '').strip(' ,') for t in ap) + '.')
    if not parts and always:
        parts.append(f"No {'new ' if new_only else ''}assessment submissions, and nobody {'new ' if new_only else ''}in Applied.")
    return ' '.join(parts)


def handle_now():
    if not lists():
        return None
    snap = snapshot()
    if not snap:
        return "I couldn't read ClickUp just now. Is it signed in?"
    return speak(snap, new_only=False, always=True)


if __name__ == '__main__':
    if '--check-hiring' in sys.argv:
        s = snapshot()
        if s:
            out = speak(s, new_only=True, always='--always' in sys.argv)
            if out:
                print(out)
