"""Zuka's screen-aware helper, free and local: "what's on my screen", "explain this", "summarise this page", "what does this error mean",
"read this to me", "help me with this". It reads the front window's TEXT on this Mac (the active tab for Brave / Safari / Chrome, the accessibility
tree for every other app) and answers with the local brain (zuka_chat, Ollama) in 1 to 3 plain sentences. Nothing leaves the Mac, nothing is
logged and the window text is never written to disk (it lives only in local variables; "read more" keeps the unread rest in memory for 5 minutes).

Privacy: password managers, Keychain, the Passwords settings pane and banking / payment pages are never read (DENY_APPS, DENY_TITLE, DENY_HOST:
add to them freely). Before any text reaches the model, long tokens, card-like numbers and anything near "password" are masked.
If the local brain is down, the window has no readable text (an image or video) or the ask needs real reasoning (write / fix / reply), Zuka says so
and offers Claude; she never calls Claude herself. Saying "ask Claude about this screen" is the spoken permission that hands the request on.
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CAP = 6000                 # characters of window text kept
HEAD = 4400                # of those, the part nearest the top; the rest is the error / failed / exception lines found further down
MORE_WINDOW = 300          # seconds "read more" stays available
BROWSERS = {'Brave Browser': 'brave', 'Safari': 'safari', 'Google Chrome': 'chrome'}

# ---- privacy denylists (lowercase; easy to extend) ----
DENY_APPS = ('1password', 'bitwarden', 'lastpass', 'dashlane', 'keychain access', 'keepassxc', 'keepass', 'enpass', 'nordpass', 'proton pass',
             'keeper', 'roboform', 'passwords', 'secrets', 'strongbox')
DENY_TITLE = re.compile(r"\b(passwords?|passcodes?|keychain|net ?banking|internet banking|online banking|mobile banking|bank account|checkout|payment|"
                        r"credit card|debit card|card number|billing|pay now|wire transfer|sign ?in to your|log ?in to your|one[- ]time (?:code|password)|"
                        r"2fa|two[- ]factor|recovery (?:key|phrase)|seed phrase|wallet)\b", re.I)
DENY_HOST = re.compile(r"(?:^|\.)(?:paypal|stripe|venmo|cash\.app|wise|revolut|coinbase|binance|kraken|razorpay|paytm|phonepe|gpay|pay\.google|"
                       r"chase|wellsfargo|bankofamerica|citi|capitalone|americanexpress|usbank|schwab|fidelity|hdfcbank|icicibank|sbi|onlinesbi|axisbank|"
                       r"kotak|barclays|hsbc|monzo|lloyds|natwest|santander|ally|discover|1password|bitwarden|lastpass|dashlane|"
                       r"accounts\.google)\.|bank\.|banking\.|netbanking|\.bank$", re.I)
PRIVATE = "That looks private, so I am not reading it."
NO_TEXT = "I can't read any text in that window, it looks like an image or a video."
NO_BRAIN = "My local brain isn't up right now, so I can't say."
OFFER = " Want Claude to take a look? Say ask Claude about this screen."

# ---- routing ----
_PRE = r"^(?:(?:hey|ok|okay|please|can you|could you|would you|will you|zuka|just|i want you to|i need you to)\s+)*"
_ASK_CLAUDE = re.compile(r"^(?:(?:hey|ok|okay|please|zuka)\s+)*ask claude (?:about|to look at|to explain|for help with|what is on|whats on) (?:this|my|the) ?(?:screen|page|window|tab|app|error)?$")
_READ = re.compile(_PRE + r"(?:read|say) (?:this|that|it|the page|this page|the screen|this screen|this article|the article|this window)(?: (?:out|loud|aloud|to me|please))*$")
_MORE = re.compile(_PRE + r"(?:read more|keep reading|continue reading|go on reading|read the rest|carry on reading)(?: please)?$")
_SCREEN = re.compile(_PRE + r"(?:"
                     r"what(?:s| is) (?:on|in) (?:my |the )?(?:screen|window|display|page|tab)|"
                     r"what(?:s| is) (?:on )?(?:this|that) (?:page|screen|window|tab|app|site|website|document)(?: about)?|"
                     r"what (?:am i|are we) (?:looking at|seeing)|what do i (?:have )?(?:see|on) (?:here|on (?:my )?screen)|"
                     r"what(?:s| is) (?:this|that)(?: here)?|what(?:s| is) in front of me|"
                     r"(?:explain|describe|tell me about|summari[sz]e|sum up|give me (?:a |the )?(?:summary|gist) of) (?:this|that|it|my screen|the screen|this screen|this page|the page|this window|this tab|this document|this site|this website|what(?:s| is) on (?:my |the )?screen)(?: to me| for me| briefly| quickly)?|"
                     r"(?:what|whats) does (?:this|that) (?:error|message|warning|alert|popup|dialog|page|say|mean)(?: message)?(?: mean| say)?|"
                     r"what(?:s| is) (?:this|that|the) (?:error|warning|message|alert|popup|dialog)(?: on (?:my )?screen)?(?: mean)?|"
                     r"(?:help me with|help with|help me out with|look at) (?:this|that|my screen|the screen|this screen|this page|this window)|"
                     r"(?:what|whats) (?:is )?(?:going on|happening|wrong) (?:here|on (?:my )?screen|on this page)|"
                     r"what (?:does|did) (?:this|that|the) (?:page|screen|window|document|error) (?:say|mean)"
                     r")(?: please| for me)?$")
_DEEP = re.compile(r"\b(write|draft|rewrite|reply|respond|fix|debug|code|translate|compare|plan|solve|fill|complete|continue)\b")


def route(t):
    """-> ('read'|'more'|'ask'|'claude', None) or None. t is already normalised lowercase words."""
    t = (t or '').strip()
    if not t or len(t) > 120:
        return None
    if _ASK_CLAUDE.match(t): return 'claude'
    if _MORE.match(t): return 'more'
    if _READ.match(t): return 'read'
    if _SCREEN.match(t): return 'ask'
    return None


# ---- privacy ----
def denied(app, title='', host=''):
    """True when this window must never be read."""
    a, ti, h = (app or '').lower(), (title or '').lower(), (host or '').lower()
    if any(d == a or d in a for d in DENY_APPS): return True
    if a in ('system settings', 'system preferences') and re.search(r'password|keychain|touch id|login', ti): return True
    if DENY_TITLE.search(ti): return True
    if h and DENY_HOST.search(h): return True
    return False


_TOKEN = re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|xox[a-z]?|AIza|hf|AKIA|eyJ)[-_A-Za-z0-9.]{8,}|\b(?=[A-Za-z0-9_\-+/=]*\d)(?=[A-Za-z0-9_\-+/=]*[A-Za-z])[A-Za-z0-9_\-+/=]{24,}\b|\b[0-9a-fA-F]{32,}\b")
_CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_NEAR = re.compile(r"(?i)\b(password|passcode|passwd|pwd|secret|api[ _-]?key|access[ _-]?key|token|otp|verification code|cvv|cvc|security code|pin)\b")
_MASK = '[hidden]'


def mask(text):
    """Hide long tokens, card-like numbers and anything near 'password' (that line, the one before and the one after)."""
    lines = (text or '').split('\n')
    hide = set()
    for i, ln in enumerate(lines):
        if _NEAR.search(ln):
            hide.update((i - 1, i, i + 1))
    out = []
    for i, ln in enumerate(lines):
        if i in hide:
            out.append(_MASK)
            continue
        ln = _CARD.sub(lambda m: _MASK if len(re.sub(r'\D', '', m.group())) >= 13 else m.group(), ln)
        out.append(_TOKEN.sub(_MASK, ln))
    return '\n'.join(out)


_ERR = re.compile(r"(?i)\b(error|errors|failed|failure|exception|traceback|fatal|denied|cannot|can't|couldn't|unable to)\b")


def cap(text, limit=CAP, head=HEAD):
    """At most `limit` characters: the top of the text, plus any later line that says error / failed / exception."""
    text = re.sub(r'[ \t]+', ' ', text or '')
    text = re.sub(r'\n\s*\n+', '\n', text).strip()
    if len(text) <= limit:
        return text
    top = text[:head]
    top = top[:top.rfind('\n')] if '\n' in top[head // 2:] else top
    rest = [ln.strip() for ln in text[len(top):].split('\n') if _ERR.search(ln)]
    extra, room = [], limit - len(top) - 1
    for ln in rest:
        ln = ln[:300]
        if len(ln) + 1 > room: break
        extra.append(ln)
        room -= len(ln) + 1
    return top + ('\n' + '\n'.join(extra) if extra else '')


# ---- reading the window ----
def _run(args, timeout=5):
    import zuka_commands as zc
    return zc._run(args, timeout)


def front():
    """(app name, window title) of the window in front; ('', '') when unknown. The app comes from lsappinfo (0.2 s; System Events needs about 1 s).
    The title of a browser tab is read just before its text (read_browser); for other apps it comes back with the text (read_app)."""
    try:
        r = _run(['/bin/sh', '-c', 'lsappinfo info -only name "$(lsappinfo front)"'], 4)
        line = (r.stdout or '').strip().splitlines()[0] if r.returncode == 0 and (r.stdout or '').strip() else ''
        m = re.search(r'"LSDisplayName"="([^"]+)"|^"([^"]+)"', line)
        return ((m.group(1) or m.group(2)) if m else ''), ''
    except Exception:
        return '', ''


_PEEK = 'JSON.stringify({host:location.host,title:document.title})'
_TEXT = 'JSON.stringify({text:(document.body?document.body.innerText:"").slice(0,20000)})'
_BROWSER_AS = {
    'safari': 'tell application "Safari"\nif (count of windows) = 0 then return ""\nreturn (do JavaScript "%s" in current tab of front window)\nend tell',
    'chrome': 'tell application "Google Chrome"\nif (count of windows) = 0 then return ""\nreturn (execute (active tab of front window) javascript "%s")\nend tell',
}
# Hard time limits per read path (seconds). A path that cannot answer in time is dropped and the next one tries: bridge -> head -> full.
T_PEEK = 3          # host + title of a tab (a browser with page JS off answers with an error at once; this only caps a hang)
T_TEXT = 4          # page text from a browser tab or an Electron page
T_HEAD = 3          # accessibility first screenful (about 0.3 s when healthy)
T_FULL = 8          # accessibility full read (5 to 12 s on a heavy window)
SHORT = 400         # a first screenful shorter than this triggers the full read
CDP_APPS = ('ClickUp',)   # Electron apps read through zuka_cdp when their page bridge is already on (never restarted to enable it)


def _tab_js(app, expr, timeout=T_PEEK):
    """The JSON object `expr` evaluates to in the active tab, or {} (no window, page JS off, error or timeout: all quick)."""
    kind = BROWSERS.get(app)
    try:
        if kind == 'brave':
            import zuka_brave   # same osascript bridge as brave-bridge read, with a short limit instead of zuka_brave.js's 20 s
            wrapped = '(function(){try{return (%s)}catch(e){return ""}})()' % expr
            v = zuka_brave._osa_args(zuka_brave._FIND_TAB, ['', wrapped], timeout)
            return json.loads(v) if v not in ('', '__notab__', '__err__', 'missing value') else {}
        r = _run(['osascript', '-e', _BROWSER_AS[kind] % expr.replace('"', '\\"')], timeout)
        return json.loads((r.stdout or '').strip() or '{}') if r.returncode == 0 else {}
    except Exception:
        return {}


def peek_browser(app):
    """(host, title) of the active tab, read before any page text so a banking page is never read. ('', '') when there is no readable tab."""
    d = _tab_js(app, _PEEK, T_PEEK)
    return d.get('host', '') or '', d.get('title', '') or ''


def read_browser(app):
    """Text of the active tab."""
    return _tab_js(app, _TEXT, T_TEXT).get('text', '') or ''


def _cdp_js(app, expr, timeout):
    """Evaluate expr in the Electron app's page through zuka_cdp; None when the bridge is off or anything fails. Never starts or restarts the app."""
    t = None
    try:
        import zuka_cdp
        if app not in zuka_cdp.PORTS or not zuka_cdp.port_open(app):
            return None
        t = zuka_cdp.open_tab(app)
        if not t: return None
        t.s.settimeout(timeout)
        return t.js(expr)
    except Exception:
        return None
    finally:
        try:
            t and t.close()
        except Exception:
            pass


def peek_cdp(app):
    """(host, title) of the Electron app's page, or None when the page bridge is not on."""
    v = _cdp_js(app, _PEEK, T_PEEK)
    try:
        d = json.loads(v) if isinstance(v, str) else None
    except ValueError:
        d = None
    return (d.get('host', '') or '', d.get('title', '') or '') if isinstance(d, dict) else None


def read_cdp(app):
    v = _cdp_js(app, _TEXT, T_TEXT)
    try:
        return (json.loads(v) if isinstance(v, str) else {}).get('text', '') or ''
    except ValueError:
        return ''


def read_app(app, head=False, timeout=None):
    """(text, window title) from the app's accessibility tree. head=True is the first screenful only (fast)."""
    timeout = timeout or (T_HEAD if head else T_FULL)
    try:
        import zuka_apps
        r = zuka_apps.hands(['read', app], timeout=timeout, head=head)
        d = json.loads(r.stdout) or {}
        return d.get('text', '') or '', d.get('window', '') or ''
    except Exception:
        return '', ''


def look(deep=False):
    """-> dict(app, title, host, text, private, path). The text is masked and capped, and is empty when private. Never stored.
    Read order, each path with its own hard limit: page bridge (browser tab / Electron page) -> accessibility first screenful ->
    accessibility full read (only when the first screenful is short or deep=True, for 'read this'). Host and title are read first so
    a private page is never fetched. path says which one answered (a label, never window content)."""
    app, _ = front()
    blank = {'app': app, 'title': '', 'host': '', 'text': '', 'private': False, 'path': ''}
    if not app:
        return blank
    if denied(app):
        return dict(blank, private=True)
    text, title, host, path = '', '', '', ''
    if app in BROWSERS:
        host, title = peek_browser(app)
        if denied(app, title, host):
            return dict(blank, title=title, host=host, private=True)
        if host or title:
            text = read_browser(app)
            path = 'bridge' if text.strip() else ''
    elif app in CDP_APPS:
        pk = peek_cdp(app)
        if pk is not None:
            host, title = pk
            if denied(app, title, host):
                return dict(blank, title=title, host=host, private=True)
            text = read_cdp(app)
            path = 'cdp' if text.strip() else ''
    if not text.strip():
        text, t2 = read_app(app, head=True)
        title, path = title or t2, 'head'
        if denied(app, title):   # the window title only arrives with the text; a private window's text is dropped here, unused
            return dict(blank, title=title, private=True)
        if deep or len(text.strip()) < SHORT:
            full, t3 = read_app(app)
            if len(full.strip()) > len(text.strip()):
                text, title, path = full, title or t3, 'full'
            if denied(app, title):
                return dict(blank, title=title, private=True)
    return {'app': app, 'title': title, 'host': host, 'text': cap(mask(text)), 'private': False, 'path': path if text.strip() else ''}


# ---- the local brain ----
_SYS = ("You help a person understand what is on their Mac screen. You get the app, the window title and the text read from the window. "
        "Answer the question directly in 1 to 3 short plain sentences, as you would say it out loud: no lists, no markdown, no emojis. "
        "Say what the page or window is and what matters on it; for an error, say what it means and the most likely fix. "
        "Use only what the text says, never invent details. If the text is not enough to answer, reply exactly NEED_CLAUDE.")


def _tidy(raw):
    import zuka_chat
    r = re.sub(r'[*_`#]+', '', raw or '').strip().strip('"')
    r = re.sub(r'\s*\n+\s*', ' ', r)
    parts = re.findall(r'.+?[.!?]+["\')”]*(?=\s+["\'(“]?[A-Z0-9]|\s*$)|.+$', r)
    parts = [p.strip() for p in parts if p.strip() and not re.search(r'\b(Claude|Anthropic|OpenAI|Alibaba|Qwen|ChatGPT|Gemini)\b', p)]
    out = ' '.join(parts[:3]).strip()
    if len(out) > 420: out = ' '.join(parts[:2]).strip()
    if len(out) > 420: out = parts[0].strip() if parts else ''
    return '' if zuka_chat._FAKE.search(out) else out


def _for_model(text, limit=2600):
    """The small model gets less than the 6000 kept: the top and the error lines (cap again), so the answer starts in seconds."""
    return cap(text, limit, int(limit * .75))


KEEP_ALIVE = '30m'     # the answer call keeps the model loaded this long after each use
_warm = {'at': 0.0}


def warm():
    """Load the local model now (empty prompt, no generation) and keep it for KEEP_ALIVE. Quiet no-op when the brain is off. Never raises."""
    try:
        import zuka_chat
        if not zuka_chat.enabled(): return False
        if not zuka_chat._up() and not zuka_chat.ensure_server(): return False
        body = {'model': zuka_chat.MODEL, 'prompt': '', 'stream': False, 'keep_alive': KEEP_ALIVE}
        req = urllib.request.Request(zuka_chat._url() + '/api/generate', json.dumps(body).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        zuka_chat._touch()
        return True
    except Exception:
        return False


def _warm_async(every=240):
    """Background warm ping, at most once per `every` seconds; skipped under tests."""
    if 'unittest' in sys.modules or 'pytest' in sys.modules or os.environ.get('ZUKA_SCREEN_NO_WARM'):
        return
    now = time.time()
    if now - _warm['at'] < every: return
    _warm['at'] = now
    import threading
    threading.Thread(target=warm, daemon=True).start()


_warm_async()   # first import (the first screen phrase, or app start if something imports this) starts loading the model


def ask_brain(app, title, text, question):
    """1 to 3 spoken sentences from the local model, or None when it cannot run or says it needs more."""
    try:
        import zuka_chat
        if not text or not zuka_chat.enabled(): return None
        if not zuka_chat._up() and not zuka_chat.ensure_server(): return None
        user = f"Question: {question}\nApp: {app}\nWindow title: {title}\n\nTEXT FROM THE WINDOW:\n{_for_model(text)}"
        body = {'model': zuka_chat.MODEL, 'stream': False, 'keep_alive': KEEP_ALIVE,
                'options': {'num_predict': 100, 'temperature': .2, 'num_ctx': 3072},
                'messages': [{'role': 'system', 'content': _SYS}, {'role': 'user', 'content': user}]}
        req = urllib.request.Request(zuka_chat._url() + '/api/chat', json.dumps(body).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=zuka_chat.TIMEOUT + 6) as r:
            out = json.load(r)
        zuka_chat._touch()
    except Exception:
        return None
    raw = ((out.get('message') or {}).get('content')) if isinstance(out, dict) else ''
    if not isinstance(raw, str) or 'NEEDCLAUDE' in re.sub(r'[\s_\-]', '', raw).upper(): return None
    return _tidy(raw) or None


# ---- read it aloud ----
def main_text(text):
    """The readable body: menu / nav / button lines (short, no sentence punctuation), links and repeats removed."""
    seen, out = set(), []
    for ln in (text or '').split('\n'):
        ln = re.sub(r'https?://\S+|www\.\S+', '', ln).strip()
        if not ln or ln == _MASK: continue
        words = ln.split()
        if len(words) < 5 and not re.search(r'[.!?]$', ln): continue
        if len(words) < 3: continue
        if ln in seen: continue
        seen.add(ln)
        out.append(ln)
    return ' '.join(out)


def chunks(body, size=320):
    sents = re.findall(r'.+?[.!?](?=\s|$)|.+$', body)
    out, cur = [], ''
    for s in (x.strip() for x in sents if x.strip()):
        if cur and len(cur) + len(s) + 1 > size:
            out.append(cur)
            cur = s
        else:
            cur = (cur + ' ' + s).strip()
    if cur: out.append(cur)
    return out


_rest = {'chunks': [], 'at': 0.0}   # unread chunks, memory only


def _speak_chunks(cs, per=3):
    now, rest = cs[:per], cs[per:]
    _rest['chunks'], _rest['at'] = rest, time.time()
    return ' '.join(now) + (' Say read more to keep going.' if rest else '')


def read_more():
    if time.time() - _rest['at'] > MORE_WINDOW or not _rest['chunks']:
        _rest['chunks'] = []
        return "There is nothing more waiting to be read."
    return _speak_chunks(_rest['chunks'])


# ---- entry ----
def answer(question, d=None):
    d = d or look()
    if not d['app']:
        return "I can't tell which window is in front."
    if d['private']:
        return PRIVATE
    if not d['text'].strip():
        return NO_TEXT + OFFER
    if _DEEP.search(question):
        return "That needs more than my local brain." + OFFER
    out = ask_brain(d['app'], d['title'], d['text'], question)
    if out: return out
    import zuka_chat
    return (NO_BRAIN if not zuka_chat.enabled() or not zuka_chat._up() else "I can't tell from the text alone.") + OFFER


def handle(t, raw=''):
    """Spoken reply for a screen phrase, else None. 'ask claude about this screen' returns None on purpose: that is the permission, the
    request then goes to Claude as spoken."""
    r = route(t)
    if r in (None, 'claude'):
        return None
    if r == 'more':
        return read_more()
    _warm_async()   # load the model while the window is read, so the first answer is never cold
    d = look(deep=(r == 'read'))
    if r == 'read':
        if not d['app']: return "I can't tell which window is in front."
        if d['private']: return PRIVATE
        body = main_text(d['text'])
        if not body: return NO_TEXT
        return _speak_chunks(chunks(body))
    return answer(t, d)
