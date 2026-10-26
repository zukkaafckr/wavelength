#!/usr/bin/env python3
"""Wavelength phone bridge: lets the Android app ask ONE tool-less Claude question on the owner's plan, through this Mac.

Run:   python3 phone_bridge.py            (serve on 0.0.0.0:8765)
Pair:  python3 phone_bridge.py --pair     (token, LAN IP, wavelength://pair?... string)
Agent: python3 phone_bridge.py --install-agent   (writes the LaunchAgent plist; does not load it)
Nothing else is ever run: no tools, no files, no URLs, no shell.
"""
import hmac, json, os, plistlib, re, secrets, shutil, subprocess, sys, tempfile, threading, time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
VERSION = 1
MAX_TEXT = 4000
MAX_BODY = 16384
RATE_LIMIT, RATE_WINDOW = 30, 60.0
AUTH_DELAY = 1.0
ASK_TIMEOUT = 60
LABEL = 'com.wavelength.phonebridge'


def home(): return os.path.expanduser('~')
def config_dir(): return os.environ.get('ATTICUS_DIR') or os.path.join(home(), '.config/atticus')
def token_path(): return os.path.join(config_dir(), 'phone-token')


def load_token():
    """Read the pairing token; create it (0600) on first use."""
    path = token_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    try:
        tok = Path(path).read_text().strip()
        if tok:
            os.chmod(path, 0o600)
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(24)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f: f.write(tok + '\n')
    os.chmod(path, 0o600)
    return tok


def _pref(key, default):
    try:
        with open(os.path.join(config_dir(), 'settings.json')) as f: return json.load(f).get(key, default)
    except (OSError, ValueError, AttributeError):
        return default


def _clean_name(value, default):
    value = re.sub(r'[^\w \-]', '', value).strip()[:31] if isinstance(value, str) else ''
    return value or default


def assistant_name(): return _clean_name(_pref('assistantName', 'Zuka'), 'Zuka')   # same rule as atticus.assistant_name()


def plan_size(usd):   # same buckets as atticus.plan_size()
    return 'a tiny' if usd < 0.003 else 'a small' if usd < 0.015 else 'a medium' if usd < 0.06 else 'a large'


def system_prompt(call):
    call = _clean_name(call, '')
    who = f'Call the user {call}.' if call else 'Do not call the user by any name.'
    return f'You are {assistant_name()}, a phone voice assistant. Answer in at most 2 short spoken sentences (under 35 words), leading with the answer. {who}'


def claude_bin():
    path = os.environ.get('ATTICUS_CLAUDE') or shutil.which('claude')
    if not path:
        extra = os.pathsep.join(os.path.join(home(), d) for d in ('.local/bin', '.claude/local', '.npm-global/bin')) + ':/opt/homebrew/bin:/usr/local/bin'
        path = shutil.which('claude', path=extra)
    return path or 'claude'


def claude_argv(call):
    return [claude_bin(), '-p', '--model', 'haiku', '--effort', 'low', '--system-prompt', system_prompt(call),
            '--tools', '', '--setting-sources', '', '--settings', '{"disableAllHooks":true}',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--disable-slash-commands',
            '--no-session-persistence', '--output-format', 'json']


def log_ask(text, reply, started, usd, usage):
    """Same log.jsonl the Mac app's usage view reads, tagged path: phone."""
    row = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'task': text, 'reply': reply, 'usd': round(usd, 5),
           'secs': round(time.time() - started, 1), 'steps': 0, 'ran': [], 'live': False, 'pics': 0, 'cursor': False,
           'model': 'haiku', 'path': 'phone', 'escalated': False, 'escalate_why': None, 'attempt_usd': [usd],
           'attempt_usage': [usage] if usage else [], 'status': 'completed'}
    try:
        os.makedirs(config_dir(), mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(config_dir(), 'log.jsonl'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try: os.write(fd, (json.dumps(row) + '\n').encode())
        finally: os.close(fd)
    except OSError:
        pass


class AskError(Exception):
    pass


def ask_claude(text, call):
    started = time.time()
    try:
        p = subprocess.run(claude_argv(call), input=text, capture_output=True, text=True, timeout=ASK_TIMEOUT,
                           cwd=tempfile.gettempdir())
    except subprocess.TimeoutExpired:
        raise AskError('timeout')
    except OSError:
        raise AskError('claude unavailable')
    try:
        res = json.loads(p.stdout)
    except ValueError:
        res = {}
    if p.returncode or not isinstance(res, dict) or res.get('is_error') or not isinstance(res.get('result'), str):
        raise AskError('claude failed')
    reply = res['result'].strip()
    usd = res.get('total_cost_usd') if isinstance(res.get('total_cost_usd'), (int, float)) else 0
    log_ask(text, reply, started, usd, {k: res[k] for k in ('usage', 'modelUsage') if isinstance(res.get(k), dict)})
    return reply, plan_size(usd)


class RateLimiter:
    def __init__(self, limit=RATE_LIMIT, window=RATE_WINDOW, clock=time.monotonic):
        self.limit, self.window, self.clock, self.hits, self.lock = limit, window, clock, defaultdict(deque), threading.Lock()

    def allow(self, ip):
        now = self.clock()
        with self.lock:
            q = self.hits[ip]
            while q and now - q[0] > self.window: q.popleft()
            if len(q) >= self.limit: return False
            q.append(now)
            return True


class Handler(BaseHTTPRequestHandler):
    server_version = 'Wavelength'
    protocol_version = 'HTTP/1.1'
    timeout = 30

    def log_message(self, *a): pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _gate(self):
        """Rate limit, then bearer auth. True when the request may proceed."""
        if not self.server.limiter.allow(self.client_address[0]):
            self._send(429, {'error': 'rate limit'}); return False
        given = self.headers.get('Authorization', '')
        want = 'Bearer ' + self.server.token
        if not hmac.compare_digest(given.encode(), want.encode()):
            time.sleep(self.server.auth_delay)
            self._send(401, {'error': 'unauthorized'}); return False
        return True

    def do_GET(self):
        if not self._gate(): return
        if self.path == '/health':
            return self._send(200, {'ok': True, 'name': assistant_name(), 'version': VERSION})
        self._send(404, {'error': 'not found'})

    def do_POST(self):
        if not self._gate(): return
        if self.path != '/ask': return self._send(404, {'error': 'not found'})
        try:
            n = int(self.headers.get('Content-Length', ''))
        except ValueError:
            return self._send(411, {'error': 'length required'})
        if n < 0 or n > MAX_BODY: return self._send(413, {'error': 'too large'})
        try:
            data = json.loads(self.rfile.read(n))
        except ValueError:
            return self._send(400, {'error': 'bad json'})
        text, call = (data.get('text'), data.get('call', '')) if isinstance(data, dict) else (None, '')
        if not isinstance(text, str) or not text.strip(): return self._send(400, {'error': 'text required'})
        if len(text) > MAX_TEXT: return self._send(413, {'error': 'text too long'})
        if not isinstance(call, str) or len(call) > 100: return self._send(400, {'error': 'bad call'})
        try:
            reply, usage = ask_claude(text, call)
        except AskError as e:
            return self._send(504 if str(e) == 'timeout' else 502, {'error': str(e)})
        self._send(200, {'reply': reply, 'usage': usage})


class Bridge(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, token, limiter=None, auth_delay=AUTH_DELAY):
        super().__init__(addr, Handler)
        self.token, self.limiter, self.auth_delay = token, limiter or RateLimiter(), auth_delay


def computer_name():
    try: return subprocess.run(['scutil', '--get', 'ComputerName'], capture_output=True, text=True, timeout=5).stdout.strip() or 'Mac'
    except (OSError, subprocess.SubprocessError): return 'Mac'


def lan_ip():
    try: return subprocess.run(['ipconfig', 'getifaddr', 'en0'], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError): return ''


def pair_lines(token=None, ip=None, port=PORT):
    token = token or load_token(); ip = lan_ip() if ip is None else ip
    return [f'token: {token}', f'host: {ip}', f'port: {port}', f'wavelength://pair?host={ip}&port={port}&token={token}']


def advertise(port=PORT):
    try:
        return subprocess.Popen(['dns-sd', '-R', f'Wavelength on {computer_name()}', '_wavelength._tcp', 'local', str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def agent_plist():
    log = os.path.join(config_dir(), 'phone-bridge.log')
    py = shutil.which('python3') or '/usr/bin/python3'
    return {'Label': LABEL, 'ProgramArguments': [py, os.path.abspath(__file__)], 'RunAtLoad': True, 'KeepAlive': True,
            'StandardOutPath': log, 'StandardErrorPath': log, 'WorkingDirectory': os.path.dirname(os.path.abspath(__file__)),
            'EnvironmentVariables': {'PATH': os.pathsep.join([os.path.join(home(), '.local/bin'), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin'])}}


def install_agent():
    """Write the LaunchAgent plist (does NOT load it). Returns its path."""
    path = os.path.join(home(), 'Library', 'LaunchAgents', LABEL + '.plist')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(config_dir(), mode=0o700, exist_ok=True)
    with open(path, 'wb') as f: plistlib.dump(agent_plist(), f)
    return path


def serve(port=PORT):
    token = load_token()
    srv = Bridge(('0.0.0.0', port), token)
    mdns = advertise(port)
    print(f'Wavelength phone bridge on 0.0.0.0:{port}', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        if mdns: mdns.terminate()


def main(argv):
    if '--pair' in argv: return print('\n'.join(pair_lines()))
    if '--install-agent' in argv: return print('wrote', install_agent(), '\nload with: launchctl load ' + install_agent())
    port = PORT
    if '--port' in argv: port = int(argv[argv.index('--port') + 1])
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    serve(port)


if __name__ == '__main__':
    main(sys.argv[1:])
