"""Page reading in Chrome-family browsers: every reason code, with fake osascript answers (no menu is ever clicked here)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import atticus


class PageJs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for p in (mock.patch.object(atticus, 'DIR', self.dir), mock.patch.object(atticus, 'proc_of', lambda app: app),
                  mock.patch.object(atticus.time, 'sleep', lambda s: None), mock.patch.object(atticus, 'page_js_pref', return_value=False)):
            p.start(); self.addCleanup(p.stop)
        self.calls = []
        self.launch = mock.patch.object(atticus, 'launch_app', return_value=True); self.launched = self.launch.start(); self.addCleanup(self.launch.stop)

    def tearDown(self): shutil.rmtree(self.dir, ignore_errors=True)

    def fake(self, probe, *script):
        """probe: (rc, out, err) for the permission probe; script: the answers the menu script gives in turn (the last repeats)."""
        answers = list(script)
        def osa_run(src, *args, timeout=20):
            self.calls.append((src, args))
            if src.startswith('tell application "System Events" to count'): return probe
            if src.startswith('tell application') and 'make new window' in src: return (0, '', '')
            return answers.pop(0) if len(answers) > 1 else answers[0]
        return mock.patch.object(atticus, 'osa_run', osa_run)

    def menu_calls(self): return [a for s, a in self.calls if s == atticus.PAGE_JS_SCRIPT]

    def err(self):
        with open(os.path.join(self.dir, 'app.err')) as f: return f.read()

    OK = (0, '', '')

    def test_already_on_is_ok_and_clicks_once_at_most(self):
        with self.fake(self.OK, (0, 'on|Allow JavaScript from Apple Events', '')):
            r = atticus.page_js('Google Chrome')
        self.assertEqual((r['code'], r['ok']), ('ok', True)); self.assertEqual(len(self.menu_calls()), 1)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'app.err')))

    def test_clicked_and_verified_on(self):
        with self.fake(self.OK, (0, 'clicked|Allow JavaScript from Apple Events', '')):
            self.assertTrue(atticus.page_js('Google Chrome')['ok'])
        self.assertEqual(self.menu_calls()[0][1], '1')   # the click flag is only a request: the script clicks only when the mark is missing

    def test_read_only_never_asks_for_a_click(self):
        with self.fake(self.OK, (0, 'off|x', '')):
            r = atticus.page_js('Google Chrome', click=False)
        self.assertEqual(r['code'], 'off'); self.assertEqual({a[1] for a in self.menu_calls()}, {'0'})

    def test_script_never_clicks_when_already_on(self):
        s = atticus.PAGE_JS_SCRIPT   # the only click sits behind the "mark is missing" state
        self.assertIn('if state is "off" and doClick then\nclick m', s); self.assertEqual(s.count('click m'), 1)

    def test_accessibility_missing(self):
        with self.fake((1, '', 'execution error: Atticus is not allowed assistive access. (-25211)')):
            r = atticus.page_js('Google Chrome')
        self.assertEqual((r['code'], r['pane']), ('no-accessibility', 'ax')); self.assertEqual(self.menu_calls(), [])
        self.assertRegex(self.err(), r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d page-js Google Chrome: no-accessibility')

    def test_automation_missing(self):
        with self.fake((1, '', 'System Events got an error: Not authorized to send Apple events to System Events. (-1743)')):
            r = atticus.page_js('Google Chrome')
        self.assertEqual((r['code'], r['pane']), ('no-automation', 'auto')); self.assertIn('no-automation', self.err())

    def test_missing_permission_found_by_the_menu_script_too(self):
        with self.fake(self.OK, (1, '', 'not allowed assistive access (-1719)')):
            self.assertEqual(atticus.page_js('Google Chrome')['code'], 'no-accessibility')

    def test_permission_prompt_hangs(self):
        with self.fake((-9, '', 'timed out')): self.assertEqual(atticus.page_js('Google Chrome')['code'], 'timeout')

    def test_browser_closed_is_launched_then_works(self):
        with self.fake(self.OK, (0, 'not-running|', ''), (0, 'not-running|no menu bar yet', ''), (0, 'clicked|Allow JavaScript from Apple Events', '')):
            r = atticus.page_js('Google Chrome')
        self.assertTrue(r['ok']); self.launched.assert_called_once_with('Google Chrome')

    def test_browser_never_gets_a_menu_bar(self):
        with self.fake(self.OK, (0, 'not-running|', '')):
            r = atticus.page_js('Google Chrome')
        self.assertEqual(r['code'], 'not-running'); self.assertIn('opened', r['text'])

    def test_browser_cannot_be_opened(self):
        self.launched.return_value = False
        with self.fake(self.OK, (0, 'not-running|', '')): self.assertEqual(atticus.page_js('Google Chrome')['code'], 'not-running')
        self.assertIn('could not open', self.err())

    def test_managed_menu_missing_or_disabled(self):
        for out in ('managed|no Developer menu', 'managed|only the switch is disabled', 'managed|whole Developer menu is disabled'):
            with self.fake(self.OK, (0, out, '')):
                r = atticus.page_js('Google Chrome')
            self.assertEqual(r['code'], 'managed'); self.assertIn('organization', r['text']); self.assertIn('View > Developer > Allow JavaScript from Apple Events', r['hand'])

    def test_menu_item_not_found(self):
        with self.fake(self.OK, (0, 'no-item|Developer menu has no switch', '')): self.assertEqual(atticus.page_js('Google Chrome')['code'], 'no-item')

    def test_click_did_not_take_retries_once_with_the_app_in_front(self):
        with self.fake(self.OK, (0, 'off|x', '')):
            r = atticus.page_js('Google Chrome')
        self.assertEqual(r['code'], 'failed'); self.assertEqual([a[2] for a in self.menu_calls()], ['0', '0', '1'])

    def test_no_window_but_preferences_say_on(self):
        with self.fake(self.OK, (0, 'no-window|menus are disabled', '')), mock.patch.object(atticus, 'page_js_pref', return_value=True):
            r = atticus.page_js('Brave Browser', click=False)
        self.assertTrue(r['ok']); self.assertEqual(len(self.menu_calls()), 1)

    def test_no_window_opens_one_to_click(self):
        with self.fake(self.OK, (0, 'no-window|x', ''), (0, 'clicked|Allow', '')):
            r = atticus.page_js('Google Chrome')
        self.assertTrue(r['ok']); self.assertTrue(any('make new window' in s for s, _ in self.calls))

    def test_no_window_read_only_opens_nothing(self):
        with self.fake(self.OK, (0, 'no-window|x', '')):
            r = atticus.page_js('Google Chrome', click=False)
        self.assertEqual(r['code'], 'no-window'); self.assertFalse(any('make new window' in s for s, _ in self.calls))

    def test_unknown_script_error(self):
        with self.fake(self.OK, (1, '', "Can't get menu item 1")): self.assertEqual(atticus.page_js('Google Chrome')['code'], 'error')

    def test_allow_page_js_stays_a_yes_no_and_need_reports_the_reason(self):
        with self.fake((1, '', '(-1743)')):
            self.assertFalse(atticus.allow_page_js('Google Chrome'))
            with mock.patch.dict(os.environ, {'ATTICUS_ASK': self.dir}), mock.patch.object(atticus, 'pref', return_value=True), mock.patch.object(atticus, 'emit'):
                self.assertIn('Automation', atticus.need('page-js', app='Google Chrome', do=True))

    def test_cli_prints_json_and_exits_by_result(self):
        with self.fake((1, '', '(-25211)')), mock.patch.object(atticus.sys, 'argv', ['atticus.py', '--allow-js', 'Google Chrome']), mock.patch('builtins.print') as pr, self.assertRaises(SystemExit) as e:
            atticus.main()
        self.assertEqual(e.exception.code, 1); self.assertEqual(json.loads(pr.call_args[0][0])['code'], 'no-accessibility')

    def test_applescript_compiles(self):
        if not shutil.which('osacompile'): self.skipTest('no osacompile')
        out = os.path.join(self.dir, 'p.scpt')
        r = subprocess.run(['osacompile', '-e', atticus.PAGE_JS_SCRIPT, '-o', out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
