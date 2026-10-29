"""Zuka's page bridge: read and drive an installed Electron app (ClickUp, Slack, Discord...) through its own page code.

Free and local. Talks only to 127.0.0.1 over the Chrome DevTools Protocol, so no pixel clicks, no tokens, no browser. Stdlib only.
The app must be started with a debug port (`ensure_app` does that once, only if it is not already open that way).
"""
import base64, json, os, socket, struct, subprocess, time, urllib.request

PORTS = {'ClickUp': 9333}
_H = '127.0.0.1'


def _targets(port):
    try:
        with urllib.request.urlopen(f'http://{_H}:{port}/json', timeout=3) as r:
            return json.load(r)
    except Exception:
        return None


def port_open(app):
    return _targets(PORTS[app]) is not None


def ensure_app(app, wait=25):
    """Open the app with its page bridge on. If it is already running without the bridge, restart it once. -> True when ready."""
    port = PORTS[app]
    if port_open(app):
        return True
    if subprocess.run(['pgrep', '-x', app], capture_output=True).returncode == 0:
        subprocess.run(['osascript', '-e', f'tell application "{app}" to quit'], capture_output=True, timeout=15)
        for _ in range(15):
            if subprocess.run(['pgrep', '-x', app], capture_output=True).returncode:
                break
            time.sleep(1)
    subprocess.run(['open', '-g', '-a', app, '--args', f'--remote-debugging-port={port}',
                    f'--remote-allow-origins=http://{_H}:{port}'], capture_output=True, timeout=15)
    end = time.time() + wait
    while time.time() < end:
        if port_open(app) and page(app):
            return True
        time.sleep(1)
    return False


def page(app, needle=''):
    """The app's main page target (its ws url), or None."""
    for t in _targets(PORTS[app]) or []:
        if t.get('type') == 'page' and needle in t.get('url', '') and t.get('url', '').startswith('https://app.'):
            return t
    return None


class Tab:
    """One page over a minimal WebSocket client (no third-party packages)."""
    def __init__(self, ws_url):
        host, rest = ws_url[5:].split('/', 1)
        h, p = host.split(':')
        self.s = socket.create_connection((h, int(p)), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f'GET /{rest} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                        f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: http://{host}\r\n\r\n').encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += self.s.recv(1)
        if b' 101 ' not in buf.split(b'\r\n')[0]:
            raise OSError('page bridge refused')
        self.n = 0

    def _send(self, text):
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack('>H', n) if n < 65536
                               else bytes([0x80 | 127]) + struct.pack('>Q', n))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv_exact(self, n):
        out = b''
        while len(out) < n:
            c = self.s.recv(n - len(out))
            if not c:
                raise OSError('closed')
            out += c
        return out

    def _recv(self):
        msg = b''
        while True:
            b1, b2 = self._recv_exact(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack('>H', self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._recv_exact(8))[0]
            msg += self._recv_exact(n)
            if b1 & 0x80:
                return msg.decode('utf-8', 'replace')

    def call(self, method, **params):
        self.n += 1
        i = self.n
        self._send(json.dumps({'id': i, 'method': method, 'params': params}))
        while True:
            d = json.loads(self._recv())
            if d.get('id') == i:
                if 'error' in d:
                    raise OSError(d['error'].get('message', 'error'))
                return d.get('result', {})

    def js(self, expr):
        r = self.call('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        if r.get('exceptionDetails'):
            raise OSError(r['exceptionDetails'].get('text', 'script error'))
        return r.get('result', {}).get('value')

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def open_tab(app):
    t = page(app)
    return Tab(t['webSocketDebuggerUrl']) if t else None
