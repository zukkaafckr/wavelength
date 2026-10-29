"""Zuka's ClickUp read through the page bridge (zuka_cdp): the Inbox and the open list, straight from ClickUp's own page.

Same output as zuka_apps.clickup_snapshot's accessibility reader, but no scraping or clicking at pixels, so it survives layout changes.
Read-only: nothing in ClickUp is changed, and the view the person had open is put back afterwards. Never restarts ClickUp: no bridge -> None.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zuka_cdp as cdp  # noqa: E402
import zuka_hiring as hiring  # noqa: E402  (same page, so same one-at-a-time lock and the same list-row reader)
from zuka_apps import DATE, inbox_total  # noqa: E402

_JS_INBOX = """(()=>{const a=[...document.querySelectorAll('a')].find(x=>/\\/inbox(\\?|$)/.test(x.getAttribute('href')||''));if(!a)return false;
 for(const n of ['mousedown','mouseup','click'])a.dispatchEvent(new MouseEvent(n,{bubbles:true,cancelable:true,button:0,view:window}));return true})()"""   # ClickUp routes on mousedown
_JS_BUNDLES = """(()=>{const t=document.querySelector('[data-test="inbox-tab__messages"]');
 return JSON.stringify({tab:t?t.innerText:'',rows:[...document.querySelectorAll('[data-test="notification-bundle"]')]
  .map(b=>b.innerText.split('\\n').map(s=>s.trim()).filter(Boolean))})})()"""
_JS_BACK = """(h=>{const a=[...document.querySelectorAll('a')].find(x=>x.getAttribute('href')===h);
 if(!a)return false;for(const n of ['mousedown','mouseup','click'])a.dispatchEvent(new MouseEvent(n,{bubbles:true,cancelable:true,button:0,view:window}));return true})(%s)"""
_TIME = re.compile(r'^\d{1,2}:\d{2}\s?[ap]m$', re.I)


def parse_bundle(lines):
    """One notification's text lines -> {'task','status','date','count','message','mentions','assigned','who'}, or None if it isn't one.
    Lines look like: [type, 'Current status: s', task, ...message..., date or time, n, 'unread notifications']."""
    lines = [l for l in lines if l]
    i = next((n for n, l in enumerate(lines) if l.startswith('Current status:')), None)
    if i is None or i + 1 >= len(lines):
        return None
    status, task, rest, count = lines[i][len('Current status:'):].strip(), lines[i + 1], lines[i + 2:], 0
    if len(rest) >= 2 and re.match(r'(?i)^unread notifications?$', rest[-1]) and rest[-2].isdigit():
        count, rest = int(rest[-2]), rest[:-2]
    if not rest or not re.fullmatch(DATE, rest[-1], re.I):
        return None
    date, msg = rest[-1], ' '.join(rest[:-1])
    if _TIME.match(date):
        date = 'Today'
    msg = re.sub(r'(?:fb\.me)+', '', msg).strip()
    msg = re.sub(r'^TA\s*$', '', msg)
    who = re.match(r'^(\w[\w ]*?) assigned (?:this task )?to you', msg)
    return {'task': task, 'status': status, 'date': date, 'count': count, 'message': msg,
            'mentions': re.findall(r'@([A-Z][\w]*(?: [A-Z][\w]*)?)', msg),
            'assigned': bool(re.search(r'\bassign', msg, re.I)), 'who': who.group(1) if who else ''}


def parse_inbox(data):
    """{'tab': 'Primary\\n56 unread', 'rows': [[lines]...]} -> (items, unread)."""
    return [i for i in (parse_bundle(r) for r in data.get('rows', [])) if i], inbox_total(data.get('tab', ''))


def parse_board(rows, me=''):
    """Open-list rows ([{'name','group','people'}], from zuka_hiring) -> board items with 'mine'."""
    me = (me or '').strip().lower()
    return [{'name': r['name'], 'group': r['group'], 'people': list(r['people']),
             'mine': bool(me) and any(me in p.lower() for p in r['people'])} for r in rows]


def _open_inbox(tab):
    """Click the sidebar Inbox link and wait for the notifications to load and settle -> parsed page dict, or None."""
    if not tab.js(_JS_INBOX):
        return None
    end, last = time.time() + 12, None
    while time.time() < end:
        time.sleep(1)
        if '/inbox' not in (tab.js('location.href') or ''):
            continue
        cur = tab.js(_JS_BUNDLES)
        data = json.loads(cur)
        if data['rows'] and cur == last:
            return data
        last = cur
    return None


def _snapshot(me):
    if not cdp.port_open('ClickUp'):   # no restart from here: the old reader is the fallback
        return None
    tab = cdp.open_tab('ClickUp')
    if not tab:
        return None
    try:
        before = tab.js('location.href') or ''
        team = (re.search(r'clickup\.com/(\d+)/', before) or [None, ''])[1]
        rows = json.loads(tab.js(hiring._JS_ROWS)) if '/v/l/' in before else []   # the open list, read before we leave it
        data = _open_inbox(tab)
        if data is None:
            return None
        tab.js('history.go(-1)')
        time.sleep(1.5)
        if (tab.js('location.href') or '') != before:   # history didn't land: open the same page again by its link
            tab.js(_JS_BACK % json.dumps(before))
            time.sleep(1.5)
        items, unread = parse_inbox(data)
        return {'inbox': items, 'unread': unread, 'board': parse_board(rows, me), 'team': team}
    except (OSError, ValueError, TypeError):
        return None
    finally:
        tab.close()


def clickup_snapshot_bridge(me=''):
    """-> {'inbox','unread','board','team'} read through the page bridge, or None on any problem (or another check is running)."""
    lock = hiring._locked()
    if not lock:
        return None
    try:
        return _snapshot(me)
    except Exception:
        return None
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass
