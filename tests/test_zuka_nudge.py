"""Zuka's chat nudges. Nothing here reads the Claude app, speaks, or notifies: every side effect is injected."""
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zuka_nudge as n  # noqa: E402

SIDEBAR = """Sidebar
Sam's budget notes
Sam's budget notes
More options for Sam's budget notes
Alex trip planning and booking for the long weekend in spring Awaiting input
Alex trip planning and booking for the long weekend in spring
Awaiting input
More options for Alex trip planning and booking for the long weekend in spring
Chris recipe ideas
Chris recipe ideas
Running
Chris recipe ideas Awaiting input
Awaiting input
More options for Chris recipe ideas
Alex trip planning and booking for the long weekend in spring Awaiting input
"""


class Parse(unittest.TestCase):
    def test_finds_rows_that_end_with_awaiting_input(self):
        self.assertEqual(n.parse_awaiting(SIDEBAR), ['Alex trip planning and booking for the long weekend in spring', 'Chris recipe ideas'])

    def test_bare_label_and_empty(self):
        self.assertEqual(n.parse_awaiting('Awaiting input\nRunning\n'), [])
        self.assertEqual(n.parse_awaiting(''), [])
        self.assertEqual(n.parse_awaiting(None), [])

    def test_short_title_six_words(self):
        self.assertEqual(n.short_title('Alex trip planning and booking for the long weekend'), 'Alex trip planning and booking for')
        self.assertEqual(n.short_title('Sam notes'), 'Sam notes')


class Timing(unittest.TestCase):
    def test_first_nudge_at_three_minutes(self):
        s, due = n.step({}, ['Sam'], 1000)
        self.assertEqual(due, [])
        s, due = n.step(s, ['Sam'], 1000 + 179)
        self.assertEqual(due, [])
        s, due = n.step(s, ['Sam'], 1000 + 180)
        self.assertEqual(due, ['Sam'])
        self.assertEqual(s['Sam']['count'], 1)

    def test_repeats_every_ten_minutes_capped_at_four(self):
        s, t, heard = {}, 0, []
        n.step(s, ['Sam'], 0)
        s, _ = n.step(s, ['Sam'], 0)
        for t in range(0, 20000, 60):
            s, due = n.step(s, ['Sam'], t)
            heard += [t] * len(due)
        self.assertEqual(len(heard), 4)
        self.assertEqual(heard[0], 180)
        self.assertTrue(all(b - a >= 600 for a, b in zip(heard, heard[1:])))
        self.assertEqual(heard[1] - heard[0], 600)

    def test_clears_when_no_longer_waiting_and_restarts(self):
        s, _ = n.step({}, ['Sam', 'Alex'], 0)
        s, due = n.step(s, ['Sam', 'Alex'], 200)
        self.assertEqual(due, ['Sam', 'Alex'])
        s, due = n.step(s, ['Alex'], 300)
        self.assertEqual(list(s), ['Alex'])
        s, due = n.step(s, ['Sam'], 400)   # back again: a fresh clock
        self.assertEqual((due, s['Sam']['count']), ([], 0))

    def test_chats_timed_independently(self):
        s, _ = n.step({}, ['Sam'], 0)
        s, due = n.step(s, ['Sam', 'Chris'], 190)
        self.assertEqual(due, ['Sam'])


class Run(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.st, self.gen, self.send = (os.path.join(d, x) for x in ('nudge.json', 'generate-pending.json', 'send-pending.json'))
        self.said, self.shown = [], []

    def go(self, now, titles=('Alex trip planning and booking for the long weekend',), idle=5, front='Brave Browser', **kw):
        return n.run(now=now, at_mac=idle, frontmost=front, read=lambda: None if titles is None else list(titles), speak=self.said.append,
                     notify=self.shown.append, state_path=self.st, generate_file=self.gen, send_file=self.send, **kw)

    def test_speaks_title_trimmed_once_waited_three_minutes_and_notifies_once(self):
        self.assertEqual(self.go(1000), [])
        lines = self.go(1000 + 181)
        self.assertEqual(lines, ['Alex trip planning and booking for, is waiting for your answer.'])
        self.assertEqual((self.said, len(self.shown)), (lines, 1))

    def test_away_from_mac_is_silent(self):
        self.go(0)
        self.assertEqual(self.go(500, idle=600), [])
        self.assertEqual(self.said, [])

    def test_claude_frontmost_is_silent(self):
        self.go(0)
        self.assertEqual(self.go(500, front='Claude'), [])
        self.assertEqual(self.said, [])
        self.assertEqual(len(self.go(501)), 1)   # he left Claude: it speaks

    def test_unreadable_app_is_silent_and_forgets_chats(self):
        self.go(0)
        self.assertEqual(self.go(500, titles=None), [])
        self.assertEqual(n.load_state(self.st), {})

    def test_partial_read_does_not_reset_clock(self):
        self.go(0)
        reads = iter([[], ['Sam']])
        n.run(now=100, at_mac=0, frontmost='', read=lambda: next(reads), speak=self.said.append, notify=self.shown.append,
              state_path=self.st, generate_file=self.gen, send_file=self.send)
        self.assertEqual(n.load_state(self.st)['Sam']['first'], 100)   # new chat title, own clock

    def test_chat_cleared_when_answered(self):
        self.go(0)
        self.go(200)
        self.assertEqual(self.go(300, titles=[]), [])
        self.assertEqual(n.load_state(self.st), {})

    def test_unexpired_generate_is_skipped_expired_is_nudged(self):
        import json
        with open(self.gen, 'w') as f:
            json.dump({'tab_key': 'x', 'button_text': 'Generate', 'expires': 5000}, f)
        self.assertEqual(self.go(4000, titles=[]), [])
        self.assertEqual(self.go(4500, titles=[]), [])
        self.assertEqual(self.go(5100, titles=[]), [])      # first seen after expiry
        lines = self.go(5100 + 200, titles=[])
        self.assertEqual(len(lines), 1)
        self.assertIn('generate', lines[0])

    def test_pending_send_is_skipped(self):
        import json
        with open(self.send, 'w') as f:
            json.dump({'at': 1}, f)
        with open(self.gen, 'w') as f:
            json.dump({'tab_key': 'x', 'button_text': 'Generate', 'expires': 1}, f)
        self.go(5000, titles=[])
        self.assertEqual(self.go(6000, titles=[]), [])


class Idle(unittest.TestCase):
    def test_idle_parse(self):
        out = mock.Mock(stdout='    | "HIDIdleTime" = 125000000000\n')
        with mock.patch.object(n.apps, '_run', return_value=out):
            self.assertEqual(n.idle_seconds(), 125)
        with mock.patch.object(n.apps, '_run', return_value=mock.Mock(stdout='')):
            self.assertIsNone(n.idle_seconds())


class Install(unittest.TestCase):
    def test_plist_every_two_minutes_not_at_load(self):
        home = tempfile.mkdtemp()
        with mock.patch.object(n.subprocess, 'run') as run:
            path = n.install_nudge(home=home)
        with open(path, 'rb') as f:
            p = plistlib.load(f)
        self.assertEqual((p['Label'], p['StartInterval'], p['RunAtLoad']), ('com.wavelength.nudge', 120, False))
        self.assertEqual(p['ProgramArguments'][1:], [str(Path(n.__file__).resolve()), '--run'])
        self.assertTrue(path.endswith('Library/LaunchAgents/com.wavelength.nudge.plist'))
        self.assertTrue(any('bootstrap' in c.args[0] for c in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
