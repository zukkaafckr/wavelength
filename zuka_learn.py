"""Zuka's daily learning engine: learns a person's real routine from their own Mac, all on-device.

Public API
  learn(dry=False)        build habits.json (+ merge learned prefs into workflow.json) -> habits dict
  alias(t)                learned phrasing -> the phrasing that works; also routes free music requests
  suggestion(now=None)    one short proactive spoken line, or None (rate-limited, never during calls)
  gaps_report()           requests that still needed Claude but look mechanical -> gaps.md
  music_pick(request)     "play something I like / for focus / Punjabi songs / something new" -> a pick dict or None
CLI: python3 zuka_learn.py --learn [--dry] | --suggest | --gaps | --summary

Everything stays on the Mac. Sources are read-only (copies of sqlite files). Message contents are never stored.
Test hooks (env): ATTICUS_DIR, ZUKA_KNOWLEDGEC, ZUKA_PMSET_FILE, ZUKA_MEMORY_DIR, ZUKA_BRAVE_HISTORY, ZUKA_MUSIC_JSON.
"""
import collections
import json
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

HOME = os.path.expanduser('~')
SAID = '\x00said:'   # alias() returns SAID + reply when it already played something
MAC_EPOCH = 978307200
DAY_START = 4        # the "day" runs 04:00-04:00: a 1 am session belongs to the day before
WINDOW_DAYS = 90
BUCKETS = (('morning', 5, 11), ('afternoon', 11, 17), ('evening', 17, 22), ('late night', 22, 29))
LANGS = ('hindi', 'english', 'punjabi', 'marathi', 'tamil', 'telugu', 'bengali', 'gujarati', 'bhojpuri', 'kannada', 'malayalam', 'urdu', 'korean', 'spanish')
CONTENT_VERBS = ('message', 'text', 'whatsapp', 'send', 'email', 'mail', 'remind', 'tell', 'reply', 'dm', 'note', 'write', 'say', 'dictate', 'type')
FILLER = {'hey', 'ok', 'okay', 'um', 'uh', 'zuka', 'please', 'kindly', 'just', 'so', 'and', 'then', 'also', 'can', 'could', 'would', 'will', 'you', 'u',
          'the', 'a', 'an', 'my', 'me', 'for', 'to', 'i', 'want', 'need', 'wanna', 'now', 'again', 'quickly', 'real', 'quick', 'lets', 'go', 'ahead', 'thanks', 'is', 'are', 'there', 'any', 'what', 'whats', 'show', 'tell', 'give'}
ACTION_VERBS = ('open', 'close', 'play', 'pause', 'check', 'show', 'set', 'start', 'stop', 'turn', 'create', 'add', 'find', 'search', 'mute', 'unmute', 'list',
                'read', 'launch', 'quit', 'switch', 'lock', 'copy', 'paste', 'move', 'rename', 'delete', 'make', 'run', 'get', 'bring', 'take', 'save', 'export', 'skip', 'next')
IGNORE_BUNDLES = {'com.apple.loginwindow', 'com.apple.finder', 'com.apple.systempreferences', 'com.apple.screensaver', 'com.apple.dock',
                  'com.apple.notificationcenterui', 'com.apple.controlcenter', 'com.apple.universalcontrol', 'com.apple.coreservices.uiagent',
                  'com.apple.securityagent', 'com.apple.systemuiserver', 'com.apple.spotlight', 'com.apple.usernotificationcenter'}
BROWSER_BUNDLES = {'com.brave.browser', 'com.google.chrome', 'company.thebrowser.browser', 'com.microsoft.edgemac', 'com.apple.safari', 'org.mozilla.firefox'}
KEEP_OPEN_SKIP = IGNORE_BUNDLES | BROWSER_BUNDLES

# request types: (name, regex on the normalised request, spoken suggestion subject)
TYPES = (
    ('clickup check', r'\bclick ?up\b|\b(?:my )?tasks?\b|\bwhat(?:s| is) due\b|\bbrief\b', 'check ClickUp'),
    ('music', r'^(?:play|pause|resume|skip|next|shuffle|put on)\b|\bmusic\b|\bsong\b|\bplaylist\b|\bvolume\b', 'put music on'),
    ('messages', r'^(?:message|text|whatsapp|call|facetime|ring|dm|email|mail|reply)\b', 'check messages'),
    ('reminders', r'\bremind(?:er)?s?\b|\btimer\b|\balarm\b', 'set a reminder'),
    ('start day', r'\bstart (?:my |the )?day\b|\bgood morning\b|\bmorning routine\b|\bbegin (?:my )?day\b', 'start your day'),
    ('edit mode', r'\bedit(?:ing)? mode\b|\bstart editing\b|\bpremiere\b', 'start editing'),
    ('weather', r'\bweather\b|\btemperature\b|\brain\b', 'check the weather'),
    ('calendar', r'\bcalendar\b|\bmeeting\b|\bschedule\b|\bevents?\b', 'check your calendar'),
    ('time', r'\bwhat time\b|\bthe time\b|\bdate today\b|\bwhat day\b', 'tell the time'),
    ('open app', r'^(?:open|launch|go to|switch to)\b', 'open things'),
    ('close apps', r'^(?:close|quit|done for the day)\b|\bclose all\b', 'wrap up'),
    ('volume/system', r'\bbrightness\b|\bmute\b|\bwifi\b|\bbluetooth\b|\block\b|\bscreenshot\b|\bdark mode\b', 'adjust the Mac'),
)
TYPES = tuple((n, re.compile(rx), s) for n, rx, s in TYPES)


# ------------------------------------------------------------------ paths
def _dir():
    return os.environ.get('ATTICUS_DIR') or os.path.join(HOME, '.config/atticus')


def _p(name): return os.path.join(_dir(), name)
def _habits_path(): return _p('habits.json')
def _workflow_path(): return _p('workflow.json')
def _log_path(): return _p('log.jsonl')


def _memory_dir():
    d = os.environ.get('ZUKA_MEMORY_DIR') or os.path.join(HOME, '.claude/projects', HOME.replace('/', '-'), 'memory')
    return d if os.path.isdir(d) else None


def _jload(path, default):
    try:
        with open(path) as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def _jsave(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp{os.getpid()}'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def _norm(t):
    t = (t if isinstance(t, str) else '').lower().replace('\u2019', "'")
    t = re.sub(r"\blet'?s\b", 'lets', t)
    t = re.sub(r"\b(what|that|how)'?s\b", r'\1s', t)
    t = re.sub(r"[^a-z0-9#@ ]+", ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _core(t):
    return ' '.join(w for w in t.split() if w not in FILLER)


def _is_content(n):
    """A request that carries message/note contents: never stored."""
    return (n.split() or [''])[0] in CONTENT_VERBS


def _run(args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _bucket(hour):
    h = hour if hour >= 5 else hour + 24
    for name, a, b in BUCKETS:
        if a <= h < b: return name
    return 'late night'


# ------------------------------------------------------------------ the log
def read_log():
    """Zuka's log: one final record per request id (the log is rewritten per step; later rows may lack 'at')."""
    final, order = {}, []
    try:
        with open(_log_path()) as f:
            for line in f:
                try: r = json.loads(line)
                except ValueError: continue
                if not isinstance(r, dict): continue
                k = r.get('id') or f'row{len(order)}'
                if k not in final: final[k] = {}; order.append(k)
                final[k].update({a: b for a, b in r.items() if b is not None})
    except OSError:
        return []
    out = []
    for k in order:
        r = final[k]
        try: r['ts'] = datetime.strptime(r['at'], '%Y-%m-%d %H:%M:%S')
        except (KeyError, ValueError, TypeError): continue
        if isinstance(r.get('task'), str) and r['task'].strip(): out.append(r)
    return sorted(out, key=lambda r: r['ts'])


def _free(r): return r.get('model') == 'instant' and r.get('status') == 'completed'
def _needed_claude(r): return r.get('status') == 'not_handled' or (r.get('model') != 'instant' and r.get('status') not in ('cancelled', 'running'))


def req_type(n):
    for name, rx, _ in TYPES:
        if rx.search(n): return name
    return None


# ------------------------------------------------------------------ app usage + wake/sleep
def _copy_db(src):
    d = tempfile.mkdtemp(prefix='zuka-learn-')
    dst = os.path.join(d, os.path.basename(src))
    shutil.copy2(src, dst)
    for ext in ('-wal', '-shm'):
        if os.path.exists(src + ext): shutil.copy2(src + ext, dst + ext)
    return dst, d


def app_usage(days=WINDOW_DAYS):
    """[(start_datetime, seconds, bundle)] from Screen Time's knowledgeC.db (read from a copy)."""
    src = os.environ.get('ZUKA_KNOWLEDGEC') or os.path.join(HOME, 'Library/Application Support/Knowledge/knowledgeC.db')
    if not os.path.exists(src): return []
    out = []
    try:
        dst, tmp = _copy_db(src)
    except OSError:
        return []
    try:
        con = sqlite3.connect(f'file:{dst}?mode=ro', uri=True)
        since = time.time() - days * 86400 - MAC_EPOCH
        for s, e, b in con.execute("select ZSTARTDATE, ZENDDATE, ZVALUESTRING from ZOBJECT where ZSTREAMNAME='/app/usage' and ZSTARTDATE>? order by ZSTARTDATE", (since,)):
            if b and s is not None:
                out.append((datetime.fromtimestamp(s + MAC_EPOCH), max(0.0, (e or s) - s), b))
        con.close()
    except sqlite3.Error:
        pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def usage_today(now=None):
    """Today's app usage from Screen Time (the 04:00-04:00 day): ({bundle: seconds} without system noise, readable). readable is False when the database can't be read."""
    now = now or datetime.now()
    src = os.environ.get('ZUKA_KNOWLEDGEC') or os.path.join(HOME, 'Library/Application Support/Knowledge/knowledgeC.db')
    rows = app_usage(2)
    per = collections.Counter()
    for st, secs, b in rows:
        if _day(st) == _day(now) and b.lower() not in IGNORE_BUNDLES: per[b] += secs
    return dict(per), bool(rows) or os.path.exists(src)


def today_tasks(now=None):
    """What was asked today (the 04:00-04:00 day) from Zuka's own log: [(request text, request type or None)], oldest first, minus cancelled ones."""
    now = now or datetime.now()
    return [(r['task'].strip(), req_type(_norm(r['task']))) for r in read_log() if _day(r['ts']) == _day(now) and r.get('status') != 'cancelled']


def display_intervals(days=WINDOW_DAYS):
    """[(on, off)] from pmset -g log (Display turned on/off, Wake, Entering Sleep)."""
    fx = os.environ.get('ZUKA_PMSET_FILE')
    if fx:
        try: text = open(fx).read()
        except OSError: return []
    else:
        try: text = _run(['/usr/bin/pmset', '-g', 'log'], 90).stdout
        except (OSError, subprocess.TimeoutExpired): return []
    since = datetime.now() - timedelta(days=days)
    on, out = None, []
    rx = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) [+-]\d{4} \S+\s+(.*)')
    for line in text.splitlines():
        m = rx.match(line)
        if not m: continue
        ts = datetime.strptime(m[1], '%Y-%m-%d %H:%M:%S')
        if ts < since: continue
        msg = m[2]
        if 'Display is turned on' in msg or msg.startswith('Wake from'):
            if on is None: on = ts
        elif 'Display is turned off' in msg or msg.startswith('Entering Sleep'):
            if on is not None and ts > on:
                out.append((on, min(ts, on + timedelta(hours=14))))
            on = None
    return out


def _day(ts): return (ts - timedelta(hours=DAY_START)).date()


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def active_hours(usage, intervals):
    """Per weekday (0=Mon): first/last activity (clock hours, may pass 24) and how often each hour is active."""
    secs_in = collections.Counter()   # absolute hour slot -> seconds of foreground use / display-on
    def spread(a, b, w):
        h = a.replace(minute=0, second=0, microsecond=0)
        while h < b:
            lo, hi = max(a, h), min(b, h + timedelta(hours=1))
            if hi > lo: secs_in[h] += (hi - lo).total_seconds() * w
            h += timedelta(hours=1)
    for ts, secs, b in usage:
        if b not in IGNORE_BUNDLES and secs > 0: spread(ts, ts + timedelta(seconds=min(secs, 4 * 3600)), 1)
    for a, b in intervals: spread(a, b, 0.4)   # display-on counts less than real use
    days = collections.defaultdict(set)
    for h, sec in secs_in.items():
        if sec >= 180: days[_day(h)].add(h)
    per = collections.defaultdict(list)   # weekday -> [(first, last, set(hours))]
    for d, hs in days.items():
        if len(hs) < 2: continue
        rel = sorted(((h - datetime.combine(d, datetime.min.time())).total_seconds() / 3600) for h in hs)
        per[d.weekday()].append((rel[0], rel[-1] + 1, {int(x) % 24 for x in rel}))
    out = {}
    for wd, rows in per.items():
        n = len(rows)
        out[str(wd)] = {'days': n, 'first': round(_median([r[0] for r in rows]), 1), 'last': round(_median([r[1] for r in rows]), 1),
                        'hours': [round(sum(1 for r in rows if h in r[2]) / n, 2) for h in range(24)]}
    return out


def suggested_checkins(active):
    """First activity +1h, mid, last -1h (report only; the LaunchAgent is not rewritten)."""
    def fmt(x):
        x = max(8.0, min(x, 22.5)); return f'{int(x):02d}:{int(round((x - int(x)) * 60 / 5) * 5) % 60:02d}'
    out = {}
    for wd, a in active.items():
        if a['days'] < 2: continue
        f, l = a['first'], a['last']
        if l - f < 3: continue
        out[wd] = [fmt(f + 1), fmt((f + l) / 2), fmt(l - 1)]
    allf = [a['first'] for a in active.values() if a['days'] >= 2]
    alll = [a['last'] for a in active.values() if a['days'] >= 2]
    res = {'byWeekday': out}
    if allf:
        f, l = _median(allf), _median(alll)
        res['all'] = [fmt(f + 1), fmt((f + l) / 2), fmt(l - 1)]
    return res


def apps_by_hour(usage):
    h = collections.defaultdict(collections.Counter)
    for ts, secs, b in usage:
        if b in IGNORE_BUNDLES: continue
        h[ts.hour][b] += max(secs, 1) / 60
    return {str(k): [[b, round(m)] for b, m in c.most_common(3)] for k, c in sorted(h.items())}


def first_apps(usage):
    """Apps opened in the first 30 minutes of each day (counts of days)."""
    byday = collections.defaultdict(list)
    for ts, secs, b in usage:
        if b not in IGNORE_BUNDLES and ts.hour >= 0: byday[_day(ts)].append((ts, b))
    cnt, n = collections.Counter(), 0
    for d, evs in byday.items():
        evs.sort(); t0 = evs[0][0]; n += 1
        for b in {b for ts, b in evs if ts <= t0 + timedelta(minutes=30)}: cnt[b] += 1
    return {'days': n, 'apps': dict(cnt.most_common(12))}


_NAMES = {}


def app_name(bundle):
    """A bundle id -> the app's name, from the .app bundles on this Mac (None if not installed)."""
    if not _NAMES:
        for base in ('/Applications', '/System/Applications', '/System/Applications/Utilities', os.path.join(HOME, 'Applications'), '/Applications/Utilities'):
            try: items = os.listdir(base)
            except OSError: continue
            paths = [os.path.join(base, it) for it in items]
            paths += [os.path.join(p, x) for p in paths if os.path.isdir(p) and not p.endswith('.app') for x in (os.listdir(p) if os.access(p, os.R_OK) else [])]
            for full in paths:
                if not full.endswith('.app'): continue
                try:
                    with open(os.path.join(full, 'Contents/Info.plist'), 'rb') as f: bid = plistlib.load(f).get('CFBundleIdentifier')
                except (OSError, ValueError, plistlib.InvalidFileException): continue
                if bid: _NAMES.setdefault(bid.lower(), os.path.basename(full)[:-4])
    return _NAMES.get((bundle or '').lower())


# ------------------------------------------------------------------ requests, plays, contacts, aliases
def _play_query(n):
    if not n.startswith(('play ', 'put on ')): return None
    q = re.sub(r'^(?:play|put on)\s+', '', n)
    q = re.sub(r'\s+(?:on|in|using|from)\s+(?:my\s+)?(?:youtube(?: music)?|apple music|the music app|music app|spotify)$', '', q)
    q = re.sub(r'^(?:me |the |some |a |my )+', '', q).strip()
    if not q or q in ('music', 'song', 'songs', 'something', 'anything', 'it', 'a song', 'next', 'next song') or len(q.split()) > 6: return None
    return q


def request_profile(rows):
    by_hour = collections.defaultdict(collections.Counter)
    types = collections.Counter(); contacts = collections.Counter(); plays = collections.Counter()
    play_hours = collections.defaultdict(collections.Counter)
    type_days = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in rows:
        n = _norm(r['task'])
        if not n: continue
        t = req_type(n)
        if t:
            by_hour[r['ts'].hour][t] += 1; types[t] += 1
            type_days[t][r['ts'].hour].add(r['ts'].date().isoformat())
        m = re.match(r'^(?:message|text|call|whatsapp|facetime|ring)\s+([a-z]+)\b', n)
        if m and m[1] not in ('me', 'my', 'him', 'her', 'them', 'someone', 'the', 'a', 'on', 'back'): contacts[m[1].title()] += 1   # a name only, never the message
        q = _play_query(n)
        if q and r.get('status') != 'cancelled': plays[q] += 1; play_hours[q][r['ts'].hour] += 1
    return {'byHour': {str(h): dict(c.most_common(5)) for h, c in sorted(by_hour.items())}, 'types': dict(types.most_common()),
            'typeHourDays': {t: {str(h): len(d) for h, d in hs.items() if len(d) >= 2} for t, hs in type_days.items()},
            'contacts': dict(contacts.most_common(8)), 'plays': plays, 'playHours': play_hours}


def learn_aliases(rows):
    """alias(original -> phrasing that worked instantly within 90 s). Needs >=2 sightings, or the two differ only by filler."""
    pairs = collections.Counter()
    for i, r1 in enumerate(rows):
        if not _needed_claude(r1): continue
        n1 = _norm(r1['task'])
        if not n1 or _is_content(n1) or len(n1.split()) > 9: continue
        for r2 in rows[i + 1:i + 4]:
            if (r2['ts'] - r1['ts']).total_seconds() > 90: break
            n2 = _norm(r2['task'])
            if not _free(r2) or not n2 or n2 == n1 or _is_content(n2) or len(n2) < 3: continue
            c1, c2 = set(_core(n1).split()), set(_core(n2).split())
            if not (req_type(n1) and req_type(n1) == req_type(n2)) and len(c1 & c2) / max(len(c1 | c2), 1) < 0.5: continue   # unrelated request: not a rephrase
            pairs[(n1, n2)] += 1
            break
    best = {}
    for (a, b), c in pairs.items():
        if c >= 2 or (_core(a) == _core(b) and _core(a)):
            if c > best.get(a, ('', 0))[1]: best[a] = (b, c)
            elif c == best.get(a, ('', 0))[1]: best[a] = ('', c)   # tie: ambiguous, skip
    return {a: b for a, (b, c) in best.items() if b}


# ------------------------------------------------------------------ music
LANG_PLAYLIST = {'edm': 'EDM', 'dance': 'EDM'}
MOODS = {   # mood -> (language/genre hints that fit it, query suffix, bucket it usually means)
    'work': (('hindi', 'english'), 'songs for work', 'afternoon'), 'focus': (('english', 'instrumental'), 'focus lofi', 'afternoon'),
    'study': (('english', 'instrumental'), 'focus lofi', 'afternoon'), 'gym': (('punjabi', 'edm', 'hip'), 'workout songs', 'morning'),
    'workout': (('punjabi', 'edm', 'hip'), 'workout songs', 'morning'), 'chill': (('hindi', 'english', 'acoustic'), 'chill songs', 'evening'),
    'relax': (('hindi', 'acoustic'), 'relaxing songs', 'evening'), 'sad': (('hindi',), 'sad songs', 'late night'),
    'party': (('punjabi', 'edm', 'dance'), 'party songs', 'evening'), 'sleep': (('acoustic', 'hindi'), 'sleep songs', 'late night'),
    'late night': ((), 'late night songs', 'late night'), 'night': ((), 'late night songs', 'late night'),
    'drive': (('punjabi', 'hindi'), 'drive songs', 'evening'), 'driving': (('punjabi', 'hindi'), 'drive songs', 'evening'),
    'morning': (('hindi', 'acoustic'), 'morning songs', 'morning'), 'cooking': (('hindi',), 'songs', 'evening'),
}
_NOISE = re.compile(r'\b(?:official|video|audio|lyrics?|lyrical|full|song|songs|hd|4k|8k|ultra|new|latest|hits?|mashup|nonstop|jukebox|remix|mix|live|visualizer|music)\b|[\(\[].*?[\)\]]|\b20\d\d\b', re.I)
_MUSIC_HINT = re.compile(r'\b(?:official|lyrics?|lyrical|song|songs|audio|mashup|jukebox|nonstop|remix|music video|full video|ft\.?|feat\.?)\b|\s-\s', re.I)


def _clean_title(t):
    t = re.sub(r'^\(\d+\)\s*', '', t or '')
    return re.sub(r'\s*-\s*YouTube(?: Music)?$', '', t).strip()


def apple_library():
    """Top artists/playlists/genres from the Music app via JXA. Hidden launch only if it isn't running; quit again after."""
    fx = os.environ.get('ZUKA_MUSIC_JSON')
    if fx:
        return _jload(fx, {})
    if not os.path.isdir('/System/Applications/Music.app') and not os.path.isdir('/Applications/Music.app'):
        return {}
    if not os.path.exists(os.path.join(HOME, 'Music/Music/Music Library.musiclibrary')) and not os.path.isdir(os.path.join(HOME, 'Music/Music')):
        return {}
    was = _run(['pgrep', '-x', 'Music'], 5).returncode == 0
    js = r"""
var m=Application('Music'),t=m.libraryPlaylists[0].tracks,o={tracks:[],playlists:[]};
var n=t.name(),a=t.artist(),p=t.playedCount(),g=t.genre(),f=[];
try{f=t.favorited()}catch(e){}
var d=[];try{d=t.playedDate()}catch(e){}
for(var i=0;i<n.length;i++){o.tracks.push([n[i],a[i],p[i]||0,g[i],f[i]?1:0,d[i]?d[i].getTime()/1000:0])}
var pl=m.userPlaylists,pn=pl.name(),sm=[];try{sm=pl.smart()}catch(e){}
for(var j=0;j<pn.length&&j<60;j++){if(sm[j])continue;var q=pl[j],ar={},pc=0,cnt=0;try{var qa=q.tracks.artist(),qp=q.tracks.playedCount();cnt=qa.length;for(var k=0;k<qa.length;k++){ar[qa[k]]=(ar[qa[k]]||0)+1;pc+=qp[k]||0}}catch(e){}
o.playlists.push({name:pn[j],count:cnt,plays:pc,artists:ar})}
JSON.stringify(o)"""
    try:
        if not was: _run(['/usr/bin/open', '-g', '-j', '-a', 'Music'], 20); time.sleep(4)
        r = _run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', js], 240)
        data = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        data = {}
    finally:
        if not was:
            try: _run(['/usr/bin/osascript', '-e', 'tell application "Music" to quit'], 10)
            except Exception: pass
    return data


def brave_titles(days=WINDOW_DAYS):
    """YouTube watch / YouTube Music page titles from the last 90 days: [(hour, title)] (copied history; nothing else is read)."""
    src = os.environ.get('ZUKA_BRAVE_HISTORY') or os.path.join(HOME, 'Library/Application Support/BraveSoftware/Brave-Browser/Default/History')
    if not os.path.exists(src): return []
    out = []
    try: dst, tmp = _copy_db(src)
    except OSError: return []
    try:
        con = sqlite3.connect(f'file:{dst}?mode=ro', uri=True)
        since = (time.time() - days * 86400 + 11644473600) * 1e6
        q = "select title, last_visit_time, url from urls where (url like '%youtube.com/watch%' or url like 'https://music.youtube.com/%') and last_visit_time>? and title!=''"
        for title, lv, url in con.execute(q, (since,)):
            ts = datetime.fromtimestamp(lv / 1e6 - 11644473600)
            out.append((ts, _clean_title(title), 'music.youtube.com' in url))
        con.close()
    except sqlite3.Error:
        pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _lang_of(text):
    t = (text or '').lower()
    for l in LANGS:
        if re.search(rf'\b{l}\b', t): return l
    return None


def _split_artists(a):
    return [x.strip() for x in re.split(r'\s*(?:,|&|\bfeat\.?|\bft\.?|\bx\b|\bwith\b)\s*', a, flags=re.I) if x.strip()]


def _canon(name, known):
    """The known artist a free-text name mentions (longest match), else None."""
    n = ' ' + _norm(name) + ' '
    best = None
    for k in known:
        kn = _norm(k)
        if len(kn) >= 4 and f' {kn} ' in n and (best is None or len(kn) > len(_norm(best))): best = k
    return best


def music_profile(rows, req, apple=None, titles=None, memory_text=''):
    apple = apple if apple is not None else {}
    titles = titles if titles is not None else []
    score = collections.Counter(); apple_plays = collections.Counter(); genres = collections.Counter()
    hours = collections.defaultdict(collections.Counter)    # bucket -> artist -> weight
    lang_artist = {}
    loved, recent = [], []
    # Apple Music
    tracks = apple.get('tracks') or []
    mx = max([t[2] for t in tracks] + [1])
    for name, artist, plays, genre, fav, last in tracks:
        if not artist: continue
        if genre: genres[genre] += max(plays, 1)
        if fav and len(loved) < 25: loved.append(f'{name} - {artist}')
        for one in _split_artists(artist):
            apple_plays[one] += plays
            score[one] += plays / mx * 10 + (2 if fav else 0)
            if last: hours[_bucket(datetime.fromtimestamp(last).hour)][one] += 1
    for t in sorted(tracks, key=lambda t: -(t[5] or 0))[:15]:
        if t[5]: recent.append(f'{t[0]} - {t[1]}')
    playlists = []
    for pl in apple.get('playlists') or []:
        playlists.append({'name': pl['name'], 'count': pl.get('count', 0), 'plays': pl.get('plays', 0)})
        lang = _lang_of(pl['name']) or ('edm' if re.search(r'\b(edm|dance)\b', pl['name'].lower()) else None)
        if lang:
            for a0, c in (pl.get('artists') or {}).items():
                for a in _split_artists(a0): lang_artist.setdefault(a, collections.Counter())[lang] += c
    known = set(apple_plays) | {a for a in (apple.get('knownArtists') or [])}
    # Zuka's own "play X" history (+ time of day)
    zplays = collections.Counter(); songs = collections.Counter()
    plays = collections.Counter(req['plays'])
    for k in _jload(_p('youtube-cache.json'), {}):   # songs/artists that have played before (YouTube cache keys)
        if isinstance(k, str) and k not in plays and _play_query('play ' + k): plays[k] = 1; req['playHours'].setdefault(k, collections.Counter())
    for q, c in plays.items():
        a = _canon(q, known)
        if a:
            zplays[a] += c; score[a] += c * 3
            for h, k in req['playHours'][q].items(): hours[_bucket(h)][a] += k
        else:
            songs[q] += c
            bits = [b.strip() for b in re.split(r'\band\b|,|&', re.sub(r'\bmix\b', '', q)) if b.strip()]
            if len(bits) > 1 or q.endswith(' mix') or (c >= 2 and len(q.split()) <= 3):   # "A and B mix" = artists; a lone title stays a song
                for b in bits:
                    zplays[b.title()] += c; score[b.title()] += c * 3
                    for h, k in req['playHours'][q].items(): hours[_bucket(h)][b.title()] += k
    # Brave: YouTube / YouTube Music titles -> an artist name only
    yt = collections.Counter(); ytlang = collections.Counter()
    unknown = collections.Counter()
    for ts, title, is_music in titles:
        if not _canon(title, known | set(zplays)) and (is_music or _MUSIC_HINT.search(title)):
            m = re.match(r'^([^-|–]{3,40}?)\s*[-–|]\s*\S', title)
            if m: unknown[_NOISE.sub('', m[1]).strip()] += 1
    for ts, title, is_music in titles:
        a = _canon(title, known | set(zplays))
        if not a and (is_music or _MUSIC_HINT.search(title)):
            m = re.match(r'^([^-|–]{3,40}?)\s*[-–|]\s*\S', title)
            cand = _NOISE.sub('', m[1]).strip() if m else ''
            if 3 <= len(cand) <= 30 and len(cand.split()) <= 3 and not re.search(r'\d', cand) and unknown[cand] >= 2: a = cand
        if a:
            yt[a] += 1; score[a] += 1; hours[_bucket(ts.hour)][a] += 1
            l = _lang_of(title)
            if l: ytlang[l] += 1; lang_artist.setdefault(a, collections.Counter())[l] += 1
    langs = collections.Counter()
    for a, w in score.items():
        c = lang_artist.get(a)
        if c: langs[c.most_common(1)[0][0]] += w
    tot = sum(langs.values()) or 1
    artists = [{'name': a, 'score': round(s, 1), 'lang': (lang_artist[a].most_common(1)[0][0] if a in lang_artist else None)} for a, s in score.most_common(20)]
    fav_pl = [p['name'] for p in sorted(playlists, key=lambda p: -(p['plays'] or 0)) if p['count']][:6]
    mem_pl = re.search(r'Playlists?:\s*(.+)', memory_text)
    if mem_pl and not fav_pl: fav_pl = [re.sub(r'[*_]', '', x).strip() for x in re.split(r',', mem_pl[1].split('\n')[0]) if x.strip()][:6]
    by_bucket = {b: [a for a, _ in c.most_common(5)] for b, c in hours.items() if c}
    hr = collections.Counter()
    for q, hs in req['playHours'].items():
        for h, k in hs.items(): hr[h] += k
    for ts, _, _ in titles: hr[ts.hour] += 1
    return {'topArtists': artists, 'languages': {l: round(c / tot * 100) for l, c in langs.most_common(6)}, 'genres': [g for g, _ in genres.most_common(8)],
            'playlists': [p['name'] for p in playlists][:30], 'favouritePlaylists': fav_pl, 'lovedSongs': loved, 'recentlyPlayed': recent,
            'zukaPlays': dict(songs.most_common(12)), 'zukaArtistPlays': dict(zplays.most_common(10)), 'listeningHours': {str(h): c for h, c in sorted(hr.items())},
            'moodsByTime': by_bucket, 'youtubeArtists': dict(yt.most_common(10)), 'hasAppleMusic': bool(tracks or playlists)}


# --- free music commands -------------------------------------------------------------
_PREFIX = r"(?:(?:hey |ok |okay |please |zuka |can you |could you |just )*)"
_FAV = re.compile(rf"^{_PREFIX}play (?:me )?(?:something|some ?thing|some music|a song|songs?|anything|music|a playlist) (?:i|that i|which i|id) (?:like|love|enjoy|usually listen to)$|^{_PREFIX}play (?:me )?my (?:music|favou?rites?|favou?rite (?:songs?|music)|songs|taste|usual|usual music|go to music|playlist)$|^{_PREFIX}play (?:my )?favou?rites?$|^{_PREFIX}play (?:something|some music|a song) (?:from )?my (?:taste|library|favou?rites?)$")
_MOOD = re.compile(rf"^{_PREFIX}play (?:me )?(?:something|some music|some songs?|a song|songs?|music|some|anything)? ?(?:for|to|while) (?:my |a |the |when i am |when im |when i m )?(?P<m>work(?:ing)?|focus(?:ing)?|study(?:ing)?|gym|workout|working out|chill(?:ing)?|relax(?:ing)?|sad|party|partying|sleep(?:ing)?|late night|night|driv(?:e|ing)|morning|cooking)(?: time| session| vibes?| mood| music| songs?)?$|^{_PREFIX}play (?:me )?(?:some |something |a )?(?P<m2>chill|relax(?:ing)?|sad|party|gym|workout|focus|sleep|late night|drive|driving|morning|study|work) (?:music|songs?|vibes?|playlist|mood)$|^{_PREFIX}play (?:me )?(?:something |some )(?P<m3>chill|sad|relaxing|energetic|upbeat)$")
_LANG = re.compile(rf"^{_PREFIX}play (?:me )?(?:some |something |a few )?(?P<l>[a-z]+)(?: songs?| music| tracks| playlist| hits| gaane| gane)?$")
_NEW = re.compile(rf"^{_PREFIX}play (?:me )?(?:something|some music|a song|songs?|some songs?) (?:new|fresh|different)(?: (?:like|for|from|based on) (?:my )?(?:taste|music|library|favou?rites?|what i like))?$|^{_PREFIX}play (?:something |some music |songs? )?(?:new )?like my (?:taste|music|library)$|^{_PREFIX}play (?:me )?something (?:i (?:have not|havent|haven t|have n t) (?:heard|played)|i might like)$")


def _habits(): return _jload(_habits_path(), {})


def _state():
    return _jload(_p('zuka-learn-state.json'), {})


def _recent_picks(): return _state().get('picks', [])


def _remember_pick(key):
    s = _state(); picks = (s.get('picks') or [])[-12:] + [key]; s['picks'] = picks[-12:]
    try: _jsave(_p('zuka-learn-state.json'), s)
    except OSError: pass


def _pick_artist(artists, avoid=()):
    for a in artists:
        if a not in avoid: return a
    return artists[0] if artists else None


def music_pick(request, habits=None):
    """A pick for a free "play ..." taste request: {'kind': 'apple'|'youtube', 'target', 'say'} or None (not one of these, or no taste known yet)."""
    n = _norm(request)
    if not n.startswith(('play', 'hey play', 'ok play', 'okay play', 'please play', 'zuka play', 'can you play', 'could you play', 'just play')): return None
    m = (habits if habits is not None else _habits()).get('music') or {}
    top = [a['name'] for a in m.get('topArtists', [])]
    if not top: return None
    recent = _recent_picks()
    pls = m.get('playlists', [])
    favpl = [p for p in m.get('favouritePlaylists', []) if p in pls]
    byb = m.get('moodsByTime', {})
    lang_of = {a['name']: a.get('lang') for a in m.get('topArtists', [])}

    def yt(query, say): return {'kind': 'youtube', 'target': query, 'say': say}
    def am(name): return {'kind': 'apple', 'target': name, 'say': f'Playing {name} in Apple Music'}
    def mix(artists): return f"{artists[0]} and {artists[1]} mix" if len(artists) > 1 else f'{artists[0]} mix'

    if _FAV.match(n):
        avoid = {r for r in recent}
        pl = next((p for p in favpl if 'p:' + p not in avoid), None)
        if pl: _remember_pick('p:' + pl); return am(pl)
        a = _pick_artist(top[:5], {r[2:] for r in recent if r.startswith('a:')}); _remember_pick('a:' + a)
        return yt(f'{a} mix', f'Putting on your {a} mix')
    mm = _MOOD.match(n)
    if mm:
        mood = (mm.group('m') or mm.group('m2') or mm.group('m3') or '').strip()
        mood = {'working': 'work', 'focusing': 'focus', 'studying': 'study', 'working out': 'workout', 'chilling': 'chill', 'relaxing': 'relax', 'partying': 'party',
                'sleeping': 'sleep', 'energetic': 'party', 'upbeat': 'party'}.get(mood, mood)
        mood = 'drive' if mood.startswith('driv') else mood
        hints, suffix, bucket = MOODS.get(mood, ((), 'songs', 'evening'))
        pl = next((p for p in pls if mood in p.lower()), None)
        if pl: return am(pl)
        pool = [a for a in byb.get(bucket, []) if a in top] or top
        fit = [a for a in pool if (lang_of.get(a) or '') in hints] or [a for a in top if (lang_of.get(a) or '') in hints] or pool
        a = _pick_artist(fit[:4], {r[2:] for r in recent if r.startswith('a:')}); _remember_pick('a:' + a)
        return yt(f'{a} {suffix}', f'Putting on some {a} for {mood}')
    nm = _NEW.match(n)
    if nm:
        seen = {x.title() for x in (m.get('zukaArtistPlays') or {})} | set(m.get('youtubeArtists', {}))
        fresh = [a for a in top[1:12] if a not in seen] or top[3:12] or top
        a = _pick_artist(fresh, {r[2:] for r in recent if r.startswith('a:')}); _remember_pick('a:' + a)
        return yt(f'{a} songs you may not have heard', f'Trying something new from {a}')
    lm = _LANG.match(n)
    if lm and lm.group('l') in LANGS:
        lang = lm.group('l')
        pl = next((p for p in pls if _lang_of(p) == lang), None)
        if pl: return am(pl)
        arts = [a for a in top if lang_of.get(a) == lang]
        if arts: return yt(mix(arts[:2]), f'Putting on {lang.title()} songs')
        return yt(f'{lang} songs mix', f'Putting on {lang.title()} songs')
    return None


def _play_pick(pick):
    """Play it: Apple Music playlist through the Music app, else YouTube through atticus.youtube_play (not reimplemented)."""
    if pick['kind'] == 'apple':
        name = pick['target'].replace('\\', '').replace('"', '')
        script = 'tell application "Music"\nset r to (every playlist whose name is "%s")\nif (count of r) = 0 then return "none"\nplay (item 1 of r)\nreturn "ok"\nend tell' % name
        r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip() == 'ok': return pick['say'] + '.'
        return None
    at = sys.modules.get('atticus') or sys.modules.get('__main__')
    if not hasattr(at, 'youtube_play'):
        try:
            import atticus as at
        except Exception:
            return None
    said = at.youtube_play(pick['target'])
    return said or None


def alias(t):
    """Learned phrasing -> the phrasing that works (t is already normalised). Free taste-music requests are played here and answered via SAID."""
    try:
        if not isinstance(t, str) or not t: return t
        a = (_habits().get('aliases') or {}).get(t)
        if isinstance(a, str) and a: t = a
        if 'play' in t:
            pick = music_pick(t)
            if pick:
                said = _play_pick(pick)
                if said: return SAID + said
        return t
    except Exception:
        return t


# ------------------------------------------------------------------ preferences
def update_prefs(habits, usage_first, dry=False):
    """Merge learned music / startDay.apps / keepOpen into workflow.json: only unset or previously learned keys, never hand-set ones."""
    wf = _jload(_workflow_path(), {})
    learned = dict(habits.get('learned') or {})
    changes = []
    defaults = {'music': 'top hits mix', 'keepOpen': ['Claude']}

    def settable(key, cur, default):
        return cur in (None, '', [], default) or (key in learned and learned[key] == cur)

    # music
    arts = [a['name'] for a in (habits.get('music') or {}).get('topArtists', [])][:2]
    if arts:
        new = f'{arts[0]} and {arts[1]} mix' if len(arts) > 1 else f'{arts[0]} mix'
        cur = wf.get('music')
        if new != cur and settable('music', cur, defaults['music']):
            wf['music'] = new; learned['music'] = new; changes.append(f"music: {cur!r} -> {new!r}")
        elif new != cur: changes.append(f"music: kept your {cur!r} (set by you)")
    # startDay.apps
    n = usage_first.get('days', 0)
    cand = [b for b, c in usage_first.get('apps', {}).items() if n >= 3 and c / n >= 0.6 and b.lower() not in KEEP_OPEN_SKIP and b.lower() != 'com.anthropic.claudefordesktop']
    names = [x for x in (app_name(b) for b in cand) if x][:3]
    sd = wf.get('startDay') if isinstance(wf.get('startDay'), dict) else {}
    cur = sd.get('apps')
    if names and names != cur:
        if settable('startDay.apps', cur, None):
            wf['startDay'] = {**sd, 'apps': names}; learned['startDay.apps'] = names; changes.append(f"startDay.apps: {cur!r} -> {names!r}")
        else: changes.append(f"startDay.apps: kept your {cur!r} (set by you)")
    # keepOpen hints: apps open in >= 50% of the active days (Claude + browsers stay)
    cnt = usage_first.get('stayDays', {}); nd = usage_first.get('days', 0)
    keep = [x for x in (app_name(b) for b, c in cnt.items() if nd >= 3 and c / nd >= 0.5 and b.lower() not in IGNORE_BUNDLES) if x]
    if keep:
        new = list(dict.fromkeys(['Claude'] + keep))[:6]
        cur = wf.get('keepOpen')
        if new != cur and settable('keepOpen', cur, defaults['keepOpen']):
            wf['keepOpen'] = new; learned['keepOpen'] = new; changes.append(f"keepOpen: {cur!r} -> {new!r}")
        elif new != cur: changes.append(f"keepOpen: kept your {cur!r} (set by you)")
    habits['learned'] = learned
    if not dry and any('->' in c for c in changes):
        _jsave(_workflow_path(), wf)
    return changes


# ------------------------------------------------------------------ learn
def _stay_days(usage):
    byday = collections.defaultdict(set)
    for ts, secs, b in usage:
        if secs >= 600: byday[_day(ts)].add(b)   # used for at least 10 minutes in a go
    cnt = collections.Counter()
    for bs in byday.values(): cnt.update(bs)
    return dict(cnt.most_common(15))


def learn(dry=False):
    rows = read_log()
    usage = app_usage(); intervals = display_intervals()
    active = active_hours(usage, intervals)
    req = request_profile(rows)
    fa = first_apps(usage); fa['stayDays'] = _stay_days(usage)
    mem = ''
    md = _memory_dir()
    if md:
        try: mem = open(os.path.join(md, 'project-apple-music-library.md')).read()
        except OSError: pass
    old = _habits()
    music = music_profile(rows, req, apple_library(), brave_titles(), mem)
    top_apps = collections.Counter()
    for ts, secs, b in usage:
        if b not in IGNORE_BUNDLES: top_apps[b] += secs / 3600
    habits = {'generated': datetime.now().strftime('%Y-%m-%d %H:%M'), 'version': 1, 'learned': old.get('learned', {}),
              'activeHours': active, 'topApps': [[b, round(h, 1)] for b, h in top_apps.most_common(10)], 'appsByHour': apps_by_hour(usage),
              'requestTypes': req['types'], 'requestsByHour': req['byHour'], 'typeHourDays': req['typeHourDays'], 'contacts': req['contacts'],
              'firstApps': {'days': fa['days'], 'apps': fa['apps']}, 'aliases': learn_aliases(rows), 'music': music,
              'suggestedCheckins': suggested_checkins(active), 'sources': {'requests': len(rows), 'usageEvents': len(usage), 'displayIntervals': len(intervals)}}
    habits['changes'] = update_prefs(habits, fa, dry=dry)
    if not dry: _jsave(_habits_path(), habits)
    return habits


def learn_daily():
    """From the first check-in of the day: learn at most once a day. Returns the habits, or None if already done today."""
    if _habits().get('generated', '')[:10] == datetime.now().strftime('%Y-%m-%d'): return None
    h = learn()
    try: gaps_report()
    except Exception: pass
    return h


# ------------------------------------------------------------------ suggestions
def in_call():
    """A call app is running or the mic is held by another app."""
    try:
        if _run(['/usr/bin/pgrep', '-x', 'CptHost|FaceTime|MSTeams|Microsoft Teams|zoom.us|Slack Helper \\(Plugin\\)'], 3).stdout.strip(): return True
    except Exception: pass
    try:
        out = _run(['/usr/bin/pmset', '-g', 'assertions'], 5).stdout
        if re.search(r'(?i)(?:audio-in|microphone).*', out) and re.search(r'(?i)pid \d+\((?!coreaudiod|Atticus|Wavelength)[^)]*\).*(?:input|mic)', out): return True
    except Exception: pass
    return False


def screen_locked():
    try:
        out = subprocess.run(['/usr/sbin/ioreg', '-n', 'Root', '-d1', '-a'], capture_output=True, timeout=5).stdout
        users = plistlib.loads(out)[0].get('IOConsoleUsers') or []
        return any(u.get('CGSSessionScreenIsLocked') for u in users)
    except Exception:
        return False


def suggestion(now=None, record=True):
    """One short spoken proactive line for this moment, or None. Max 3 a day, never the same twice, never during calls / locked screen."""
    now = now or datetime.now()
    h = _habits()
    if not h: return None
    st = _jload(_p('suggestions.json'), {})
    day = now.date().isoformat()
    given = st.get('given', []) if st.get('date') == day else []
    if len(given) >= 3: return None
    if in_call() or screen_locked(): return None
    cands = []
    hour = now.hour
    for t, hs in (h.get('typeHourDays') or {}).items():
        if hs.get(str(hour), 0) >= 3 and t in ('clickup check', 'calendar', 'weather', 'reminders'):
            subj = next((s for n, _, s in TYPES if n == t), None)
            if subj: cands.append((f'type:{t}', f"It's around when you {subj.replace('check ', 'check ', 1)} - want me to look?" if t != 'reminders' else "It's around when you set reminders - want me to set one?"))
    act = (h.get('activeHours') or {}).get(str(now.weekday())) or {}
    first = act.get('first')
    if first is not None:
        hr = now.hour + now.minute / 60 + (24 if now.hour < DAY_START else 0)
        if first - 0.25 <= hr <= first + 1.5 and 4 <= now.hour <= 12: cands.append(('morning', 'Morning - want me to start your day?'))
    mus = h.get('music') or {}
    lh = mus.get('listeningHours') or {}
    if (now.hour >= 22 or now.hour < 3) and (mus.get('topArtists') or sum(lh.values()) >= 3):
        cands.append(('music-late', 'Want some music while you work?'))
    for key, line in cands:
        if key in [g[0] for g in given]: continue
        if len(given) < 3:
            if record:
                st = {'date': day, 'given': given + [[key, now.strftime('%H:%M')]]}
                try: _jsave(_p('suggestions.json'), st)
                except OSError: pass
            return line
    return None


# ------------------------------------------------------------------ gaps
def gaps_report(force=False):
    """Requests that still needed Claude but look mechanical (repeat >= 2, action verbs). Written for the developer."""
    rows = read_log()
    cnt = collections.Counter(); last = {}
    for r in rows:
        n = _norm(r['task'])
        if not n or _is_content(n) or not _needed_claude(r): continue
        if n.split()[0] not in ACTION_VERBS or len(n.split()) > 8: continue
        cnt[n] += 1; last[n] = r['ts']
    gaps = [(n, c) for n, c in cnt.most_common() if c >= 2]
    today = datetime.now().strftime('%Y-%m-%d')
    body = ['# Zuka gaps (free-looking requests that still needed Claude)', f'Generated {today}. Repeat count >= 2, action verbs only; no message contents.', '']
    body += [f'- {n}  (x{c}, last {last[n]:%Y-%m-%d})' for n, c in gaps] or ['- none this week']
    _write_text(_p('gaps.md'), '\n'.join(body) + '\n')
    md = _memory_dir()
    if md and (gaps or force):
        path = os.path.join(md, 'project-zuka-gaps.md')
        head = ('---\nname: project-zuka-gaps\ndescription: "Requests Zuka still sends to Claude that look mechanical (free-command gaps), dated log"\n'
                'metadata:\n  node_type: memory\n  type: project\n---\n\nWeekly gaps log from zuka_learn (newest last). Each line is a candidate for a new free command.\n')
        try:
            cur = open(path).read()
        except OSError:
            cur = head
        if f'## {today}' not in cur:
            cur = cur.rstrip('\n') + f'\n\n## {today}\n' + '\n'.join(f'- {n} (x{c})' for n, c in gaps[:15]) + '\n'
            _write_text(path, cur)
    return gaps


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f: f.write(text)


# ------------------------------------------------------------------ CLI
def summary(h):
    L = []
    aw = h.get('activeHours', {})
    names = 'Mon Tue Wed Thu Fri Sat Sun'.split()
    for wd in sorted(aw): L.append(f"  {names[int(wd)]}: first {aw[wd]['first']:.1f}h last {aw[wd]['last']:.1f}h ({aw[wd]['days']} days)")
    L.insert(0, 'ACTIVE HOURS (clock hours; >24 = after midnight)')
    L.append('TOP APPS (hours): ' + ', '.join(f"{app_name(b) or b} {x}" for b, x in h.get('topApps', [])[:8]))
    L.append('REQUEST TYPES: ' + ', '.join(f'{k} {v}' for k, v in h.get('requestTypes', {}).items()))
    L.append('REQUESTS BY HOUR: ' + '; '.join(f'{k}h {",".join(v)}' for k, v in h.get('requestsByHour', {}).items()))
    L.append('FIRST APPS: ' + ', '.join(f"{app_name(b) or b} {c}/{h['firstApps']['days']}" for b, c in h.get('firstApps', {}).get('apps', {}).items()))
    L.append('CONTACTS: ' + ', '.join(f'{k} {v}' for k, v in h.get('contacts', {}).items()))
    L.append('ALIASES: ' + (json.dumps(h.get('aliases'), ensure_ascii=False) if h.get('aliases') else 'none'))
    m = h.get('music', {})
    L.append('MUSIC top artists: ' + ', '.join(a['name'] for a in m.get('topArtists', [])))
    L.append('MUSIC languages %: ' + json.dumps(m.get('languages')) + '  genres: ' + ', '.join(m.get('genres', [])))
    L.append('MUSIC fav playlists: ' + ', '.join(m.get('favouritePlaylists', [])) + '  | loved: ' + str(len(m.get('lovedSongs', []))))
    L.append('MUSIC moods by time: ' + json.dumps(m.get('moodsByTime'), ensure_ascii=False))
    L.append('MUSIC listening hours: ' + json.dumps(m.get('listeningHours')))
    L.append('SUGGESTED CHECK-INS: ' + json.dumps(h.get('suggestedCheckins', {}).get('all')))
    L.append('CHANGES: ' + ('; '.join(h.get('changes', [])) or 'none'))
    return '\n'.join(L)


def main(argv):
    if '--learn' in argv:
        h = learn(dry='--dry' in argv)
        print(summary(h) if '--quiet' not in argv else 'ok')
    elif '--suggest' in argv:
        s = suggestion(record='--peek' not in argv)
        if s: print(s)
    elif '--gaps' in argv:
        for n, c in gaps_report(force=True): print(f'{c}x {n}')
    elif '--daily' in argv:
        learn_daily()
    elif '--summary' in argv:
        print(summary(_habits()))


if __name__ == '__main__':
    main(sys.argv[1:])
