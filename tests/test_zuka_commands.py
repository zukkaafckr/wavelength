import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zuka_commands as z  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dl = Path(self.tmp.name)
        p = mock.patch.object(z, 'DOWNLOADS', self.dl)
        p.start(); self.addCleanup(p.stop)
        self.calls = []

        def fake_run(args, timeout=10, inp=None):
            self.calls.append(args)
            return mock.Mock(returncode=0, stdout='', stderr='')
        q = mock.patch.object(z, '_run', fake_run)
        q.start(); self.addCleanup(q.stop)
        self.osa = mock.patch.object(z, '_osa', return_value='none')
        self.osa.start(); self.addCleanup(self.osa.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def mk(self, name, age=0):
        d = self.dl / name
        d.mkdir(parents=True)
        t = time.time() - age
        os.utime(d, (t, t))
        return d


class Matching(Base):
    def test_positive(self):
        for p in ['start my day', 'lets start work', 'good morning lets begin', 'morning setup']:
            with mock.patch.object(z, '_start_day', return_value='x'):
                self.assertEqual(z.handle(p), 'x', p)
        for p in ['edit mode', 'lets edit', "let's edit", 'editing time']:
            with mock.patch.object(z, '_edit_mode', return_value='x'):
                self.assertEqual(z.handle(p), 'x', p)
        for p in ['export check', 'check exports', 'how many exports']:
            with mock.patch.object(z, '_export_check', return_value='x'):
                self.assertEqual(z.handle(p), 'x', p)
        for p in ['any new messages', 'check whatsapp', 'any new mail', 'unread', 'anything new']:
            with mock.patch.object(z, '_unread', return_value='x'):
                self.assertEqual(z.handle(p), 'x', p)
        for p in ['next meeting', 'whats my next meeting', "what's my next meeting"]:
            with mock.patch.object(z, '_calendar', return_value='n') as c:
                self.assertEqual(z.handle(p), 'n', p)
                c.assert_called_with(False)
        for p in ['meetings today', 'whats on my calendar today', 'what meetings do i have today']:
            with mock.patch.object(z, '_calendar', return_value='n') as c:
                self.assertEqual(z.handle(p), 'n', p)
                c.assert_called_with(True)

    def test_open_tools(self):
        for k in z.TOOLS:
            with mock.patch.object(z, '_focus_or_open', return_value=True):
                self.assertEqual(z.handle(f'open {k}'), f"{z.TOOLS[k][0]}'s up.")

    def test_negative(self):
        for p in ['open premiere', 'open safari', 'how is the export going', 'what is the weather',
                  'send a whatsapp to mom', 'write a script for my day', 'new task', 'open', '']:
            self.assertIsNone(z.handle(p), p)


class Folders(Base):
    def test_new_task_default_type(self):
        r = z.handle('new task 473 copper story')
        stamp = datetime.now().strftime('%d%b%y').upper()
        d = self.dl / f'{stamp}_473_CopperStory_Video'
        self.assertTrue(d.is_dir())
        for s in z.SUBFOLDERS:
            self.assertTrue((d / s).is_dir(), s)
        self.assertEqual(r, 'Done. Task 473, Copper Story, is ready in Downloads.')
        self.assertIn(['open', str(d)], self.calls)

    def test_type_word(self):
        z.handle('create task 474 skeleton hooks hookiteration')
        z.handle('new task 475 pharmacy counter ugc')
        names = {p.name.split('_', 1)[1] for p in self.dl.iterdir()}
        self.assertIn('474_SkeletonHooks_HookIteration', names)
        self.assertIn('475_PharmacyCounter_UGC', names)

    def test_date_format(self):
        z.handle('new task folder 476 copper pipe scandal')
        n = next(self.dl.iterdir()).name
        self.assertRegex(n, r'^\d{2}[A-Z]{3}\d{2}_476_CopperPipeScandal_Video$')

    def test_exists(self):
        z.handle('new task 473 copper story')
        r = z.handle('new task 473 copper story')
        self.assertIn('already exists', r)
        self.assertEqual(len(list(self.dl.iterdir())), 1)

    def test_no_name(self):
        self.assertIn('call it', z.handle('new task 473 video'))


class Exports(Base):
    def test_counts(self):
        self.mk('20OCT26_469_Old_Video', age=1000)
        d = self.mk('23OCT26_472_LivingMetalScandal_Video')
        (d / '06_Exports/Premiere').mkdir(parents=True)
        (d / '06_Exports/Submagic').mkdir(parents=True)
        for i in range(5):
            (d / f'06_Exports/Premiere/a{i}.mp4').write_text('x')
        for i in range(3):
            (d / f'06_Exports/Submagic/b{i}.MOV').write_text('x')
        (d / '06_Exports/Submagic/notes.txt').write_text('x')
        self.assertEqual(z.handle('export check'), 'Task 472: 5 in Premiere, 3 in Submagic.')

    def test_missing(self):
        self.mk('23OCT26_472_X_Video')
        self.assertIn('no exports folders', z.handle('check exports'))

    def test_no_task(self):
        self.assertIn("can't find", z.handle('export check'))

    def test_newest_by_mtime(self):
        self.mk('20OCT26_469_A_Video', age=500)
        self.mk('21OCT26_470_B_Video', age=0)
        self.assertEqual(z._newest_task_folder().name, '21OCT26_470_B_Video')


class Titles(Base):
    def test_real_like(self):
        info = z._parse_titles(['Hydroh Bottle | Atria', 'Inbox (1,650) - alex.k@gmail.com - Gmail', '(58) WhatsApp'])
        self.assertEqual(info, {'whatsapp': 58, 'gmail': [('alex.k', 1650)]})
        self.assertEqual(z._unread_reply(info), '58 unread on WhatsApp, and 1,650 unread in your Gmail.')

    def test_multi_gmail(self):
        info = z._parse_titles(['Inbox (12) - jay@hoa.com - Gmail', 'Inbox (1,001) - ps@gmail.com - Gmail', '(3) WhatsApp'])
        r = z._unread_reply(info)
        self.assertIn('12 unread in jay', r)
        self.assertIn('1,001 unread in ps', r)
        self.assertIn('3 unread on WhatsApp', r)

    def test_missing_tabs(self):
        r = z._unread_reply(z._parse_titles(['(58) WhatsApp']))
        self.assertIn('say open gmail', r.lower())
        self.assertIn('Say open whatsapp', z._unread_reply(z._parse_titles(['Inbox (4) - a@b.com - Gmail'])))
        self.assertIn('Neither', z._unread_reply(z._parse_titles(['YouTube'])))

    def test_zero(self):
        info = z._parse_titles(['Inbox - a@b.com - Gmail', 'WhatsApp'])
        self.assertEqual(info, {'whatsapp': 0, 'gmail': [('a', 0)]})

    def test_handle_unread_uses_osa(self):
        with mock.patch.object(z, '_osa', return_value='(7) WhatsApp\nInbox (2) - x@y.com - Gmail\n'):
            self.assertEqual(z.handle('any new messages'), '7 unread on WhatsApp, and 2 unread in your Gmail.')


class Calendar(Base):
    def _patch(self, payload):
        return mock.patch.object(z, '_calendar_events', return_value=payload)

    def test_no_accounts(self):
        with self._patch({'events': [], 'calendars': []}):
            self.assertIn('Internet Accounts', z.handle('next meeting'))

    def test_need_permission(self):
        with self._patch({'need': 'calendar'}):
            self.assertIn('Calendar access', z.handle('next meeting'))

    def test_next_event(self):
        s = datetime.now().astimezone() + timedelta(minutes=25, seconds=20)
        ev = [{'title': 'Past', 'start': (s - timedelta(hours=3)).isoformat(), 'end': (s - timedelta(hours=2)).isoformat()},
              {'title': 'Creative review', 'start': s.isoformat(), 'end': (s + timedelta(hours=1)).isoformat()}]
        with self._patch({'events': ev, 'calendars': [{'id': '1'}]}):
            r = z.handle('whats my next meeting')
        self.assertIn('Next up: Creative review at', r)
        self.assertIn('in 25 minutes', r)

    def test_today_list(self):
        now = datetime.now().astimezone()
        ev = [{'title': f'M{i}', 'start': (now + timedelta(hours=i + 1)).isoformat(),
               'end': (now + timedelta(hours=i + 2)).isoformat()} for i in range(4)]
        with self._patch({'events': ev, 'calendars': [{'id': '1'}]}):
            r = z.handle('meetings today')
        self.assertIn('4 left today', r)
        self.assertIn('plus 1 more', r)
        with self._patch({'events': [], 'calendars': [{'id': '1'}]}):
            self.assertIn('Nothing', z.handle('meetings today'))

    def test_clock(self):
        self.assertEqual(z._clock(datetime(2026, 1, 1, 16, 0)), '4 pm')
        self.assertEqual(z._clock(datetime(2026, 1, 1, 9, 30)), '9:30 am')
        self.assertEqual(z._clock(datetime(2026, 1, 1, 0, 5)), '12:05 am')


class Actions(Base):
    def test_start_day(self):
        self.mk('23OCT26_472_LivingMetalScandal_Video')
        r = z.handle("let's start work")
        self.assertTrue(r.startswith('Morning, J. Gmail, ClickUp, your 472 folder and Premiere are up.'))
        flat = [' '.join(c) for c in self.calls]
        self.assertTrue(any('-a Brave Browser https://mail.google.com/mail/u/0/#inbox' in c for c in flat))
        self.assertTrue(any('https://app.clickup.com' in c for c in flat))
        self.assertTrue(any('-a Adobe Premiere Pro 2026' in c for c in flat))

    def test_edit_mode(self):
        self.mk('23OCT26_472_X_Video')
        r = z.handle('edit mode')
        flat = [' '.join(c) for c in self.calls]
        self.assertTrue(any('Adobe Media Encoder 2026' in c for c in flat))
        self.assertIn('472', r)

    def test_open_tool_not_found_opens_new(self):
        self.assertEqual(z.handle('open the whatsapp'), "WhatsApp's up.")
        self.assertIn(['open', '-a', 'Brave Browser', 'https://web.whatsapp.com'], self.calls)

    def test_open_tool_focus_existing(self):
        with mock.patch.object(z, '_osa', return_value='found'):
            self.assertEqual(z.handle('open gmail'), "Gmail's up.")
        self.assertEqual(self.calls, [])


class NeverRaises(Base):
    def test_errors(self):
        boom = mock.Mock(side_effect=RuntimeError('boom'))
        for name in ('_run', '_osa', '_calendar_events'):
            with mock.patch.object(z, name, boom):
                for p in ['start my day', 'edit mode', 'new task 99 foo', 'open gmail', 'unread',
                          'next meeting', 'meetings today', 'export check']:
                    self.assertIsInstance(z.handle(p), str, (name, p))
        with mock.patch.object(z, '_calendar_events', return_value={'events': 'bad', 'calendars': [1]}):
            self.assertIsInstance(z.handle('next meeting'), str)

    def test_garbage(self):
        for v in (None, 5, '', '   ', '!!!'):
            self.assertIsNone(z.handle(v))


if __name__ == '__main__':
    unittest.main()


class VoicePickTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.p = [mock.patch.object(z, 'VOICE_PICK', os.path.join(self.d, 'voice.json')), mock.patch.object(z, 'ZUKA_DIR', self.d)]
        for x in self.p: x.start()

    def tearDown(self):
        for x in self.p: x.stop()

    def test_list_names_every_voice_and_the_current_one(self):
        said = z.handle('voice options')
        for name in z.VOICES.values(): self.assertIn(name, said)
        self.assertIn("warm (that's me now)", said)

    def test_try_saves_the_pick_and_keep_confirms(self):
        self.assertIn('British voice', z.handle('try the british voice'))
        with open(z.VOICE_PICK) as f: self.assertEqual(json.load(f)['pick'], 'british')
        self.assertIn("That's my voice now", z.handle('keep it'))
        self.assertIn('Jarvis', z.handle('use jarvis voice'))
        self.assertIsNone(z.handle('try photoshop'))   # not a voice: the normal path

    def test_greetings_are_kept_and_restored_for_her_own_voice(self):
        g = os.path.join(self.d, 'greetings'); os.makedirs(g)
        Path(g, 'ack-1.wav').write_text('original')
        z.handle('try the deep voice')            # no recorder here: greetings untouched, original kept once
        self.assertTrue(os.path.exists(os.path.join(self.d, 'greetings-original', 'ack-1.wav')))
        Path(g, 'ack-1.wav').write_text('re-recorded')
        z.handle('go back to your original voice')
        self.assertEqual(Path(g, 'ack-1.wav').read_text(), 'original')
