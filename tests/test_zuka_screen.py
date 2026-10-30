"""zuka_screen: routing, privacy denylist, masking, capping, empty text, offer-Claude paths. The Mac, the window and the model are faked."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zuka_commands as z  # noqa: E402
import zuka_screen as s  # noqa: E402

PHRASES = ["what's on my screen", 'what is on my screen', 'what am I looking at', 'explain this', 'summarise this page', 'summarize this page',
           'what does this error mean', 'help me with this', 'can you explain this page please', 'zuka what is on the screen',
           'tell me about this page', 'what does this say', "what's this error", 'read this to me', 'read this page out loud', 'read this out to me please']
NOT = ['play a song', 'open Brave', 'what is the weather', 'remind me tomorrow', 'read my WhatsApp', 'explain how photosynthesis works',
       'what is 2 plus 2', 'message Sam I am late', 'read the last message from Alex']


def win(app='Notes', title='Shopping list', text='Sam wants milk.\nAlex wants eggs.\nChris wants bread.', private=False, host=''):
    return {'app': app, 'title': title, 'host': host, 'text': text, 'private': private}


class Route(unittest.TestCase):
    def test_phrases_route(self):
        for p in PHRASES:
            self.assertIsNotNone(s.route(z._norm(p)), p)

    def test_others_do_not(self):
        for p in NOT:
            self.assertIsNone(s.route(z._norm(p)), p)

    def test_read_and_more(self):
        self.assertEqual(s.route('read this to me'), 'read')
        self.assertEqual(s.route('read more'), 'more')
        self.assertEqual(s.route('ask claude about this screen'), 'claude')

    def test_in_the_free_chain(self):
        with mock.patch.object(s, 'look', return_value=win()), mock.patch.object(s, 'ask_brain', return_value='A shopping list for Sam, Alex and Chris.'):
            for p in PHRASES[:6]:
                self.assertEqual(z.handle(z._norm(p), p), 'A shopping list for Sam, Alex and Chris.', p)

    def test_ask_claude_is_left_for_claude(self):
        self.assertIsNone(s.handle('ask claude about this screen'))


class Privacy(unittest.TestCase):
    def test_denied_apps(self):
        for a in ('1Password', 'Bitwarden', 'Keychain Access', 'Passwords', 'LastPass', 'KeePassXC'):
            self.assertTrue(s.denied(a), a)
        self.assertTrue(s.denied('System Settings', 'Passwords'))
        self.assertFalse(s.denied('System Settings', 'Wi-Fi'))
        self.assertFalse(s.denied('Notes', 'Shopping list'))

    def test_denied_pages(self):
        self.assertTrue(s.denied('Brave Browser', 'Sam - Online Banking'))
        self.assertTrue(s.denied('Safari', 'Checkout', ''))
        self.assertTrue(s.denied('Google Chrome', 'Home', 'www.paypal.com'))
        self.assertTrue(s.denied('Brave Browser', 'Home', 'netbanking.examplebank.com'))
        self.assertFalse(s.denied('Brave Browser', 'Alex on Chess', 'chess.example.org'))

    def test_denied_window_is_not_read(self):
        with mock.patch.object(s, 'front', return_value=('1Password', '')), mock.patch.object(s, 'read_app') as ra:
            d = s.look()
        self.assertTrue(d['private']); ra.assert_not_called()
        self.assertEqual(s.answer('what is on my screen', d), s.PRIVATE)

    def test_denied_host_found_after_read(self):
        with mock.patch.object(s, 'front', return_value=('Safari', '')), mock.patch.object(s, 'peek_browser', return_value=('www.paypal.com', 'Home')), \
                mock.patch.object(s, 'read_browser', return_value='Balance 5') as rb:
            d = s.look()
        self.assertTrue(d['private']); self.assertEqual(d['text'], ''); rb.assert_not_called()   # the page text is never even fetched

    def test_denied_window_title_in_a_native_app(self):
        with mock.patch.object(s, 'front', return_value=('Notes', '')), mock.patch.object(s, 'read_app', return_value=('Card number 1', 'Checkout')):
            d = s.look()
        self.assertTrue(d['private']); self.assertEqual(d['text'], '')

    def test_brain_never_called_when_private(self):
        with mock.patch.object(s, 'ask_brain') as b:
            s.answer('explain this', win(private=True))
        b.assert_not_called()


class Masking(unittest.TestCase):
    def test_masks(self):
        t = 'Hi Sam\nfiller\nPassword: hunter2\nnext line\nunrelated\ncard 4111 1111 1111 1111 ok\nkey sk-abcdefghijklmnop1234\nlong Zx9Kq2Lm8Pw4Rt6Yv1Bn3Cd5Fg7Hj0'
        m = s.mask(t)
        for bad in ('hunter2', 'next line', '4111', 'sk-abc', 'Zx9Kq2Lm8Pw4'):
            self.assertNotIn(bad, m)
        self.assertIn('Hi Sam', m)
        self.assertIn('card [hidden] ok', m)

    def test_plain_text_kept(self):
        self.assertEqual(s.mask('Alex has 3 apples and 12 pears.'), 'Alex has 3 apples and 12 pears.')

    def test_mask_applied_before_model(self):
        seen = {}
        def brain(app, title, text, q): seen['t'] = text; return 'ok.'
        with mock.patch.object(s, 'front', return_value=('Notes', '')), mock.patch.object(s, 'read_app', return_value=('Chris\npassword is abc\nfin', 'Notes')), mock.patch.object(s, 'ask_brain', side_effect=brain):
            s.handle('whats on my screen')
        self.assertNotIn('abc', seen['t'])


class Capping(unittest.TestCase):
    def test_cap_keeps_top_and_errors(self):
        body = '\n'.join(f'line {i} about Sam and Alex going to the market today' for i in range(400)) + '\nFATAL error: disk failed at the end'
        c = s.cap(body)
        self.assertLessEqual(len(c), s.CAP)
        self.assertTrue(c.startswith('line 0 '))
        self.assertIn('FATAL error: disk failed', c)

    def test_short_untouched(self):
        self.assertEqual(s.cap('hello\nworld'), 'hello\nworld')


class Answers(unittest.TestCase):
    def test_empty_text_offers_claude_without_calling_it(self):
        with mock.patch.object(s, 'ask_brain') as b:
            r = s.answer('explain this', win(text=''))
        b.assert_not_called()
        self.assertIn('image or a video', r); self.assertIn('ask Claude', r)

    def test_brain_unavailable_offers_claude(self):
        with mock.patch.object(s, 'ask_brain', return_value=None), mock.patch('zuka_chat.enabled', return_value=False):
            r = s.answer('explain this', win())
        self.assertIn('local brain', r); self.assertIn('ask Claude', r)

    def test_deep_ask_offers_claude(self):
        with mock.patch.object(s, 'ask_brain') as b:
            r = s.answer('help me write a reply to this', win())
        b.assert_not_called(); self.assertIn('ask Claude', r)

    def test_tidy_limits_and_fakes(self):
        self.assertEqual(s._tidy('It is a list. It has milk. It has eggs. It has bread.'), 'It is a list. It has milk. It has eggs.')
        self.assertEqual(s._tidy("I'll handle that for you."), '')
        self.assertEqual(s._tidy('It needs Claude.'), '')


class ReadAloud(unittest.TestCase):
    TEXT = 'Home\nMenu\nSign in\nSam went to the market this morning. Alex stayed home and cooked lunch for everyone.\nChris called later to say he was running late.\nShare\n' + \
           '\n'.join(f'Paragraph {i} says that the weather stayed fine all afternoon in town.' for i in range(30))

    def test_nav_stripped(self):
        b = s.main_text(self.TEXT)
        self.assertNotIn('Sign in', b); self.assertNotIn('Menu', b); self.assertIn('Sam went to the market', b)

    def test_chunks_and_more(self):
        cs = s.chunks(s.main_text(self.TEXT))
        self.assertGreater(len(cs), 3)
        self.assertTrue(all(len(c) <= 420 for c in cs))
        with mock.patch.object(s, 'look', return_value=win(text=self.TEXT)):
            first = s.handle('read this to me')
        self.assertIn('Say read more', first)
        self.assertIn('Paragraph', s.handle('read more'))

    def test_read_private_and_empty(self):
        with mock.patch.object(s, 'look', return_value=win(private=True)):
            self.assertEqual(s.handle('read this to me'), s.PRIVATE)
        with mock.patch.object(s, 'look', return_value=win(text='Home\nMenu')):
            self.assertEqual(s.handle('read this to me'), s.NO_TEXT)


class ReadPaths(unittest.TestCase):
    """Fall-through order bridge -> head -> full, hard time limits, and privacy before fetch. Everything is faked."""
    LONG = 'Sam went to the market this morning and bought milk, eggs and bread for the whole week. ' * 8

    def look(self, app, **kw):
        with mock.patch.object(s, 'front', return_value=(app, '')), mock.patch.object(s, 'peek_cdp', return_value=kw.get('cdp_peek')), \
                mock.patch.object(s, 'read_cdp', return_value=kw.get('cdp', '')), mock.patch.object(s, 'peek_browser', return_value=kw.get('peek', ('', ''))), \
                mock.patch.object(s, 'read_browser', return_value=kw.get('browser', '')) as rb, \
                mock.patch.object(s, 'read_app', side_effect=kw.get('app_reads', [('', '')])) as ra:
            d = s.look(deep=kw.get('deep', False))
        return d, rb, ra

    def test_browser_bridge_first(self):
        d, rb, ra = self.look('Brave Browser', peek=('chess.example.org', 'Chess'), browser=self.LONG)
        self.assertEqual(d['path'], 'bridge'); ra.assert_not_called()

    def test_browser_without_page_js_falls_to_head(self):
        d, rb, ra = self.look('Brave Browser', peek=('', ''), app_reads=[(self.LONG, 'Chess')])
        rb.assert_not_called(); self.assertEqual(d['path'], 'head'); self.assertEqual(ra.call_count, 1)

    def test_browser_denied_host_never_fetched_nor_read(self):
        d, rb, ra = self.look('Google Chrome', peek=('www.paypal.com', 'Home'), browser='x', app_reads=[('y', 'z')])
        self.assertTrue(d['private']); rb.assert_not_called(); ra.assert_not_called()

    def test_electron_bridge_when_on(self):
        d, rb, ra = self.look('ClickUp', cdp_peek=('app.clickup.com', 'Tasks'), cdp=self.LONG)
        self.assertEqual(d['path'], 'cdp'); ra.assert_not_called()

    def test_electron_bridge_off_uses_accessibility_and_never_restarts(self):
        with mock.patch('zuka_cdp.ensure_app') as ea, mock.patch('zuka_cdp.port_open', return_value=False):
            d, rb, ra = self.look('ClickUp', cdp_peek=None, app_reads=[(self.LONG, 'Tasks')])
        ea.assert_not_called(); self.assertEqual(d['path'], 'head')

    def test_electron_denied_title_not_fetched(self):
        with mock.patch.object(s, 'read_cdp') as rc:
            d, rb, ra = self.look('ClickUp', cdp_peek=('app.clickup.com', 'Payment settings'), cdp='secret')
        self.assertTrue(d['private'])

    def test_head_enough_skips_full(self):
        d, rb, ra = self.look('Finder', app_reads=[(self.LONG, 'Downloads')])
        self.assertEqual(ra.call_count, 1); self.assertEqual(d['path'], 'head')
        self.assertTrue(ra.call_args.kwargs.get('head'))

    def test_short_head_goes_to_full(self):
        d, rb, ra = self.look('Terminal', app_reads=[('ls', 'zsh'), (self.LONG, 'zsh')])
        self.assertEqual(ra.call_count, 2); self.assertEqual(d['path'], 'full')
        self.assertTrue(ra.call_args_list[0].kwargs.get('head')); self.assertFalse(ra.call_args_list[1].kwargs.get('head'))

    def test_read_this_goes_to_full(self):
        d, rb, ra = self.look('Finder', deep=True, app_reads=[(self.LONG, 'Downloads'), (self.LONG * 2, 'Downloads')])
        self.assertEqual(ra.call_count, 2); self.assertEqual(d['path'], 'full')

    def test_nothing_readable(self):
        d, rb, ra = self.look('Preview', app_reads=[('', ''), ('', '')])
        self.assertEqual(d['text'], ''); self.assertEqual(d['path'], '')
        self.assertIn('image or a video', s.answer('explain this', d))

    def test_private_title_on_head_drops_text_without_full_read(self):
        d, rb, ra = self.look('Notes', app_reads=[('Card number 1', 'Checkout'), ('more', 'Checkout')])
        self.assertTrue(d['private']); self.assertEqual(d['text'], ''); self.assertEqual(ra.call_count, 1)

    def test_timeouts_are_passed_and_short(self):
        calls = []
        def fake_hands(args, timeout=20, head=False):
            calls.append((timeout, head))
            import subprocess
            return subprocess.CompletedProcess(args, 0, '{"text":"hi","window":"w"}', '')
        with mock.patch('zuka_apps.hands', side_effect=fake_hands):
            s.read_app('Finder', head=True); s.read_app('Finder')
        self.assertEqual(calls, [(s.T_HEAD, True), (s.T_FULL, False)])
        self.assertLessEqual(s.T_HEAD, 3); self.assertLessEqual(s.T_PEEK, 3); self.assertLessEqual(s.T_TEXT, 4)

    def test_timed_out_read_is_empty_not_an_error(self):
        import subprocess
        with mock.patch('zuka_apps.hands', side_effect=subprocess.TimeoutExpired('x', 1)):
            self.assertEqual(s.read_app('Finder', head=True), ('', ''))

    def test_browser_osascript_failure_is_empty(self):
        with mock.patch.object(s, '_run', side_effect=OSError('x')):
            self.assertEqual(s.peek_browser('Safari'), ('', ''))

    def test_cdp_off_returns_none_without_connecting(self):
        with mock.patch('zuka_cdp.port_open', return_value=False), mock.patch('zuka_cdp.open_tab') as ot:
            self.assertIsNone(s.peek_cdp('ClickUp'))
        ot.assert_not_called()

    def test_masking_still_applies_on_every_path(self):
        d, rb, ra = self.look('ClickUp', cdp_peek=('app.clickup.com', 'Tasks'), cdp='Hello\napi key is abc\nfin ' + self.LONG)
        self.assertNotIn('abc', d['text'])


class Warm(unittest.TestCase):
    def test_answer_call_keeps_model_loaded_long(self):
        seen = {}
        class R:
            def __enter__(s_): return s_
            def __exit__(s_, *a): pass
            def read(s_): return b'{"message":{"content":"It is a list."}}'
        def op(req, timeout=0):
            import json as j
            seen['b'] = j.loads(req.data); return R()
        with mock.patch('zuka_chat.enabled', return_value=True), mock.patch('zuka_chat._up', return_value=True), \
                mock.patch('zuka_chat._touch'), mock.patch('urllib.request.urlopen', side_effect=op):
            s.ask_brain('Notes', 'List', 'Sam wants milk.', 'explain this')
        self.assertEqual(seen['b']['keep_alive'], '30m')

    def test_warm_sends_empty_prompt_and_quiet_when_off(self):
        seen = {}
        class R:
            def __enter__(s_): return s_
            def __exit__(s_, *a): pass
            def read(s_): return b'{}'
        def op(req, timeout=0):
            import json as j
            seen['b'] = j.loads(req.data); seen['u'] = req.full_url; return R()
        with mock.patch('zuka_chat.enabled', return_value=True), mock.patch('zuka_chat._up', return_value=True), \
                mock.patch('zuka_chat._touch'), mock.patch('urllib.request.urlopen', side_effect=op):
            self.assertTrue(s.warm())
        self.assertEqual(seen['b']['prompt'], ''); self.assertEqual(seen['b']['keep_alive'], '30m'); self.assertTrue(seen['u'].endswith('/api/generate'))
        with mock.patch('zuka_chat.enabled', return_value=False), mock.patch('urllib.request.urlopen') as u:
            self.assertFalse(s.warm())
        u.assert_not_called()

    def test_no_warm_thread_under_tests(self):
        s._warm['at'] = 0
        with mock.patch('threading.Thread') as th:
            s._warm_async()
        th.assert_not_called()


if __name__ == '__main__':
    unittest.main()
