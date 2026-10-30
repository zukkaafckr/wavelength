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


if __name__ == '__main__':
    unittest.main()
