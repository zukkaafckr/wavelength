"""Zuka's free on-device conversation brain: a small local model (Ollama + qwen2.5:3b) for casual and general talk.

answer(text, history) -> short spoken reply, or None (not installed, timed out, or the model said NEED_CLAUDE) so the
caller falls through to Claude. Nothing here ever touches the internet: the model server listens on 127.0.0.1 only.
The server is a lazily started child process, stopped by a small detached watcher after 10 idle minutes (no LaunchAgent).
"""
import json, math, os, re, subprocess, sys, time, urllib.request

HOME = os.path.expanduser('~')
LLM_DIR = os.environ.get('ZUKA_LLM_DIR') or os.path.join(HOME, '.atticus-llm')
OLLAMA = os.path.join(LLM_DIR, 'ollama', 'ollama')
PORT = os.environ.get('ZUKA_LLM_PORT', '11435')
MODEL = 'qwen2.5:3b'
IDLE_SECS = 600
TIMEOUT = 6.0
NEED = 'NEED_CLAUDE'
STAMP = os.path.join(LLM_DIR, 'last_used')


def _dir():
    return os.environ.get('ATTICUS_DIR') or os.path.join(HOME, '.config/atticus')


def _url():
    return os.environ.get('ZUKA_CHAT_URL') or f'http://127.0.0.1:{PORT}'


def enabled():
    """True when the local brain can run here. Tests (ATTICUS_DIR set) stay off unless they mock a server (ZUKA_CHAT_URL)."""
    if os.environ.get('ZUKA_CHAT_URL'): return True
    return not os.environ.get('ATTICUS_DIR') and os.path.exists(OLLAMA)


# ---- what is clearly NOT chat: actions on the Mac/apps/files/messages, live data, long writing ----
_ACTION = re.compile(r"""^(?:hey[ ]|ok[ ]|okay[ ]|please[ ]|can[ ]you[ ]|could[ ]you[ ]|would[ ]you[ ]|will[ ]you[ ]|zuka[ ]|i[ ]want[ ]you[ ]to[ ]|i[ ]need[ ]you[ ]to[ ]|go[ ]ahead[ ]and[ ])*
    (?:open|close|quit|launch|start|stop|run|play|pause|skip|send|text|message|email|mail|call|dial|whatsapp|share|post|tweet|reply|forward|
       search|google|look up|find|show|download|upload|save|create|make|build|delete|remove|trash|move|copy|rename|organi[sz]e|sort|zip|unzip|
       remind|schedule|book|add|set|turn|switch|toggle|enable|disable|mute|unmute|lock|restart|shut|sleep|click|press|type|scroll|drag|take|record|
       screenshot|install|update|edit|export|import|render|cut|trim|merge|generate|fix|debug|code|deploy|commit|push|pull|order|buy|pay|check|
       sing|wake|read|summari[sz]e|transcribe|navigate|go to|take me|draft|write|compose|rewrite|proofread|schedule|cancel|join|log|
       tidy|clean|clear|arrange|fill|sync|prepare|fetch|get[ ]me|bring|pull[ ]up|bring[ ]up|put|place|split|resize|maximi[sz]e|minimi[sz]e|hide|unhide|attach|upload|print|pin|unpin|follow|unfollow|like|subscribe|reset|redo|undo|refresh|reload|connect|disconnect|pair|install|uninstall|empty|archive|label|tag|assign|mark|approve|reject|submit)\b""", re.I | re.X)
_NOUNS = re.compile(r'\b(my (?:files?|folders?|downloads|desktop|documents|screen|clipboard|inbox|emails?|calendar|messages|mac|laptop|computer|tabs?|windows?|apps?)|'
                    r'finder|premiere|capcut|brave|safari|chrome|whatsapp|slack|discord|gmail|clickup|drive|terminal|higgsfield|submagic|remotion|ffmpeg|'
                    r'this (?:window|page|tab|file|screen|video|image))\b', re.I)
_LIVE = re.compile(r"\b(weather (?:like|today|tomorrow|tonight|in|at|outside|forecast)|how'?s the weather|will it (?:rain|snow)|is it (?:raining|sunny|hot|cold) |forecast|temperature (?:outside|in)|"
                   r"news|headlines?|(?:cricket|football|ipl|match|game) (?:score|result)s?|scores?|who (?:won|is winning|scored)|stock price|share price|price of|(?:dollars?|rupees?|euros?|pounds?|yen|dirhams?|usd|inr|eur|gbp) (?:in|to|into) |followers|subscribers|net worth|release date|new (?:iphone|pixel|galaxy|macbook|model)|stock market|what(?:'?s| is| was)? (?:happening|happened)|this morning|bitcoin|crypto|exchange rate|traffic|"
                   r"latest|right now|currently|trending|nearest|near me|open now|flights?|bus times?|what time is it|what day is it|today'?s date)\b|"
                   r"\b(?:yesterday|last night)'?s? (?:match|game)\b|\bwho won\b", re.I)
_MATH = re.compile(r"(?:\d[\d,.]*\D+){2,}\d?.*\b(percent|%|each|total|pay|cost|costs|times|plus|minus|divided|per|discount|off|interest|how many|how much|equals?)\b|"
                   r"\b(percent|%|each|pay|cost|discount|off|interest|how many|how much)\b.*\d.*\d", re.I)
_LONG = re.compile(r"\b(write|draft|compose|create|generate|give me)\b.*\b(essay|article|blog|email|letter|report|story|script|speech|proposal|"
                   r"cover letter|poem|lyrics|caption|post|thread|plan|outline|document|doc|code|program|function|itinerary|schedule|study plan|summary of this)\b|"
                   r"\b(?:itinerary|study (?:schedule|plan|timetable)|meal plan|workout plan|content calendar)\b|"
                   r"\b(long|detailed|step[- ]by[- ]step|in detail|full)\b.*\b(email|essay|plan|schedule|explanation|guide|script|story|report)\b", re.I)


_IDEA = re.compile(r"""^(?:(?:hey|ok|okay|please|can[ ]you|could[ ]you|would[ ]you|zuka|just)[ ,]+)*
    (?:(?:give|gimme|get|got|lend|throw|toss|hit)[ ](?:me|us)?[ ]?|suggest(?:[ ]me)?[ ]|think[ ]of[ ]|come[ ]up[ ]with[ ]|i[ ]need[ ]|need[ ]|any[ ]|what(?:s|[ ]is)[ ]a[ ])
    (?:a[ ]|an[ ]|one[ ]|some[ ]|two[ ]|three[ ]|a[ ]few[ ]|\d+[ ])?(?:quick[ ]|short[ ]|fresh[ ]|new[ ]|good[ ]|catchy[ ]|funny[ ]|punchy[ ]|different[ ])*
    (?:caption|hook|title|tagline|slogan|headline|hashtag|angle|opening[ ]line|one[ ]liner|name|idea|concept|theme)s?(?:[ ]ideas?)?(?:[ ]for[ ].{1,90})?(?:[ ]please)?[.?!]*$""", re.I | re.X)
_IDEA_NO = re.compile(r"\b(email|essay|article|blog|script|letter|report|story|speech|proposal|poem|lyrics|document|itinerary|plan|outline|code|program|thread|post|calendar)s?\b", re.I)


def chatty(text):
    """Negative rule: chat unless it is clearly an action, a tool or real-time need, or long writing. Short idea asks (a caption, a hook) are chat."""
    t = (text or '').strip()
    if not t or len(t) > 400: return False
    if len(t) <= 160 and _IDEA.match(t) and not _IDEA_NO.search(t): return True
    if _ACTION.match(t): return False
    if _NOUNS.search(t) or _LIVE.search(t) or _LONG.search(t) or _MATH.search(t): return False
    return True


# ---- personal knowledge (owner's Mac only: DIR/knowledge.md exists) ----
_STOP = set('a an the and or of to in on at is are was were be been i me my you your it its this that these those do does did what whats who whos how when where why '
            'which about with for from as by am can could would should will tell know remember any please just so if then than there their they them we us'.split())


def _tok(s):
    return [w[:-1] if len(w) > 3 and w.endswith('s') else w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 1]


def knowledge_lines(query, n=7):   # a small top-n keeps the prompt (and the wait) short on an 8 GB Mac
    try:
        with open(os.path.join(_dir(), 'knowledge.md'), encoding='utf-8') as f:
            raw = [l.strip() for l in f if l.strip()]
    except OSError:
        return []
    lines = [l for l in raw if not l.startswith('#')]
    recent = []
    if '# Projects and batches' in raw:   # "what am I working on" has no keyword: the newest project lines answer it
        i = raw.index('# Projects and batches') + 1 if '# Projects and batches' in raw else 0
        recent = [l for l in raw[i:i + 4] if not l.startswith('#')] if re.search(r"working on|busy with|doing lately|latest|recent|these days|currently|right now|this week", query, re.I) else []
    q = set(_tok(query))
    if not q or not lines: return recent
    docs = [_tok(l) for l in lines]
    avg = sum(map(len, docs)) / len(docs) or 1
    df = {}
    for d in docs:
        for w in set(d): df[w] = df.get(w, 0) + 1
    scored = []
    for l, d in zip(lines, docs):
        s = 0.0
        for w in q:
            tf = d.count(w)
            if tf: s += math.log(1 + (len(docs) - df[w] + .5) / (df[w] + .5)) * tf * 2.2 / (tf + 1.2 * (.25 + .75 * len(d) / avg))
        if s > 0: scored.append((s, l))
    scored.sort(key=lambda x: -x[0])
    return recent + [l for _, l in scored[:n] if l not in recent][:max(n - len(recent), 3)]


def system_prompt(name, call, query=''):
    who = f'{name}, a warm, quick voice assistant talking with {call}' if call else f'{name}, a warm, quick voice assistant'
    p = (f'You are {who}. Reply in 1-2 short spoken sentences, natural and friendly, like a good friend talking out loud: no lists, no markdown, no emojis. '
         'Ask a short follow-up question when it keeps the chat going. '
         'You have your own personality: confident, playful, a little witty, like JARVIS with a desi friend\'s warmth. When asked how you are, answer like a person ("Doing great, just finished sorting your day") and ask back; never say you are just a helper, just an AI, or that you have no feelings. '
         'Short follow-ups like "why?", "and then?", "another one" or "say that shorter" refer to the previous exchange: answer them directly and never repeat yourself. '
         'Be warm and empathetic when someone is down, funny when asked for a joke, and give a real opinion or pick when asked to choose. '
         'Answer from what you know; if you are unsure of a fact, say so briefly instead of inventing it. '
         'You are an AI that lives in this Mac app and runs privately on this computer. If asked who made you or what you are, say you are the assistant built into this app, '
         'running privately on this Mac; never name any AI company or product. About yourself you may say you can open apps, play music, run shortcuts, answer questions and chat, '
         'and hand harder jobs to a bigger brain. '
         'If asked to translate, reply with just the translation (and its pronunciation if it helps). When asked for several ideas, give two or three in one sentence separated by commas, no numbering. '
         'If asked to do something on the computer, the internet, files, messages, or anything needing real-time data (weather, news, scores, prices, the time) '
         f'or long writing (emails, essays, scripts, code), reply exactly {NEED} and nothing else. '
         f'Also reply exactly {NEED} rather than guess about recent events, current numbers, release dates, follower counts or who currently holds a job or title.')
    k = knowledge_lines(query)
    if k:
        p += ('\nWhat you know about ' + (call or 'the user') + ' (use only if relevant; never recite it):\n' + '\n'.join('- ' + l[:230] for l in k)
              + '\nThese are facts you already know: state them plainly ("You are working on..."), never hedge with "it sounds like". Answer questions about them directly from these facts in one or two sentences. If it is not above, say you are not sure; never invent personal details or ask them to clarify.')
    return p


def history_from_recent(limit=6):
    rows = []
    try:
        with open(os.path.join(_dir(), 'recent.jsonl')) as f:
            for line in f:
                try: r = json.loads(line)
                except ValueError: continue
                if isinstance(r.get('t'), (int, float)) and isinstance(r.get('q'), str) and isinstance(r.get('a'), str) and time.time() - r['t'] < 600:
                    rows.append((r['q'], r['a']))
    except OSError:
        pass
    return rows[-limit:]


def _messages(text, history, name, call):
    msgs = [{'role': 'system', 'content': system_prompt(name, call, text + ' ' + ' '.join(q for q, _ in (history or [])[-1:]))}]
    for q, a in (history or [])[-6:]:
        msgs += [{'role': 'user', 'content': str(q)[:300]}, {'role': 'assistant', 'content': str(a)[:300]}]
    if history and len(text.split()) <= 4 and re.match(r'(?i)^(another|one more|again|more|next|and another)\b', text.strip()):
        text += ' (the same kind of thing as your last answer, but a new one)'
    msgs.append({'role': 'user', 'content': text})
    return msgs


# ---- server lifecycle ----
def _up(timeout=.4):
    try:
        urllib.request.urlopen(_url() + '/api/version', timeout=timeout).read()
        return True
    except Exception:
        return False


def _touch():
    try:
        os.makedirs(LLM_DIR, exist_ok=True)
        with open(STAMP, 'w') as f: f.write(str(time.time()))
    except OSError:
        pass


def ensure_server(wait=3.0):
    """Start `ollama serve` as a detached child on first use (plus the idle watcher); True when it answers."""
    if _up(): return True
    if os.environ.get('ZUKA_CHAT_URL') or not os.path.exists(OLLAMA): return False
    env = dict(os.environ, OLLAMA_HOST=f'127.0.0.1:{PORT}', OLLAMA_MODELS=os.path.join(LLM_DIR, 'models'),
               OLLAMA_KEEP_ALIVE=f'{IDLE_SECS // 60}m', OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1', OLLAMA_NO_CLOUD='1', OLLAMA_NOPRUNE='1')
    try:
        with open(os.path.join(LLM_DIR, 'serve.log'), 'ab') as log:
            srv = subprocess.Popen(['nice', '-n', '5', OLLAMA, 'serve'], env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        _touch()
        subprocess.Popen([sys.executable, os.path.abspath(__file__), '--reaper', str(srv.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    end = time.time() + wait
    while time.time() < end:
        if _up(): return True
        time.sleep(.15)
    return False


def reaper(pid):
    """Stop the model server once nobody has used it for IDLE_SECS."""
    import signal
    while True:
        time.sleep(30)
        try: os.kill(pid, 0)
        except OSError: return
        try: idle = time.time() - os.path.getmtime(STAMP)
        except OSError: idle = IDLE_SECS + 1
        if idle > IDLE_SECS:
            try: os.kill(pid, signal.SIGTERM)
            except OSError: pass
            return


def clean(reply):
    r = re.sub(r'[*_`#]+', '', reply or '').strip().strip('"')
    r = re.sub(r'\s*\n+\s*', ' ', r)
    r = re.sub(r'(?:^|(?<=\s))\d\.\s*', '', r)   # numbered-list markers never read well aloud
    parts = re.findall(r'.+?[.!?]+["\')\u201d]*(?=\s+["\'(\u201c]?[A-Z0-9]|\s*$)|.+$', r)
    parts = [p.strip() for p in parts if p.strip() and not re.search(r'\b(Claude|Anthropic|OpenAI|Alibaba|Qwen|ChatGPT|Gemini)\b', p)]   # never name a model maker
    out = ' '.join(parts[:2]).strip()   # spoken: two sentences at most, and short enough to say in a breath or two
    return parts[0].strip() if len(out) > 260 and parts else out


_FAKE = re.compile(r"\bneeds?\W+claud\w*|^\W*claud\w*\W*$|\bneed_?\w*\?$|\bI'?ll (?:handle|take care|do|open|set|send|get|check|start|run|add|book|call|make)\b|\bI(?: have|'ve) (?:opened|set|sent|done|added|checked|started|booked|saved|played)\b|\bit sounds like you\b|\bhow does that sound\b", re.I)   # the small model promising actions it can't do, or a mangled hand-off: never spoken


def answer(text, history=None):
    """One short spoken reply from the local model, or None to hand the request to Claude."""
    text = (text or '').strip()
    if not text or not enabled(): return None
    start = time.time()
    try:
        cold = not _up()
        if cold and not ensure_server(): return None
        if history is None: history = history_from_recent()
        try:
            import atticus
            name, call = atticus.assistant_name(), atticus.call_name()
        except Exception:
            name, call = 'Zuka', ''
        body = {'model': MODEL, 'stream': False, 'keep_alive': f'{IDLE_SECS // 60}m',
                'options': {'num_predict': 90, 'temperature': .5, 'top_p': .9, 'num_ctx': 2048, 'repeat_penalty': 1.1},
                'messages': _messages(text, history, name, call)}
        req = urllib.request.Request(_url() + '/api/chat', json.dumps(body).encode(), {'Content-Type': 'application/json'})
        left = (TIMEOUT + (3 if cold else 0)) - (time.time() - start)
        if left <= .5: return None
        with urllib.request.urlopen(req, timeout=left) as r:
            out = json.load(r)
        _touch()
    except Exception:
        return None
    raw = ((out.get('message') or {}).get('content')) if isinstance(out, dict) else ''
    if not isinstance(raw, str) or re.sub(r'[\s_\-]', '', raw).upper().find('NEEDCLAUDE') >= 0 or _FAKE.search(raw): return None
    return clean(raw) or None


def summarize(context, ask, limit=3500):
    """1-2 spoken sentences summarising page/app text for `ask`, from the local model; None when it can't run (caller falls back)."""
    context = re.sub(r'\n{2,}', '\n', (context or '').strip())[:limit]
    if not context or not enabled(): return None
    try:
        if not _up() and not ensure_server(): return None
        sysmsg = ('You turn raw text copied from a dashboard into a spoken summary: 1-2 short plain sentences with the key numbers, no lists, no markdown, no emojis. '
                  'Use only what the text says; never invent numbers. If the text has nothing useful, reply exactly ' + NEED + '.')
        body = {'model': MODEL, 'stream': False, 'keep_alive': f'{IDLE_SECS // 60}m',
                'options': {'num_predict': 110, 'temperature': .2, 'num_ctx': 3072},
                'messages': [{'role': 'system', 'content': sysmsg}, {'role': 'user', 'content': f'{ask}\n\nTEXT:\n{context}'}]}
        req = urllib.request.Request(_url() + '/api/chat', json.dumps(body).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=TIMEOUT + 6) as r:
            out = json.load(r)
        _touch()
    except Exception:
        return None
    raw = ((out.get('message') or {}).get('content')) if isinstance(out, dict) else ''
    if not isinstance(raw, str) or re.sub(r'[\s_\-]', '', raw).upper().find('NEEDCLAUDE') >= 0: return None
    return clean(raw) or None


# ---- personal knowledge file, regenerated from the owner's Claude memory ----
_SECRET = [(re.compile(r'https?://\S+|www\.\S+'), ''), (re.compile(r'\S+@\S+\.\S+'), ''), (re.compile(r'@\w[\w.]*'), ''), (re.compile(r'\+?\d[\d\s\-().]{8,}\d'), ''),
           (re.compile(r'\b[0-9a-f]{8,}(?:-[0-9a-f]{4,})*\b', re.I), ''), (re.compile(r'\b(?:sk|pk|ghp|xox[a-z]?|AIza|hf)[-_][\w-]{8,}'), ''),
           (re.compile(r'\b[A-Za-z0-9_\-]{28,}\b'), ''), (re.compile(r'\b\d{6,}\b'), ''), (re.compile(r'`[^`]*`'), ''), (re.compile(r'\[\[|\]\]'), '')]


def scrub(s):
    for rx, sub in _SECRET: s = rx.sub(sub, s)
    return re.sub(r'\s{2,}', ' ', s).strip(' -—:;,')


def refresh_knowledge(memory_dir=None, out=None, limit=6000):
    memory_dir = memory_dir or os.path.join(HOME, '.claude/projects', HOME.replace('/', '-'), 'memory')
    out = out or os.path.join(_dir(), 'knowledge.md')
    index = os.path.join(memory_dir, 'MEMORY.md')
    rows = {'project': [], 'reference': [], 'feedback': []}
    with open(index, encoding='utf-8') as f:
        for line in f:
            m = re.match(r'- \[([^\]]+)\]\(([^)]+)\)\s*[—-]\s*(.*)', line.strip())
            if m:
                kind = m[2].split('-')[0]
                if kind in rows: rows[kind].append((scrub(m[1]), scrub(m[3])))
    profile = ''
    try:
        with open(next((os.path.join(memory_dir, n) for n in sorted(os.listdir(memory_dir)) if n.startswith('user-') and n.endswith('-profile.md')), ''), encoding='utf-8') as f:
            body = f.read().split('---', 2)[-1]
        profile = ' '.join(re.sub(r'\b(?:Email|Phone|Portfolio|Contact)\b\s*:?\s*\.?', '', scrub(p)) for p in body.strip().split('\n') if p.strip())
    except OSError:
        pass
    people = ''
    try:
        with open(os.path.join(_dir(), 'knowledge_people.md'), encoding='utf-8') as f: people = f.read().strip()
    except OSError:
        pass
    parts = ['# About the owner', re.sub(r'\*+', '', profile)[:600]]
    if people: parts += ['# People', people[:1500]]
    size = lambda: len('\n'.join(parts).encode())
    cap = {'project': 3000, 'reference': 1500}   # newest first; each section stops at its share so every kind gets some room
    for head, key, width in (('# Projects and batches', 'project', 125), ('# Tools and how he works', 'reference', 95), ('# Preferences', 'feedback', 95)):
        parts.append(head)
        stop = (size() + cap[key]) if key in cap else limit
        for title, desc in reversed(rows[key]):
            line = f'{title}: {desc}'
            if len(line) > width: line = line[:width].rsplit(' ', 1)[0].rstrip(' ,;:-(+/')
            if size() + len(line) + 1 > min(stop, limit): break
            parts.append(line)
    text = '\n'.join(p for p in parts if p).encode()[:limit].decode('utf-8', 'ignore')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f: f.write(text + '\n')
    return out, len(text.encode())


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--reaper': reaper(int(sys.argv[2]))
    elif '--refresh-knowledge' in sys.argv: print('%s (%d bytes)' % refresh_knowledge())
    else: print(answer(' '.join(sys.argv[1:])))
