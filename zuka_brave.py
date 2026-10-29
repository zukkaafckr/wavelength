"""Zuka's fast local actions in Brave, all free (no Claude, no AI model, no network calls).

Drives the browser through AppleScript `execute <tab> javascript` (Brave: View > Developer > Allow JavaScript from Apple Events), about 0.25 s a call.
Never touches Brave's profile or settings, never closes or navigates away a tab it didn't open, never types passwords or keys.
`press ... --confirmed` (CLI only) presses any one exact-label control after Claude has asked the user and heard yes; each press is logged to press.log.
Anything that spends credits (Generate, Create, Submit, Buy, Send ...) is refused by click_text and goes only through the gate:
request_generate() speaks the cost and stores ONE pending press in ~/.config/atticus/generate-pending.json (2 minutes);
zuka_commands._handle passes the next "yes"/"no" to confirm_generate() right after zuka_msg.confirm. One yes = one press.
"""
import json
import os
import re
import shutil
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # `python3 -I` drops the script folder
import zuka_commands as zc  # noqa: E402

BROWSER = 'Brave Browser'
PENDING_FILE = os.path.expanduser('~/.config/atticus/generate-pending.json')
PENDING_WINDOW = 120
PRESS_LOG = os.path.expanduser('~/.config/atticus/press.log')   # one line per confirmed press: time, tab host, label (no page content)
RESULT_FILE = os.path.expanduser('~/.config/atticus/generate-result.json')   # what the last spoken answer did; the CLI polls it
DOWNLOADS = os.path.expanduser('~/Downloads')
_PARTIAL = ('.crdownload', '.part', '.download', '.tmp')
# labels click_text will never press: those go only through request_generate / confirm_generate
_RISKY = re.compile(r'(?i)generate|create|submit|buy|pay|confirm|send|publish|delete|remove')

_FIND_TAB = ('on run argv\nset urlkey to item 1 of argv\nset jscode to item 2 of argv\ntell application "%s"\nif urlkey is "" then\nif (count of windows) = 0 then return "__notab__"\nreturn (execute (active tab of front window) javascript jscode)\nend if\n'
             'repeat with w in windows\nrepeat with t in tabs of w\n'
             'if (URL of t) contains urlkey then return (execute t javascript jscode)\nend repeat\nend repeat\nend tell\nreturn "__notab__"\nend run' % BROWSER)
_FOCUS = ('on run argv\nset urlkey to item 1 of argv\ntell application "%s"\nrepeat with w in windows\nset i to 0\nrepeat with t in tabs of w\nset i to i + 1\n'
          'if (URL of t) contains urlkey then\nset active tab index of w to i\nset index of w to 1\nactivate\nreturn "yes"\nend if\nend repeat\nend repeat\nend tell\nreturn "no"\nend run' % BROWSER)
_TABS = ('tell application "%s"\nif (count of windows) = 0 then return ""\nset out to ""\nrepeat with w in windows\nrepeat with t in tabs of w\n'
         'set out to out & (title of t) & "\\t" & (URL of t) & "\\n"\nend repeat\nend repeat\nreturn out\nend tell' % BROWSER)


def _osa_args(script, args, timeout=15):
    """Run an AppleScript `on run argv` handler; arguments travel as argv so no quoting of the page script is needed."""
    r = zc._run(['osascript', '-e', script] + list(args), timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or 'osascript failed').strip())
    return (r.stdout or '').strip()


# ---------------------------------------------------------------- tabs
def focus_or_open(url_key, url):
    """Bring the tab whose URL contains url_key to the front; else open url in a NEW tab. Other tabs are never closed or navigated."""
    try:
        if _osa_args(_FOCUS, [url_key], 15) == 'yes':
            return True
    except Exception:
        pass
    return zc._run(['open', '-a', BROWSER, url], 10).returncode == 0


def tabs():
    """[(title, host)] of every open tab. Host names only, no paths or query strings."""
    try:
        out = zc._osa(_TABS, 10)
    except Exception:
        return []
    res = []
    for line in out.split('\n'):
        title, _, url = line.partition('\t')
        host = urlparse(url.strip()).hostname or ''
        if host:
            res.append((title.strip(), host))
    return res


def js(expr, tab_key):
    """Evaluate a JS expression in the tab whose URL contains tab_key; the JSON-able value, or None (no such tab, error, undefined)."""
    wrapped = '(function(){try{var v=(%s);return JSON.stringify(v===undefined?null:v)}catch(e){return "__err__"}})()' % expr
    try:
        out = _osa_args(_FIND_TAB, [tab_key, wrapped], 20)
    except Exception:
        return None
    if out in ('', '__notab__', '__err__', 'missing value'):
        return None
    try:
        return json.loads(out)
    except ValueError:
        return out


# ---------------------------------------------------------------- page actions
_JS_FILL = """(function(sel,text){
 var el=null;try{el=document.querySelector(sel)}catch(e){}
 if(!el){var low=sel.toLowerCase();
  el=[].slice.call(document.querySelectorAll('textarea,input,[contenteditable=true],[contenteditable=""],[role=textbox]')).find(function(x){
   return [x.getAttribute('aria-label'),x.getAttribute('placeholder'),x.getAttribute('name')].some(function(a){return a&&a.toLowerCase()===low})})}
 if(!el)return false;
 el.focus();
 if(el.isContentEditable){
  var r=document.createRange();r.selectNodeContents(el);var s=window.getSelection();s.removeAllRanges();s.addRange(r);
  if(!document.execCommand('insertText',false,text)){el.textContent=text}
  el.dispatchEvent(new Event('input',{bubbles:true}));return true}
 var proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
 Object.getOwnPropertyDescriptor(proto,'value').set.call(el,text);
 el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return el.value===text})(%s,%s)"""
_JS_CLICK = """(function(label){
 var want=label.trim().toLowerCase();
 var el=[].slice.call(document.querySelectorAll('button,a,[role=button]')).find(function(x){
  var r=x.getBoundingClientRect();
  return r.width>0&&r.height>0&&(x.innerText||x.value||'').trim().toLowerCase()===want&&!x.disabled});
 if(!el)return false;el.click();return true})(%s)"""


# counts the visible matches first and clicks only when there is exactly one: 'ok' / 'none' / 'many'
_JS_PRESS_ONE = """(function(label){
 var want=label.trim().toLowerCase();
 var hits=[].slice.call(document.querySelectorAll('button,a,[role=button]')).filter(function(x){
  var r=x.getBoundingClientRect();
  return r.width>0&&r.height>0&&(x.innerText||x.value||'').trim().toLowerCase()===want&&!x.disabled});
 if(hits.length===0)return 'none';if(hits.length>1)return 'many';
 hits[0].click();return 'ok'})(%s)"""


def fill(selector_or_label, text, tab_key=''):
    """Set a textarea / input / contenteditable the way React sites accept it (native setter + input event). True when set."""
    return js(_JS_FILL % (json.dumps(selector_or_label), json.dumps(text)), tab_key) is True


def click_text(label, tab_key=''):
    """Click the visible button/link whose text is exactly label. Refuses spending / sending / destructive labels (use the gate)."""
    if _RISKY.search(label or ''):
        return False
    return js(_JS_CLICK % json.dumps(label), tab_key) is True


def press_confirmed(label, tab_key, log_path=None):
    """Press the ONE visible button/link whose text is exactly label, risky label or not. Only the CLI calls this, and only with --confirmed
    (the caller has already asked the user and heard yes). Refuses when the label matches none or more than one control. -> 'pressed' / 'none' / 'many'."""
    host = js('location.host', tab_key)
    r = js(_JS_PRESS_ONE % json.dumps(label), tab_key)
    if r != 'ok':
        return r if r in ('none', 'many') else 'none'
    path = log_path or PRESS_LOG
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a') as f:
            f.write('%s\t%s\t%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), host if isinstance(host, str) else '', label.replace('\n', ' ').replace('\t', ' ')))
    except OSError:
        pass
    return 'pressed'


def wait_for(js_condition, tab_key='', timeout=20):
    """Poll a JS condition about every 0.3 s until truthy; True, or False on timeout."""
    end = time.time() + timeout
    while True:
        if js(js_condition, tab_key):
            return True
        if time.time() >= end:
            return False
        time.sleep(0.3)


# ---------------------------------------------------------------- downloads
def downloads_since(ts, folder=None):
    """Finished files in Downloads modified at or after ts (a time.time() value); partial downloads and hidden files are ignored."""
    folder = folder or DOWNLOADS
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(folder, n)
        if n.startswith('.') or n.lower().endswith(_PARTIAL) or not os.path.isfile(p):
            continue
        if os.path.getmtime(p) >= ts:
            out.append(p)
    return sorted(out, key=os.path.getmtime)


def file_to(paths, project_dir):
    """Move files into project_dir (created if needed). Never overwrites: a taken name becomes name-2.ext, name-3.ext. Returns the new paths."""
    os.makedirs(project_dir, exist_ok=True)
    moved = []
    for p in paths:
        base, ext = os.path.splitext(os.path.basename(p))
        dest, n = os.path.join(project_dir, base + ext), 1
        while os.path.exists(dest):
            n += 1
            dest = os.path.join(project_dir, f'{base}-{n}{ext}')
        shutil.move(p, dest)
        moved.append(dest)
    return moved


# ---------------------------------------------------------------- the Generate gate (one pending press, spoken yes, 2 minutes)
def _clear():
    try:
        os.remove(PENDING_FILE)
    except OSError:
        pass


def _pending():
    try:
        with open(PENDING_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(d, dict) and time.time() <= d.get('expires', 0) and d.get('tab_key') and d.get('button_text'):
        return d
    _clear()
    return None


def _result(pressed):
    try:
        with open(RESULT_FILE, 'w') as f:
            json.dump({'pressed': pressed, 'at': time.time()}, f)
    except OSError:
        pass


def pending():
    """True while a generate press is waiting for a spoken yes (zuka_commands uses it to decide whether a yes is for us)."""
    return _pending() is not None


def request_generate(tab_key, button_text, cost_text, say=print):
    """Say the cost and store ONE pending press (replacing any earlier one). Nothing is pressed here."""
    os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
    with open(PENDING_FILE, 'w') as f:
        json.dump({'tab_key': tab_key, 'button_text': button_text, 'expires': time.time() + PENDING_WINDOW}, f)
    line = f"{cost_text.strip().rstrip('.!?')}. Say yes to generate."
    say(line)
    return line


def _press(tab_key, button_text):
    """The one place a risky button is pressed: only called by confirm_generate after a spoken yes."""
    return js(_JS_CLICK % json.dumps(button_text), tab_key) is True


def confirm_generate(spoken):
    """The yes / no for a pending generate. A reply string, or None when nothing is pending or `spoken` doesn't answer it."""
    p = _pending()
    if not p:
        return None
    import zuka_msg   # the same yes / no words and filler stripping as a pending message send
    t0 = (spoken or '').strip().lower()
    t = zuka_msg._TAIL.sub('', zuka_msg._FILL.sub('', t0)).strip().rstrip('.!?,')
    t0 = t0.rstrip('.!?,')
    if zuka_msg._NO.match(t) or zuka_msg._NO.match(t0):
        _clear()
        _result(False)
        return "Okay, not generating."
    if zuka_msg._YES.match(t) or zuka_msg._YES.match(t0):
        _clear()   # cleared before pressing: one yes is one press, never two
        ok = _press(p['tab_key'], p['button_text'])
        _result(ok)
        return "Generating." if ok else f"I couldn't find the {p['button_text']} button{zc.call_suffix()}. Nothing was pressed."
    return None


# ---------------------------------------------------------------- command line (so Claude in chat can use the same bridge): JSON on stdout, exit 0 ok / 1 not
def _say_aloud(line):
    """Speak the cost on the Mac's own voice (local `say`, no network); Zuka's voice route hears the yes."""
    try:
        zc._run(['say', line], 30)
    except Exception:
        pass


def cli_generate(tab, button, cost, wait=PENDING_WINDOW, say=_say_aloud):
    """Gate only: speak the cost, wait for the spoken yes (zuka_commands -> confirm_generate), report. Never presses on its own."""
    try:
        os.remove(RESULT_FILE)
    except OSError:
        pass
    t0 = time.time()
    request_generate(tab, button, cost, say=say)
    end = t0 + wait
    while time.time() < end:
        try:
            with open(RESULT_FILE) as f:
                r = json.load(f)
            if r.get('at', 0) >= t0:
                return 'pressed' if r.get('pressed') else 'not confirmed'
        except (OSError, ValueError):
            pass
        if not pending():
            time.sleep(0.5)   # answered a moment ago: give the result file time to land
            if not os.path.exists(RESULT_FILE):
                return 'not confirmed'
        time.sleep(0.3)
    _clear()
    return 'not confirmed'


def _page_read(tab, limit):
    return js('({host:location.host,path:location.pathname,text:(document.body?document.body.innerText:"").slice(0,%d)})' % int(limit), tab)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='brave-bridge', description="Fast local actions in Brave (no AI, no network). JSON on stdout.")
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('tabs')
    p = sub.add_parser('read'); p.add_argument('--tab', default=''); p.add_argument('--max', type=int, default=20000)
    p = sub.add_parser('js'); p.add_argument('expr'); p.add_argument('--tab', default='')
    p = sub.add_parser('fill'); p.add_argument('--tab', required=True); p.add_argument('selector'); p.add_argument('text')
    p = sub.add_parser('click'); p.add_argument('--tab', required=True); p.add_argument('label')
    p = sub.add_parser('press'); p.add_argument('--tab', required=True); p.add_argument('label'); p.add_argument('--confirmed', action='store_true')
    p = sub.add_parser('wait'); p.add_argument('--tab', required=True); p.add_argument('cond'); p.add_argument('--timeout', type=float, default=20)
    p = sub.add_parser('open'); p.add_argument('url_key'); p.add_argument('url')
    p = sub.add_parser('downloads'); p.add_argument('--since', type=float, required=True)
    p = sub.add_parser('file'); p.add_argument('paths', nargs='+'); p.add_argument('--to', required=True)
    p = sub.add_parser('generate'); p.add_argument('--tab', required=True); p.add_argument('--button', required=True); p.add_argument('--cost', required=True)
    a = ap.parse_args(argv)
    ok, out = True, None
    if a.cmd == 'tabs':
        out = [{'title': t, 'host': h} for t, h in tabs()]
    elif a.cmd == 'read':
        out = _page_read(a.tab, a.max)
        ok = out is not None
    elif a.cmd == 'js':
        out = js(a.expr, a.tab)
    elif a.cmd == 'fill':
        out = ok = fill(a.selector, a.text, a.tab)
    elif a.cmd == 'click':
        if _RISKY.search(a.label):
            out, ok = 'refused: use the generate gate', False
        else:
            out = ok = click_text(a.label, a.tab)
    elif a.cmd == 'press':
        if not a.confirmed:
            out, ok = 'refused: ask the user first, then run again with --confirmed', False
        else:
            out = press_confirmed(a.label, a.tab)
            ok = out == 'pressed'
    elif a.cmd == 'wait':
        out = ok = wait_for(a.cond, a.tab, a.timeout)
    elif a.cmd == 'open':
        out = ok = focus_or_open(a.url_key, a.url)
    elif a.cmd == 'downloads':
        out = downloads_since(a.since)
    elif a.cmd == 'file':
        out = file_to(a.paths, a.to)
    elif a.cmd == 'generate':
        out = cli_generate(a.tab, a.button, a.cost)
        ok = out == 'pressed'
    print(json.dumps({'ok': ok, 'result': out}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
