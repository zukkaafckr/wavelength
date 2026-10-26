import json, os, plistlib, stat, subprocess, sys, tempfile, threading, unittest, urllib.error, urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import phone_bridge as pb


class BridgeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {'ATTICUS_DIR': self.tmp, 'HOME': self.tmp})
        self.env.start()
        self.token = pb.load_token()
        self.srv = pb.Bridge(('127.0.0.1', 0), self.token, auth_delay=0.01)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.env.stop()

    def req(self, path, body=None, token='ok', method=None):
        r = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', method=method or ('POST' if body is not None else 'GET'),
                                   data=json.dumps(body).encode() if body is not None else None)
        t = self.token if token == 'ok' else token
        if t is not None: r.add_header('Authorization', 'Bearer ' + t)
        try:
            with urllib.request.urlopen(r) as resp: return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


def fake_run(stdout=None, rc=0):
    out = json.dumps({'result': 'Paris.', 'is_error': False, 'total_cost_usd': 0.001}) if stdout is None else stdout
    return mock.Mock(return_value=subprocess.CompletedProcess([], rc, out, ''))


class Tests(BridgeCase):
    def test_token_file(self):
        path = pb.token_path()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertGreaterEqual(len(self.token), 30)
        self.assertEqual(pb.load_token(), self.token)

    def test_auth(self):
        for t in (None, 'wrong'):
            self.assertEqual(self.req('/health', token=t)[0], 401)
        self.assertEqual(self.req('/ask', {'text': 'hi'}, token='wrong')[0], 401)

    def test_auth_delay_is_one_second_by_default(self):
        self.assertEqual(pb.AUTH_DELAY, 1.0)

    def test_health(self):
        self.assertEqual(self.req('/health'), (200, {'ok': True, 'name': 'Zuka', 'version': 1}))

    def test_rate_limit(self):
        self.srv.limiter = pb.RateLimiter(30)
        codes = [self.req('/health')[0] for _ in range(32)]
        self.assertEqual(codes[:30], [200] * 30); self.assertEqual(codes[30:], [429, 429])

    def test_rate_limiter_window(self):
        now = [0.0]; rl = pb.RateLimiter(2, 60, clock=lambda: now[0])
        self.assertTrue(rl.allow('a')); self.assertTrue(rl.allow('a')); self.assertFalse(rl.allow('a')); self.assertTrue(rl.allow('b'))
        now[0] = 61; self.assertTrue(rl.allow('a'))

    def test_ask(self):
        with mock.patch('phone_bridge.subprocess.run', fake_run()) as run:
            code, body = self.req('/ask', {'text': 'capital of France', 'call': 'J'})
        self.assertEqual((code, body), (200, {'reply': 'Paris.', 'usage': 'a tiny'}))
        argv = run.call_args[0][0]
        self.assertEqual(argv[argv.index('--tools') + 1], '')
        self.assertEqual(argv[argv.index('--model') + 1], 'haiku')
        self.assertEqual(argv[argv.index('--system-prompt') + 1],
                         'You are Zuka, a phone voice assistant. Answer in at most 2 short spoken sentences (under 35 words), leading with the answer. Call the user J.')
        self.assertNotIn('capital of France', argv)
        self.assertEqual(run.call_args[1]['input'], 'capital of France'); self.assertEqual(run.call_args[1]['timeout'], 60)
        self.assertNotIn('--dangerously-skip-permissions', argv); self.assertIn('--strict-mcp-config', argv)

    def test_ask_no_call_name(self):
        self.assertIn('Do not call the user by any name.', pb.system_prompt(''))

    def test_ask_logged_as_phone(self):
        with mock.patch('phone_bridge.subprocess.run', fake_run()): self.req('/ask', {'text': 'hi'})
        row = json.loads(open(os.path.join(self.tmp, 'log.jsonl')).read().splitlines()[-1])
        self.assertEqual((row['path'], row['model'], row['attempt_usd']), ('phone', 'haiku', [0.001]))

    def test_input_limits(self):
        with mock.patch('phone_bridge.subprocess.run', fake_run()) as run:
            self.assertEqual(self.req('/ask', {'text': 'x' * 4001})[0], 413)
            self.assertEqual(self.req('/ask', {'text': 'x' * 4000})[0], 200)
            self.assertEqual(self.req('/ask', {'text': ''})[0], 400)
            self.assertEqual(self.req('/ask', {'text': 5})[0], 400)
            self.assertEqual(self.req('/ask', {'text': 'a', 'call': 'x' * 200})[0], 400)
            self.assertEqual(self.req('/ask', ['x'])[0], 400)
            self.assertEqual(self.req('/ask', {'text': 'a' * 20000})[0], 413)
            self.assertEqual(self.req('/other', {'text': 'a'})[0], 404)
        self.assertEqual(run.call_count, 1)

    def test_claude_failure(self):
        with mock.patch('phone_bridge.subprocess.run', fake_run('nope', 1)):
            self.assertEqual(self.req('/ask', {'text': 'hi'})[0], 502)
        with mock.patch('phone_bridge.subprocess.run', side_effect=subprocess.TimeoutExpired('claude', 60)):
            self.assertEqual(self.req('/ask', {'text': 'hi'})[0], 504)

    def test_call_name_sanitised(self):
        self.assertNotIn('<', pb.system_prompt('<b>J; rm -rf /</b>').split('Call the user')[1][:12])

    def test_pair_output(self):
        lines = pb.pair_lines(token='T0K', ip='192.168.1.5')
        self.assertEqual(lines, ['token: T0K', 'host: 192.168.1.5', 'port: 8765', 'wavelength://pair?host=192.168.1.5&port=8765&token=T0K'])

    def test_agent_plist(self):
        path = pb.install_agent()
        self.assertEqual(path, os.path.join(self.tmp, 'Library/LaunchAgents/com.wavelength.phonebridge.plist'))
        d = plistlib.load(open(path, 'rb'))
        self.assertEqual(d['Label'], 'com.wavelength.phonebridge')
        self.assertTrue(d['RunAtLoad'] and d['KeepAlive'])
        self.assertTrue(d['ProgramArguments'][0].endswith('python3')); self.assertTrue(d['ProgramArguments'][1].endswith('phone_bridge.py'))
        self.assertEqual(d['StandardOutPath'], os.path.join(self.tmp, 'phone-bridge.log'))


if __name__ == '__main__':
    unittest.main()
