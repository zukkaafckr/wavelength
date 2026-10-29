"""Zuka's Brave actions and the Generate gate. Nothing here touches a real browser: js() is replaced by a fake page."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zuka_brave as b  # noqa: E402
import zuka_commands as z  # noqa: E402


class FakePage:
    """Counts presses; click label matching is done by the real injected script's inputs only (we record the label)."""
    def __init__(self, ok=True):
        self.ok, self.clicks = ok, []

    def __call__(self, expr, tab_key):
        self.clicks.append((tab_key, expr))
        return self.ok


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.object(b, 'PENDING_FILE', os.path.join(self.d, 'generate-pending.json'))
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(b, 'RESULT_FILE', os.path.join(self.d, 'generate-result.json'))
        q.start()
        self.addCleanup(q.stop)
        self.spoken = []

    def ask(self, **kw):
        return b.request_generate(kw.get('tab', 'studio.test'), kw.get('btn', 'Generate'), kw.get('cost', 'That costs 20 credits'), say=self.spoken.append)


class TestClick(Base):
    def test_risky_labels_refused(self):
        page = FakePage()
        with mock.patch.object(b, 'js', page):
            for lab in ('Generate', 'generate now', 'Create video', 'Submit', 'Buy now', 'Pay', 'Confirm', 'Send', 'Publish', 'Delete', 'Remove file'):
                self.assertFalse(b.click_text(lab, 'x'), lab)
            self.assertEqual(page.clicks, [])
            self.assertTrue(b.click_text('Save draft', 'x'))
            self.assertEqual(len(page.clicks), 1)


class TestGate(Base):
    def test_speaks_cost_and_stores_one(self):
        self.ask()
        self.assertEqual(self.spoken, ['That costs 20 credits. Say yes to generate.'])
        self.assertTrue(b.pending())

    def test_one_yes_one_press(self):
        page = FakePage()
        self.ask()
        with mock.patch.object(b, 'js', page):
            self.assertEqual(b.confirm_generate('yes'), 'Generating.')
            self.assertIsNone(b.confirm_generate('yes'))
            self.assertIsNone(b.confirm_generate('yes please'))
        self.assertEqual(len(page.clicks), 1)
        self.assertFalse(b.pending())

    def test_no_pending_means_no_press(self):
        page = FakePage()
        with mock.patch.object(b, 'js', page):
            self.assertIsNone(b.confirm_generate('yes'))
        self.assertEqual(page.clicks, [])

    def test_expiry(self):
        page = FakePage()
        self.ask()
        with mock.patch.object(b, 'js', page), mock.patch.object(b.time, 'time', return_value=time.time() + 121):
            self.assertIsNone(b.confirm_generate('yes'))
        self.assertEqual(page.clicks, [])
        self.assertFalse(os.path.exists(b.PENDING_FILE))

    def test_replace_keeps_only_latest(self):
        page = FakePage()
        self.ask(tab='first.test', btn='Generate')
        self.ask(tab='second.test', btn='Make video')
        with mock.patch.object(b, 'js', page):
            b.confirm_generate('yes')
        self.assertEqual(len(page.clicks), 1)
        self.assertEqual(page.clicks[0][0], 'second.test')
        self.assertIn('Make video', page.clicks[0][1])

    def test_cancel_words_clear(self):
        for w in ('no', 'cancel', 'stop', 'never mind'):
            page = FakePage()
            self.ask()
            with mock.patch.object(b, 'js', page):
                self.assertEqual(b.confirm_generate(w), 'Okay, not generating.')
                self.assertIsNone(b.confirm_generate('yes'))
            self.assertEqual(page.clicks, [])

    def test_unrelated_speech_keeps_pending(self):
        self.ask()
        self.assertIsNone(b.confirm_generate('what time is it'))
        self.assertTrue(b.pending())

    def test_missing_button_reported(self):
        self.ask()
        with mock.patch.object(b, 'js', FakePage(ok=False)):
            self.assertIn("couldn't find", b.confirm_generate('yes'))
        self.assertFalse(b.pending())


class TestRouting(Base):
    def test_yes_reaches_gate_and_message_gate_wins(self):
        page = FakePage()
        self.ask()
        with mock.patch.object(b, 'js', page), mock.patch('zuka_msg.confirm', return_value=None):
            self.assertIn('Generating', z.handle('yes'))
        self.assertEqual(len(page.clicks), 1)
        # a pending message send answers first; the generate press stays untouched
        page = FakePage()
        self.ask()
        with mock.patch.object(b, 'js', page), mock.patch('zuka_msg.confirm', return_value='Sent.'):
            self.assertEqual(z.handle('yes'), 'Sent.')
        self.assertEqual(page.clicks, [])
        self.assertTrue(b.pending())

    def test_plain_yes_without_pending_unchanged(self):
        with mock.patch('zuka_msg.confirm', return_value=None), mock.patch.object(b, 'js', FakePage()) as j:
            z.handle('yes')
        self.assertEqual(j.clicks if hasattr(j, 'clicks') else [], [])


class TestFiles(unittest.TestCase):
    def test_downloads_since_filters(self):
        d = tempfile.mkdtemp()
        old = os.path.join(d, 'old.png')
        Path(old).write_text('x')
        os.utime(old, (1000, 1000))
        for n in ('new.mp4', 'a.png', 'part.mp4.crdownload', 'x.part', '.hidden.png'):
            Path(d, n).write_text('x')
        os.mkdir(os.path.join(d, 'folder'))
        got = sorted(os.path.basename(p) for p in b.downloads_since(time.time() - 60, d))
        self.assertEqual(got, ['a.png', 'new.mp4'])

    def test_file_to_never_overwrites(self):
        src, dst = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), 'proj', 'sub')
        Path(src, 'clip.mp4').write_text('1')
        first = b.file_to([os.path.join(src, 'clip.mp4')], dst)
        Path(src, 'clip.mp4').write_text('2')
        second = b.file_to([os.path.join(src, 'clip.mp4')], dst)
        Path(src, 'clip.mp4').write_text('3')
        third = b.file_to([os.path.join(src, 'clip.mp4')], dst)
        self.assertEqual([os.path.basename(p) for p in first + second + third], ['clip.mp4', 'clip-2.mp4', 'clip-3.mp4'])
        self.assertEqual(Path(first[0]).read_text(), '1')
        self.assertFalse(os.path.exists(os.path.join(src, 'clip.mp4')))


class TestTabs(unittest.TestCase):
    def test_hosts_only(self):
        out = 'Sam board\thttps://boards.test/path?token=abc\nAlex\thttps://alex.test:8080/x#y\nblank\t\n'
        with mock.patch.object(z, '_osa', return_value=out):
            self.assertEqual(b.tabs(), [('Sam board', 'boards.test'), ('Alex', 'alex.test')])


class TestCli(Base):
    def setUp(self):
        super().setUp()
        q = mock.patch.object(b, 'RESULT_FILE', os.path.join(self.d, 'generate-result.json'))
        q.start()
        self.addCleanup(q.stop)

    def run_cli(self, *argv):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                code = b.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, buf.getvalue()

    def test_click_refusal_list_exit_1_no_js(self):
        page = FakePage()
        with mock.patch.object(b, 'js', page):
            for lab in ('Generate', 'Create', 'Send message', 'Delete', 'Pay now'):
                code, out = self.run_cli('click', '--tab', 'x', lab)
                self.assertEqual(code, 1)
                self.assertFalse(json.loads(out)['ok'])
            self.assertEqual(page.clicks, [])
            self.assertEqual(self.run_cli('click', '--tab', 'x', 'Save draft')[0], 0)

    def test_missing_required_args_exit_2(self):
        self.assertEqual(self.run_cli('fill', 'sel', 'text')[0], 2)
        self.assertEqual(self.run_cli('generate', '--tab', 'x')[0], 2)

    def test_tabs_and_read_json(self):
        with mock.patch.object(z, '_osa', return_value='Sam\thttps://a.test/p?q=1\n'):
            self.assertEqual(json.loads(self.run_cli('tabs')[1])['result'], [{'title': 'Sam', 'host': 'a.test'}])
        with mock.patch.object(b, 'js', return_value={'host': 'a.test', 'path': '/p', 'text': 'hi'}):
            code, out = self.run_cli('read', '--max', '5')
        self.assertEqual((code, json.loads(out)['result']['path']), (0, '/p'))

    def test_generate_without_yes_never_presses(self):
        page = FakePage()
        with mock.patch.object(b, 'js', page):
            r = b.cli_generate('studio.test', 'Generate', 'Costs 5 credits', wait=1, say=lambda l: None)
        self.assertEqual(r, 'not confirmed')
        self.assertEqual(page.clicks, [])

    def test_generate_with_yes_presses_once(self):
        import threading
        page = FakePage()
        def yes():
            for _ in range(50):
                if b.pending():
                    break
                time.sleep(0.05)
            b.confirm_generate('yes'); b.confirm_generate('yes')
        th = threading.Thread(target=yes); th.start()
        with mock.patch.object(b, 'js', page):
            r = b.cli_generate('studio.test', 'Generate', 'Costs 5 credits', wait=10, say=lambda l: None)
            th.join()
        self.assertEqual(r, 'pressed')
        self.assertEqual(len(page.clicks), 1)

    def test_generate_cancel_not_confirmed(self):
        import threading
        page = FakePage()
        def no():
            for _ in range(50):
                if b.pending():
                    break
                time.sleep(0.05)
            b.confirm_generate('no')
        th = threading.Thread(target=no); th.start()
        with mock.patch.object(b, 'js', page):
            r = b.cli_generate('studio.test', 'Generate', 'Costs 5 credits', wait=10, say=lambda l: None)
            th.join()
        self.assertEqual((r, page.clicks), ('not confirmed', []))


if __name__ == '__main__':
    unittest.main()
