"""Zuka's messages, free (no Claude, no APIs): read WhatsApp (web.whatsapp.com in the workflow browser), Slack and Discord (the installed
apps, read through the accessibility helpers) and send a message, but only after a spoken yes.

zuka_commands._handle calls confirm(t) FIRST (so "yes"/"send it"/"no" reach a pending send before any other yes/no handler) and
handle(t, raw) before zuka_work.handle_chat. A reply, or None. Sending: find the chat, type the draft WITHOUT sending, ask
"Send 'x' to Athar on WhatsApp?", store SEND_FILE (expires in 2 minutes). Nothing is ever sent without that yes."""
import json
import os
import re
import time

import zuka_commands as zc

SEND_FILE = os.path.expanduser('~/.config/atticus/send-pending.json')
SEND_WINDOW = 120
APPS = {'whatsapp': 'WhatsApp', 'slack': 'Slack', 'discord': 'Discord'}
_APP_RX = r"(?:whatsapp|whats app|whatsap|watsapp|slack|discord)"
_FILL = re.compile(r"(?i)^(?:(?:hey|ok|okay|um+|uh+|zuka|please|kindly|just|so|and|then|also|go ahead and|yaar|bro|(?:can|could|would|will) (?:you|u)(?: please)?|i (?:want|need|would like|wanna) you to|i want to|i wanna|lets|you can|you could|i'd like you to|i would like you to|i'd like to|i would like to)[ ,]+)+")
_TAIL = re.compile(r"(?i)(?:[ ,]+(?:please|for me|right now|real quick|quickly|thanks|thank you|if you can|once|na|yaar|now|again|only|bro|ok|okay))+[ .!?]*$")
_YES = re.compile(r"^(?:yes|yeah|yep|yup|ya|yah|sure|ok|okay|haan|han|ha|send it|send|send now|go ahead|do it|please do|yes please|yes send it|yes send|yes go ahead|confirm|confirmed|correct|right|bhej do|bhej de|kar do|sure send it|yes do it|do|sure do)$")
_NO = re.compile(r"^(?:no|nope|nah|na|nahi|cancel|cancel it|dont|dont send|do not|do not send|stop|never mind|nevermind|not now|discard|delete it|mat bhejo|rehne do|leave it)$")
_NOT_NAMES = {'me', 'us', 'you', 'the', 'a', 'an', 'it', 'this', 'that', 'what', 'how', 'why', 'when', 'where', 'who', 'time', 'about', 'my', 'myself', 'everyone', 'all', 'to', 'yourself', 'zuka'}


_TAIL_SEND = re.compile(r"(?i)(?:[ ,]+(?:please|for me|if you can|thanks|thank you))+[ .!?]*$")   # a message may itself end in once / now / ok


def _strip(raw, tail=_TAIL):
    s = re.sub(r"\s+", ' ', (raw or '').strip())
    for _ in range(3):
        s = tail.sub('', _FILL.sub('', s)).strip()
    return s


def _appkey(s):
    s = (s or '').lower().replace(' ', '')
    return 'whatsapp' if s.startswith(('whats', 'wha', 'wat')) else s or None


# ---------------------------------------------------------------- pending send (2 minutes)
def _load():
    try:
        with open(SEND_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(d, dict) and time.time() - d.get('at', 0) <= SEND_WINDOW:
        return d
    _drop()
    return None


def _save(d):
    try:
        os.makedirs(os.path.dirname(SEND_FILE), exist_ok=True)
        with open(SEND_FILE, 'w') as f:
            json.dump(dict(d, at=time.time()), f)
    except OSError:
        pass


def _drop():
    try:
        os.remove(SEND_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------- parsing
_MARK = (r"(?:(?:and |then |also )?(?:tell (?:him|her|them)(?: that| to)?|let (?:him|her|them) know(?: that)?|ask (?:him|her|them)(?: to| if| that)?)"
         r"|(?:and |then )?(?:saying|says|say|sayin)(?: that| to him| to her)?|that says|with the (?:message|text)|that|:)")


def _first_person(m):
    m = re.sub(r"(?i)^(?:that |to say |to tell (?:him|her|them) )", '', m.strip().strip('"\'“”')).strip(' ,:')
    m = re.sub(r"\bi\b", 'I', re.sub(r"\bi (m|ll|ve|d)\b", r"I'\1", m))   # speech arrives lowercase: "i m late" -> "I'm late"
    return (m[:1].upper() + m[1:]) if m else ''


def _split_name(rest):
    """'athar and tell him that i am working' / 'athar khan saying hi' / 'athar i am late' -> (name, message)."""
    rest = rest.strip()
    pre = r"(?:my )?" if rest.lower().startswith('my ') else ''
    for n in (1, 2, 3):
        m = re.match(r"(?i)^(" + pre + r"[^\s,:]+(?: [^\s,:]+){%d})\s*[,:]?\s+" % (n - 1) + _MARK + r"\s*(.*)$", rest)
        if m:
            return m.group(1), _first_person(m.group(2))
    m = re.match(r"(?i)^(" + pre + r"[^\s,:]+(?: [^\s,:]+){0,2})\s*:\s*(.+)$", rest)
    if m:
        return m.group(1), _first_person(m.group(2))
    m = re.match(r"(?i)^(" + pre + r"[^\s,:]+)\s+(.+)$", rest)
    return (m.group(1), _first_person(m.group(2))) if m else (None, None)


def parse_send(raw):
    """-> (app, name, message) for "message athar and tell him that i am working", "send sam a message saying hi", "tell chris on slack that ...",
    "reply to alex on my way"; None when it isn't a send request."""
    s = _strip(raw, _TAIL_SEND)
    if not s:
        return None
    app = None
    m = re.search(r"(?i)\s+(?:on|in|over|via|through|using)\s+(?:my\s+)?(" + _APP_RX + r")\b(?: web)?", s)
    if m:
        app, s = _appkey(m.group(1)), (s[:m.start()] + s[m.end():]).strip()
    name = msg = None
    m = re.match(r"(?i)^send (?:(?:a|the|him|her|them) )?(?:(?:quick|short) )?(?:message|text|msg|whatsapp|dm|note)(?: to)? (.+)$", s) or None
    if m:   # "send a message to athar saying hi"
        name, msg = _split_name(m.group(1))
    if not name:
        m = re.match(r"(?i)^send (?P<n>[^\s,:]+(?: (?!(?:a|an|the|quick|short)\b)[^\s,:]+)?) (?:a |the )?(?:quick |short )?(?:message|text|msg|whatsapp|dm|note)\s*(?:saying|that says|that|to say|which says|:|,)?\s*(?P<m>.+)$", s)
        if m:
            name, msg = m.group('n'), _first_person(m.group('m'))
    if not name:
        m = re.match(r"(?i)^(?:(?:send|drop|shoot) (?:a |the )?(?:message|text|whatsapp|dm)(?: to)? |(?:message|text|msg|dm|ping|whatsapp|whats app|slack|discord|whatsap|watsapp)(?! me\b| size\b| app\b)\s+)(.+)$", s)
        if m:
            if re.match(r"(?i)^(?:message|text|msg|dm|ping|whatsapp|whats app|slack|discord|whatsap|watsapp)\b", s) and _appkey(re.match(r"\S+(?: app)?", s).group(0)) in APPS and not app:
                app = _appkey(re.match(r"(?i)\S+(?: app)?", s).group(0))
            name, msg = _split_name(m.group(1))
    if not name:
        m = re.match(r"(?i)^(?:tell|inform|notify|let) ([^\s,:]+(?: [^\s,:]+)?)\s+(?:know )?(?:that|to|about) (.+)$", s) or re.match(r"(?i)^(?:tell|inform|notify|let) ([^\s,:]+)\s+(?:know )?(?:that |to |about )?(.+)$", s)
        if m:
            name, msg = m.group(1), _first_person(m.group(2))
    if not name:
        m = re.match(r"(?i)^(?:reply|respond|answer|write back|text back|message back)(?: back)?(?: to)? (.+)$", s)
        if m:
            name, msg = _split_name(m.group(1))
            if not name:
                return None
    if not name or not msg:
        return None
    name = re.sub(r"(?i)^(?:to|my)\s+(?=\S)", lambda x: '' if x.group(0).lower().startswith('to') else 'my ', name).strip()
    if name.lower().split()[0] in _NOT_NAMES - {'my'} or name.lower() in _NOT_NAMES or re.fullmatch(r"(?i)" + _APP_RX, name) or len(msg) < 2:
        return None
    name = name.strip(" ,.")
    return app or 'whatsapp', name.title() if name == name.lower() else name, msg


# ---------------------------------------------------------------- WhatsApp web (the workflow browser; JS in the tab, read-only until yes)
_WA_URL = 'https://web.whatsapp.com/'
_JS_SEARCH = ("(function(n){var s=document.querySelector('#side [contenteditable=true][role=textbox]')||document.querySelector('#side [contenteditable=true]')||document.querySelector('[data-tab=\"3\"]');"
              "if(!s)return 'NOSEARCH';s.focus();document.execCommand('selectAll');document.execCommand('delete');if(n)document.execCommand('insertText',false,n);return 'OK'})(%s)")
_JS_ROWS = ("(function(){var ps=document.querySelector('#pane-side');var rows=ps?[].slice.call(ps.querySelectorAll('[role=listitem],[role=row]')):[];var seen={},out=[];"
            "rows.forEach(function(r){var sp=r.querySelector('span[title]');var n=sp?sp.getAttribute('title'):'';if(n&&!seen[n]){seen[n]=1;out.push(n)}});return JSON.stringify(out)})()")
_JS_OPEN = ("(function(n){var ps=document.querySelector('#pane-side');var rows=ps?[].slice.call(ps.querySelectorAll('[role=listitem],[role=row]')):[];"
            "for(var i=0;i<rows.length;i++){var sp=rows[i].querySelector('span[title]');if(sp&&sp.getAttribute('title')===n){['mousedown','mouseup','click'].forEach(function(t){rows[i].dispatchEvent(new MouseEvent(t,{bubbles:true}))});return 'OK'}}return 'NOROW'})(%s)")
_JS_TYPE = ("(function(m){var c=document.querySelector('#main footer [contenteditable=true]')||document.querySelector('footer [contenteditable=true]')||document.querySelector('[data-tab=\"10\"]');"
            "if(!c)return JSON.stringify({err:'NOCOMPOSER'});c.focus();document.execCommand('selectAll');document.execCommand('delete');if(m)document.execCommand('insertText',false,m);"
            "var h=document.querySelector('#main header span[title]');return JSON.stringify({chat:h?h.getAttribute('title'):'',text:(c.innerText||'').trim()})})(%s)")
_JS_SEND = ("(function(){var b=document.querySelector('#main footer button[aria-label=Send]')||document.querySelector('footer button[aria-label=Send]');"
            "if(!b){var i=document.querySelector('footer [data-icon=send]');b=i&&i.closest('button')}if(!b)return 'NOSEND';b.click();return 'OK'})()")


class _Fail(Exception):
    pass


def _wa(js, tab_front=False):
    """Run js in the WhatsApp tab. -> its text. Raises _Fail(spoken reply)."""
    b = zc._browser()
    sb = zc._short(b)
    try:
        raw = zc._tab_exec(b, 'web.whatsapp.com', js)
    except Exception as e:
        if 'javascript' in str(e).lower():
            raise _Fail(f"I can't drive {sb} tabs yet{zc.call_suffix()}. In {sb}, turn on View, Developer, Allow JavaScript from Apple Events.")
        raise _Fail(f"I couldn't reach WhatsApp{zc.call_suffix()}.")
    if raw == 'NOBROWSER':
        raise _Fail(f"{sb} isn't open{zc.call_suffix()}.")
    if raw == 'NOTAB':
        raise _Fail(f"WhatsApp isn't open in {sb}{zc.call_suffix()}. Say open WhatsApp first.")
    return raw


def _clean_names(rows):
    return [zc._wa_clean(n) for n in rows if zc._wa_clean(n)]


def _match(want, names):
    """The chats whose name fits what was said: one exact hit wins, else every name holding all the spoken words."""
    w = zc._norm(want)
    ws = w.split()
    if not ws:
        return []
    norm = [(n, zc._norm(n)) for n in names]
    exact = [n for n, k in norm if k == w]
    if len(exact) == 1:
        return exact
    hits = [n for n, k in norm if all(any(tok.startswith(x) for tok in k.split()) for x in ws)]
    firsts = [n for n in hits if zc._norm(n).split()[:len(ws)] == ws]
    if len(firsts) == 1 and not exact:
        return firsts
    return exact or hits


def _or(xs):
    return ' and '.join(xs) if len(xs) < 3 else ', '.join(xs[:-1]) + ', and ' + xs[-1]


def _wa_draft(name, msg, chosen=None):
    try:
        zc._focus_or_open('web.whatsapp.com', _WA_URL)
        time.sleep(0.6)
        if chosen is None:
            if _wa(_JS_SEARCH % json.dumps(name)) == 'NOSEARCH':
                return f"I can't find WhatsApp's search box{zc.call_suffix()}. Is it signed in?"
            time.sleep(1.4)
            names = _clean_names(json.loads(_wa(_JS_ROWS) or '[]'))
            hits = _match(name, names)
            if not hits:
                _wa(_JS_SEARCH % '""')
                return f"I don't see anyone called {name} on WhatsApp{zc.call_suffix()}."
            if len(hits) > 1:
                _save({'kind': 'pick', 'app': 'whatsapp', 'name': name, 'msg': msg, 'options': hits[:4]})
                return f"I see {_or(hits[:4])} on WhatsApp. Which one should get it?"
            chosen = hits[0]
        if _wa(_JS_OPEN % json.dumps(chosen)) != 'OK':
            return f"I couldn't open the chat with {chosen}{zc.call_suffix()}."
        time.sleep(1.2)
        d = json.loads(_wa(_JS_TYPE % json.dumps(msg)) or '{}')
        if d.get('err') or zc._norm(d.get('chat') or '') != zc._norm(chosen) or zc._norm(d.get('text') or '') != zc._norm(msg):
            _wa(_JS_TYPE % '""')
            return f"I couldn't set up the message to {chosen}{zc.call_suffix()}. Nothing was sent."
        _save({'kind': 'send', 'app': 'whatsapp', 'name': name, 'chat': chosen, 'msg': msg})
        return f"Send '{msg}' to {chosen} on WhatsApp?"
    except _Fail as e:
        return str(e)
    except Exception:
        return f"I couldn't set up that message{zc.call_suffix()}. Nothing was sent."


def _wa_send(p):
    try:
        d = json.loads(_wa(_JS_STATE) or '{}')
        if zc._norm(d.get('chat') or '') != zc._norm(p['chat']) or zc._norm(d.get('text') or '') != zc._norm(p['msg']):
            _wa(_JS_TYPE % '""')
            return f"The chat changed, so I didn't send it{zc.call_suffix()}."
        if _wa(_JS_SEND) != 'OK':
            return f"I couldn't find WhatsApp's send button{zc.call_suffix()}. It's typed, press enter yourself."
        time.sleep(0.8)
        left = json.loads(_wa(_JS_STATE) or '{}').get('text')
        _wa(_JS_SEARCH % '""')
        return f"Sent{zc.call_suffix()}." if not left else f"I pressed send but it's still in the box{zc.call_suffix()}. Check WhatsApp."
    except _Fail as e:
        return str(e)
    except Exception:
        return f"I couldn't send it{zc.call_suffix()}. Check WhatsApp."


_JS_STATE = ("(function(){var c=document.querySelector('#main footer [contenteditable=true]')||document.querySelector('footer [contenteditable=true]');"
             "var h=document.querySelector('#main header span[title]');return JSON.stringify({chat:h?h.getAttribute('title'):'',text:c?(c.innerText||'').trim():''})})()")


def _wa_cancel():
    try:
        _wa(_JS_TYPE % '""')
        _wa(_JS_SEARCH % '""')
    except Exception:
        pass


# ---------------------------------------------------------------- Slack / Discord (installed apps: quick switcher + typing through System Events)
def _keys(script):
    return zc._osa('tell application "System Events"\n' + script + '\nend tell', 10)


def _front(app):
    zc._run(['open', '-a', app], 10)
    time.sleep(0.8)


def _window(app):
    import zuka_apps
    d = zuka_apps.hands_read(app, 1, head=True) or {}
    return zc._norm((d.get('window') or '') + ' ' + (d.get('page') or ''))


def _app_draft(app, name, msg):
    label = APPS[app]
    try:
        import zuka_apps
        if not zuka_apps.running(label):
            return f"{label} isn't open{zc.call_suffix()}. Say open {label} first."
        _front(label)
        _keys('keystroke "k" using command down\ndelay 0.6\nkeystroke ' + zc._as_str(name) + '\ndelay 1.2\nkey code 36\ndelay 1.0')
        win = _window(label)
        if not all(w in win for w in zc._norm(name).split()):
            _keys('key code 53')
            return f"I couldn't find {name} on {label}{zc.call_suffix()}. Nothing was sent."
        _keys('keystroke ' + zc._as_str(msg))
        _save({'kind': 'send', 'app': app, 'name': name, 'chat': name, 'msg': msg})
        return f"Send '{msg}' to {name} on {label}?"
    except Exception:
        return f"I couldn't set up that message{zc.call_suffix()}. Nothing was sent."


def _app_send(p):
    label = APPS[p['app']]
    try:
        _front(label)
        if not all(w in _window(label) for w in zc._norm(p['chat']).split()):
            return f"The {label} window changed, so I didn't send it{zc.call_suffix()}."
        _keys('key code 36')
        return f"Sent{zc.call_suffix()}."
    except Exception:
        return f"I couldn't send it{zc.call_suffix()}. Check {label}."


def _app_cancel(p):
    try:
        _keys('keystroke "a" using command down\nkey code 51')
    except Exception:
        pass


# ---------------------------------------------------------------- confirm / pick (runs first in zuka_commands._handle)
def confirm(t):
    """The yes / no / which-one that answers a pending send. None when nothing is pending or t doesn't answer it."""
    p = _load()
    if not p:
        return None
    t0 = (t or '').strip()
    t = _TAIL.sub('', _FILL.sub('', t0)).strip()
    t = re.sub(r"^(?:yes|yeah|yep|ya|ok|okay|haan) ", '', t) if p.get('kind') == 'pick' else t
    if p.get('kind') == 'pick':
        if _NO.match(t):
            _drop()
            return "Okay, not sent."
        hits = _match(t, p['options']) if t else []
        if len(hits) == 1:
            _drop()
            return _wa_draft(p['name'], p['msg'], chosen=hits[0])
        if re.fullmatch(r"(?:first|1|one|the first one)", t):
            _drop()
            return _wa_draft(p['name'], p['msg'], chosen=p['options'][0])
        if re.fullmatch(r"(?:second|2|two|the second one)", t) and len(p['options']) > 1:
            _drop()
            return _wa_draft(p['name'], p['msg'], chosen=p['options'][1])
        return None
    if _YES.match(t) or _YES.match(t0):
        _drop()
        return _wa_send(p) if p['app'] == 'whatsapp' else _app_send(p)
    if _NO.match(t) or _NO.match(t0):
        _drop()
        _wa_cancel() if p['app'] == 'whatsapp' else _app_cancel(p)
        return "Okay, not sent."
    return None


# ---------------------------------------------------------------- reading
_READ_VERB = r"(?:read|read out|read me out|read me|read to me|read it out|tell me|show me|show|check|give me|get me|open and read|go through|play)"
_NOUN = r"(?:messages?|chats?|texts?|dms?|direct messages?|notifications?|inbox|unreads?|updates?|mentions?)"
_APPK = r"(?P<a>whatsapp|whats app|whatsap|watsapp|slack|discord)"
_APPU = r"(whatsapp|whats app|whatsap|watsapp|slack|discord)"
_READ_APP = re.compile(r"^(?:" + _READ_VERB + r" )?(?:out )?(?:all )?(?:(?:my|the|any|all) )?(?:new |unread |latest |recent |last )?" + _APPK + r"(?: web)?(?: " + _NOUN + r")?(?: out| aloud| out loud)?$")
_READ_APP2 = re.compile(r"^(?:" + _READ_VERB + r" )(?:out )?(?:all )?(?:(?:my|the|any|all) )?(?:new |unread |latest |recent |last )?" + _NOUN + r" (?:on|in|from|of) (?:my )?" + _APPK + r"(?: web)?(?: out| aloud)?$")
_ANY = re.compile(r"^(?:(?:do i have|have i got|got|is there|are there|did i get|did i have|have i)(?: any| anything)?|any|anything|whats|what is|what are|show me|tell me)(?: (?:new|unread|more))?(?: " + _NOUN + r")?(?: for me)?(?: (?:on|in|from|at) (?:my )?" + _APPK + r"(?: web)?)(?: today| now| lately| right now| yet)?$")
_WHATS_ON = re.compile(r"^(?:whats|what is|what are|anything|whats new|what s new) (?:on|in|new on|new in|happening on|happening in) (?:my )?" + _APPK + r"(?: web)?(?: today| now| right now)?$")
_WHO_MSG = re.compile(r"^who (?:has |all |else )?(?:messaged|texted|dmd|dmed|pinged|wrote|sent|messaged me|texted me|dm ed|whatsapped|slacked)(?: me)?(?: (?:on|in|over) (?:my )?" + _APPK + r")?(?: today| lately| just now| recently| so far)?$")
_WHO_MSG2 = re.compile(r"^who (?:is|are|was|were) (?:messaging|texting|pinging)(?: me)?(?: (?:on|in) (?:my )?" + _APPU + r")?$|^who (?:wants|needs) me(?: (?:on|in) (?:my )?" + _APPU + r")?$|^(?:any|anyone|anybody|someone|somebody)(?: new)? (?:messaged|texted|pinged|dmd|dmed) me(?: (?:on|in) (?:my )?" + _APPU + r")?$|^did (?:anyone|someone|somebody) (?:message|text|ping|dm) me(?: (?:on|in) (?:my )?" + _APPU + r")?$")
_NEW_APP = re.compile(r"^(?:any |got any |have i got any |do i have any )?(?:new|unread|latest|recent) " + _APPU + r" (?:messages?|chats?|texts?|dms?|notifications?)(?: for me)?$|^" + _APPU + r" (?:messages?|dms?|notifications?|unread|chats?|inbox|texts?)(?: please)?$")
_SAY_NAME = re.compile(r"^(?:what did|what has|what have|what does|whats|what is) (?P<n>[a-z0-9 ]+?) (?:say|said|send|sent|write|wrote|text|texted|message|messaged|reply|replied|tell me|ask)(?: to me| me)?(?: (?:on|in|over) (?:my )?" + _APPU + r")?$"
                       r"|^(?:read|show|open|check|get|play)(?: me)?(?: out)?(?: the| my)?(?: last| latest| new| recent)? (?P<n2>[a-z0-9 ]+?)(?: s)? (?:message|messages|text|texts|chat|dm|reply)(?: out)?(?: (?:on|in|over|from) (?:my )?" + _APPU + r")?$"
                       r"|^(?:read|show|check)(?: me)?(?: out)? (?:the |my |any )?(?:(?:last|latest|new|recent|unread) )?(?:messages?|texts?|chats?|dms?) (?:from|by|of) (?P<n3>[a-z0-9 ]+?)(?: (?:on|in) (?:my )?" + _APPU + r")?$"
                       r"|^(?:any|anything|do i have any|have i got any|got any)(?: new| unread)? (?:messages?|texts?|dms?|replies?|reply) from (?P<n4>[a-z0-9 ]+?)(?: (?:on|in) (?:my )?" + _APPU + r")?$"
                       r"|^did (?P<n5>[a-z0-9 ]+?) (?:message|text|reply|replied|write|ping|dm)(?: me)?(?: back)?(?: yet| today| lately)?(?: (?:on|in) (?:my )?" + _APPU + r")?$"
                       r"|^has (?P<n6>[a-z0-9 ]+?) (?:messaged|texted|replied|written|pinged)(?: me)?(?: back)?(?: yet| today)?(?: (?:on|in) (?:my )?" + _APPU + r")?$")
_OPEN_WA = re.compile(r"^(?:open|launch|start|bring up|pull up|show|go to|switch to|take me to|get me|focus|put on)(?: up)?(?: me)? (?:my |the )?(?:whatsapp|whats app|whatsap|watsapp)(?: web| tab| page| chat| chats| messages| app| website)?$")
_OPEN_SL = re.compile(r"^(?:open|launch|start|bring up|pull up|show|go to|switch to|focus)(?: up)? (?:my |the )?(?P<a>slack|discord)(?: app| dms| messages)?$")
_NOT_PEOPLE = {'linkedin', 'instagram', 'facebook', 'clickup', 'sms', 'phone', 'twitter', 'telegram', 'signal', 'premiere', 'the', 'my', 'any', 'all', 'new', 'last', 'latest', 'unread', 'recent', 'whatsapp', 'slack', 'discord', 'me', 'you', 'it', 'this', 'that', 'out', 'mail', 'email', 'gmail', 'voice', 'text', 'every', 'each', 'both', 'more'}


def _read(app, name=None):
    import zuka_work
    if app == 'whatsapp':
        if not name:
            return zc._read_inbox('whatsapp', True)
        return zuka_work._wa_say(name)
    r = zuka_work._chat(app)
    if name:
        low = zc._norm(name)
        hits = [x.strip() for x in re.split(r"[;\n]", r) if low in zc._norm(x)]
        return (f"{APPS[app]}: " + '; '.join(hits[:3]) + '.') if hits else f"I don't see anything from {name} on {APPS[app]}{zc.call_suffix()}."
    return r


def handle(t, raw=''):
    """A spoken reply, or None. t = normalised words."""
    t = zc._norm(_strip(t))
    if not t:
        return None
    if _OPEN_WA.match(t):
        return "WhatsApp's up." if zc._focus_or_open('web.whatsapp.com', _WA_URL) else f"I couldn't open WhatsApp{zc.call_suffix()}."
    m = _OPEN_SL.match(t)
    if m and not zc._installed_app(m.group('a'), APPS[m.group('a')]):
        return None
    for rx in (_READ_APP, _READ_APP2, _ANY, _WHATS_ON, _WHO_MSG, _WHO_MSG2, _NEW_APP):
        m = rx.match(t)
        if m:
            a = next((g for g in (m.groupdict().get(k) for k in ('a',)) if g), None) or next((g for g in m.groups() if g in ('slack', 'discord') or (g or '').startswith(('whats', 'wats', 'what'))), None)
            if a:
                return _read(_appkey(a))
            if rx in (_WHO_MSG, _WHO_MSG2):
                return None   # "who messaged me" on no named app: the inbox summary (zuka_commands) reads every open one
    m = _SAY_NAME.match(t)
    if m:
        d = m.groupdict()
        n = next((d[k] for k in ('n', 'n2', 'n3', 'n4', 'n5', 'n6') if d.get(k)), '')
        n = re.sub(r" s$", '', n.strip())
        a = next((g for g in m.groups() if g and g.startswith(('whats', 'wats', 'what', 'slack', 'discord'))), None)
        if n and n.split()[0] not in _NOT_PEOPLE and len(n.split()) <= 3 and n not in ('he', 'she', 'they', 'i', 'we', 'time', 'weather', 'date'):
            return _read(_appkey(a) if a else 'whatsapp', n)
    ps = parse_send(raw or t)
    if ps:
        app, name, msg = ps
        _drop()
        return _wa_draft(name, msg) if app == 'whatsapp' else _app_draft(app, name, msg)
    return None
