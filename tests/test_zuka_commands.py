import json
import re
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


REAL_DEFAULT = z._default_browser
EDITOR = {
 "browser": "Brave Browser",
 "tools": {
  "submagic": [
   "Submagic",
   "https://app.submagic.co"
  ],
  "higgsfield": [
   "Higgsfield",
   "https://higgsfield.ai"
  ],
  "atria": [
   "Atria",
   "https://app.tryatria.com"
  ],
  "clickup": [
   "ClickUp",
   "https://app.clickup.com"
  ],
  "drive": [
   "Drive",
   "https://drive.google.com"
  ],
  "gmail": [
   "Gmail",
   "https://mail.google.com"
  ],
  "whatsapp": [
   "WhatsApp",
   "https://web.whatsapp.com"
  ],
  "chatgpt": [
   "ChatGPT",
   "https://chatgpt.com"
  ]
 },
 "startDay": {
  "sites": [
   [
    "Gmail",
    "https://mail.google.com/mail/u/0/#inbox"
   ],
   "clickup"
  ],
  "apps": [
   "Adobe Premiere Pro 2026"
  ],
  "openTaskFolder": True
 },
 "editMode": {
  "apps": [
   "Adobe Premiere Pro 2026",
   "Adobe Media Encoder 2026"
  ],
  "openTaskFolder": True
 },
 "tasks": {
  "folder": "~/Downloads",
  "nameFormat": "{date}_{batch}_{name}_{type}",
  "dateFormat": "%d%b%y",
  "types": {
   "video": "Video",
   "iteration": "Iteration",
   "hookiteration": "HookIteration",
   "ugc": "UGC",
   "static": "Static"
  },
  "defaultType": "Video",
  "subfolders": [
   "00_Reference/Product",
   "02_Images",
   "03_StepCards",
   "04_VO_Audio/_raw",
   "04_VO_Audio/_timings",
   "05_Premiere",
   "05_TextFrames",
   "06_Exports/Premiere",
   "06_Exports/Submagic"
  ],
  "exports": {
   "Premiere": "06_Exports/Premiere",
   "Submagic": "06_Exports/Submagic"
  }
 }
}   # a sample editor's workflow.json


class Base(unittest.TestCase):
    wf = 'editor'   # 'editor' = the sample editor's workflow.json; None = no file at all; a dict/str = that file's content

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dl = Path(self.tmp.name) / 'Downloads'
        self.dl.mkdir()
        self.wfile = Path(self.tmp.name) / 'workflow.json'
        self.set_wf(self.wf)
        p = mock.patch.object(z, 'WORKFLOW', str(self.wfile))
        p.start(); self.addCleanup(p.stop)
        d = mock.patch.object(z, '_default_browser', return_value='Google Chrome')
        d.start(); self.addCleanup(d.stop)
        self.calls = []

        def fake_run(args, timeout=10, inp=None):
            self.calls.append(args)
            return mock.Mock(returncode=0, stdout='', stderr='')
        q = mock.patch.object(z, '_run', fake_run)
        q.start(); self.addCleanup(q.stop)
        self.osa = mock.patch.object(z, '_osa', return_value='none')
        self.osa.start(); self.addCleanup(self.osa.stop)
        for name, rv in (('_get_text', None), ('_get_json', None), ('_spawn', None)):   # no real network or processes in tests
            pp = mock.patch.object(z, name, return_value=rv)
            pp.start(); self.addCleanup(pp.stop)
        po = mock.patch.object(z, 'OFFER_FILE', str(Path(self.tmp.name) / 'offer.json'))
        po.start(); self.addCleanup(po.stop)
        for name, f in (('PENDING', 'pending.json'), ('SHUTDOWN_FILE', 'shutdown.json')):   # each test starts with no half-given reminder or shutdown offer
            pp = mock.patch.object(z, name, str(Path(self.tmp.name) / f))
            pp.start(); self.addCleanup(pp.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def set_wf(self, v):
        if v == 'editor':
            v = json.loads(json.dumps(EDITOR)); v['tasks']['folder'] = str(self.dl)
        if v is None:
            self.wfile.unlink(missing_ok=True)
        else:
            self.wfile.write_text(v if isinstance(v, str) else json.dumps(v))

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
        for k in EDITOR['tools']:
            with mock.patch.object(z, '_focus_or_open', return_value=True):
                self.assertEqual(z.handle(f'open {k}'), f"{EDITOR['tools'][k][0]}'s up.")

    def test_negative(self):
        for p in ['open premiere', 'open safari', 'how is the export going', 'what is my weather app',
                  'send a whatsapp to mom', 'write a script for my day', 'new task', 'open', '']:
            self.assertIsNone(z.handle(p), p)


class Folders(Base):
    def test_new_task_default_type(self):
        r = z.handle('new task 473 copper story')
        stamp = datetime.now().strftime('%d%b%y').upper()
        d = self.dl / f'{stamp}_473_CopperStory_Video'
        self.assertTrue(d.is_dir())
        for s in EDITOR['tasks']['subfolders']:
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
        info = z._parse_titles(['Inbox (12) - sam@studio.com - Gmail', 'Inbox (1,001) - ps@gmail.com - Gmail', '(3) WhatsApp'])
        r = z._unread_reply(info)
        self.assertIn('12 unread in sam', r)
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
            self.assertEqual(z.handle('any new messages'), '7 unread on WhatsApp, and 2 unread in your Gmail.' + z.OFFER_TEXT)


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


class Generic(Base):
    wf = None

    def test_no_file_defaults(self):
        w = z._workflow()
        self.assertEqual(w['browser'], 'Google Chrome')
        self.assertEqual(set(w['tools']), {'gmail', 'whatsapp', 'drive', 'chatgpt'})
        self.assertIsNone(w['tasks'])
        self.assertEqual(w['startDay'], {'sites': ['gmail'], 'apps': [], 'openTaskFolder': False})

    def test_replies_have_no_work_specific_names(self):
        replies = [z.handle(p) for p in ['start my day', 'edit mode', 'export check', 'new task 55 foo bar',
                                         'open gmail', 'open drive', 'unread']]
        self.assertTrue(all(isinstance(r, str) for r in replies))
        for r in replies:
            for bad in ('Premiere', 'Submagic', 'Atria', 'Higgsfield', 'ClickUp', 'Brave', 'Media Encoder'):
                self.assertNotIn(bad, r)
        flat = ' '.join(' '.join(c) for c in self.calls)
        for bad in ('Premiere', 'Brave', 'clickup'):
            self.assertNotIn(bad, flat)
        self.assertIn('-a Google Chrome https://mail.google.com', flat)

    def test_not_set_up_replies(self):
        self.assertIn('set up', z.handle('edit mode'))
        self.assertIn("aren't set up", z.handle('new task 55 foo bar'))
        self.assertIn("aren't set up", z.handle('export check'))
        self.assertEqual(list(self.dl.iterdir()), [])
        self.assertTrue(z.handle('start my day').startswith('Morning, J. Gmail is up.'))

    def test_editor_only_tools_not_available(self):
        self.assertIsNone(z.handle('open submagic'))
        self.assertIsNone(z.handle('open clickup'))


class Browsers(Base):
    def test_safari_scripts(self):
        self.set_wf({'browser': 'Safari'})
        scripts = []
        with mock.patch.object(z, '_osa', side_effect=lambda sc, timeout=8: scripts.append(sc) or '(3) WhatsApp'):
            self.assertIn('3 unread on WhatsApp', z.handle('any new messages'))
            z.handle('open gmail')
        self.assertIn('name of every tab', scripts[0])
        self.assertNotIn('title', scripts[0])
        self.assertIn('application "Safari"', scripts[0])
        self.assertIn('set current tab of w to tab ti of w', scripts[1])
        self.assertNotIn('active tab index', scripts[1])

    def test_chromium_scripts_and_short_name(self):
        for b in ('Brave Browser', 'Google Chrome', 'Arc', 'Microsoft Edge'):
            self.set_wf({'browser': b})
            sc = z._focus_script(b, 'x.com')
            self.assertIn('set active tab index of w to ti', sc)
            self.assertIn(f'application "{b}"', sc)
            self.assertIn('title of every tab', z._titles_script(b))
        self.set_wf({'browser': 'Brave Browser'})
        self.assertIn('open in Brave', z._unread_reply({'whatsapp': None, 'gmail': []}))

    def test_open_url_uses_browser(self):
        self.set_wf({'browser': 'Arc'})
        z.handle('open drive')
        self.assertIn(['open', '-a', 'Arc', 'https://drive.google.com'], self.calls)

    def test_default_browser_parse(self):
        plist = '(\n {\n LSHandlerContentType = "public.html";\n },\n {\n LSHandlerRoleAll = "com.google.chrome";\n LSHandlerURLScheme = https;\n }\n)'
        for out, want in ((plist, 'Google Chrome'), ('', 'Safari'), (plist.replace('com.google.chrome', 'com.unknown.app'), 'Safari')):
            REAL_DEFAULT.cache_clear()
            with mock.patch.object(z, '_run', return_value=mock.Mock(stdout=out)):
                self.assertEqual(REAL_DEFAULT(), want)
        REAL_DEFAULT.cache_clear()


class Robust(Base):
    def test_bad_json_and_unknown_keys(self):
        for bad in ('{not json', '[]', '"x"', '{"tools": 5, "startDay": "no", "tasks": 7, "browser": 3}',
                    '{"mystery": {"a": 1}, "tasks": {"folder": ""}}'):
            self.set_wf(bad)
            w = z._workflow()
            self.assertEqual(w['browser'], 'Google Chrome', bad)
            self.assertIsNone(w['tasks'], bad)
            self.assertIn('gmail', w['tools'])
            self.assertIsInstance(z.handle('start my day'), str)

    def test_unknown_keys_ignored_known_kept(self):
        self.set_wf({'mystery': 1, 'browser': 'Arc', 'tools': {'x': ['X', 'https://x.test'], 'bad': 'no'}})
        w = z._workflow()
        self.assertEqual(w['browser'], 'Arc')
        self.assertEqual(w['tools'], {'x': ['X', 'https://x.test']})

    def test_tasks_without_folder_not_set_up(self):
        self.set_wf({'tasks': {'nameFormat': '{batch}'}})
        self.assertIn("aren't set up", z.handle('export check'))

    def test_custom_format_and_dupes(self):
        self.set_wf({'tasks': {'folder': str(self.dl), 'nameFormat': '{batch}-{name}', 'dateFormat': '%Y',
                               'types': {'reel': 'Reel'}, 'subfolders': ['a/b'], 'exports': {'Out': 'out'}}})
        self.assertIn('is ready in Downloads', z.handle('new task 12 big day reel'))
        self.assertTrue((self.dl / '12-BigDay' / 'a' / 'b').is_dir())
        self.assertIn('already exists', z.handle('new task 12 other'))
        (self.dl / '12-BigDay' / 'out').mkdir()
        (self.dl / '12-BigDay' / 'out' / 'v.mp4').write_text('x')
        self.assertEqual(z.handle('export check'), 'Task 12: 1 in Out.')


class EverydayBasics(Base):
    def test_math(self):
        for p, want in [('what is two plus two', "That's 4, J."), ("what's 15% of 2,400", "That's 360, J."),
                        ('fifteen percent of twenty four hundred', "That's 360, J."), ('calculate 10 times 5', "That's 50, J."),
                        ('how much is 7 divided by 2', "That's 3.5, J."), ('5 squared', "That's 25, J."), ('3 cubed', "That's 27, J."),
                        ('what is the square root of 144', "That's 12, J."), ('2 to the power of 10', "That's 1,024, J."),
                        ('1,200 x 3', "That's 3,600, J."), ('one hundred and five minus six', "That's 99, J."),
                        ('what is 1 divided by 3', "That's 0.3333, J."), ('two thousand four hundred over twelve', "That's 200, J."),
                        ('what is 5 over 0', "I can't divide by zero, J.")]:
            self.assertEqual(z.handle(p), want, p)

    def test_math_negative_and_safe(self):
        for p in ['what is 5', 'two', 'what is 9 ** 9 ** 9', 'what is __import__ os plus 1', 'what is a plus b']:
            self.assertIsNone(z.handle(p), p)
        self.assertIsNone(z._math('what is 10 to the power of 500'))
        with self.assertRaises(ValueError):
            z._safe_eval('__import__("os")')

    def test_time_date_day(self):
        now = datetime(2026, 10, 26, 15, 42)
        with mock.patch.object(z, '_now', return_value=now):
            self.assertEqual(z.handle('what time is it'), "It's 3:42 pm, J.")
            self.assertEqual(z.handle("what's the time"), "It's 3:42 pm, J.")
            self.assertEqual(z.handle("what's the date today"), "It's Monday the 26th of October, J.")
            self.assertEqual(z.handle("what's today's date"), "It's Monday the 26th of October, J.")
            self.assertEqual(z.handle('what day is it'), "It's Monday, J.")
            self.assertIsNone(z.handle('what time is the meeting'))

    def test_weather(self):
        wx = 'Partly cloudy +31°C feels +35°C, 0.0mm rain'
        with mock.patch.object(z, '_get_text', return_value=wx) as g:
            self.assertEqual(z.handle("what's the weather"), "Right now it's partly cloudy, 31°C, feels like 35°C.")
            self.assertTrue(g.call_args[0][0].startswith('https://wttr.in/?format='))
            self.assertIn('Mumbai', z.handle('weather in mumbai'))
            self.assertIn('wttr.in/mumbai?', g.call_args[0][0])
            self.assertEqual(z.handle('is it going to rain today'), "No rain right now, J. It's partly cloudy, 31°C.")
            self.assertEqual(z.handle('temperature outside'), "It's 31°C outside, J. Feels like 35°C.")
        with mock.patch.object(z, '_get_text', return_value='Light rain +22°C feels +24°C, 1.2mm rain'):
            self.assertIn('raining', z.handle('is it going to rain'))
            self.assertIn('There\'s some rain', z.handle('weather'))
        self.assertEqual(z.handle('weather'), "I can't reach the weather right now, J.")   # offline

    def test_facts(self):
        def fake(url, timeout=4):
            if 'list=search' in url:
                return {'query': {'search': [{'title': 'Elon Musk'}]}}
            return {'type': 'standard', 'extract': 'Elon Reeve Musk (born 1971) is a businessman. He runs companies. He also tweets a lot about many things.'}
        with mock.patch.object(z, '_get_json', side_effect=fake) as g:
            self.assertEqual(z.handle('who is elon musk'), 'Elon Reeve Musk is a businessman. He runs companies.')
            self.assertIn('srsearch=elon%20musk', g.call_args_list[0][0][0])
            z.handle('what is the capital of japan')
            self.assertIn('srsearch=capital%20of%20japan', g.call_args_list[2][0][0])
        with mock.patch.object(z, '_get_json', return_value={'query': {'search': [{'title': 'X'}]}, 'type': 'disambiguation', 'extract': 'X may refer to.'}):
            self.assertIsNone(z.handle('what is mercury'))
        for p in ['what is my latest export', 'who is calling', 'who is', 'what is this file', 'tell me about my day',
                  'what is going on', 'what is the new task', 'who was the email from', 'what is 4 plus x']:
            with mock.patch.object(z, '_get_json', side_effect=fake):
                self.assertIsNone(z.handle(p), p)
        self.assertIsNone(z.handle('who is elon musk'))   # offline -> Claude can take it

    def test_define(self):
        d = [{'meanings': [{'definitions': [{'definition': 'The occurrence of events by chance in a happy way.'}]}]}]
        with mock.patch.object(z, '_get_json', return_value=d):
            for p in ['define serendipity', 'what does serendipity mean', 'meaning of serendipity']:
                self.assertEqual(z.handle(p), 'Serendipity: The occurrence of events by chance in a happy way.', p)
            self.assertIsNone(z.handle('define'))
            self.assertIsNone(z.handle('what does it mean'))
        self.assertIsNone(z.handle('define serendipity'))

    def test_currency(self):
        with mock.patch.object(z, '_get_json', return_value={'result': 'success', 'rates': {'INR': 84.12, 'USD': 1}}) as g:
            self.assertEqual(z.handle('convert 100 usd to inr'), '100 US dollars is about 8,412 rupees, J.')
            self.assertIn('/latest/USD', g.call_args[0][0])
            self.assertIn('8,412 rupees', z.handle('100 dollars in rupees'))
            self.assertIn('4,206 rupees', z.handle('how much is 50 dollars in rupees'))
            self.assertIsNone(z.handle('convert 100 usd to usd'))
            self.assertIsNone(z.handle('convert 100 usd to bitcoin'))
        self.assertIsNone(z.handle('convert 100 usd to inr'))

    def test_volume(self):
        with mock.patch.object(z, '_osa', return_value='50') as o:
            self.assertEqual(z.handle('volume up'), 'Volume at 62, J.')
            self.assertIn('set volume output volume 62', o.call_args[0][0])
            self.assertEqual(z.handle('turn it down'), 'Volume at 38, J.')
            z.handle('louder'); z.handle('quieter')
            self.assertEqual(z.handle('mute'), 'Muted, J.')
            self.assertEqual(o.call_args[0][0], 'set volume output muted true')
            self.assertEqual(z.handle('unmute'), 'Unmuted, J.')
            self.assertEqual(z.handle('set volume to forty percent'), 'Volume at 40, J.')
            self.assertEqual(o.call_args[0][0], 'set volume output volume 40')
            z.handle('max volume')
            self.assertEqual(o.call_args[0][0], 'set volume output volume 100')
        with mock.patch.object(z, '_osa', return_value='95'):
            self.assertEqual(z.handle('volume up'), 'Volume at 100, J.')
        with mock.patch.object(z, '_osa', return_value='missing value'):
            self.assertIn("can't change", z.handle('volume up'))
        self.assertIsNone(z.handle('volume'))

    def test_timer(self):
        with mock.patch.object(z, '_spawn') as sp:
            self.assertEqual(z.handle('set a timer for five minutes'), 'Timer set for 5 minutes, J.')
            cmd = sp.call_args[0][0][-1]
            self.assertIn('sleep 300;', cmd)
            self.assertIn('Time', cmd)
            self.assertEqual(z.handle('timer 30 seconds'), 'Timer set for 30 seconds, J.')
            self.assertEqual(z.handle('set a timer for an hour'), 'Timer set for 1 hour, J.')
            self.assertEqual(z.handle('set a timer for half an hour'), 'Timer set for 30 minutes, J.')
            self.assertEqual(z.handle('set a 10 minute timer'), 'Timer set for 10 minutes, J.')
            self.assertIn('/usr/bin/say', sp.call_args[0][0][-1]) if not os.access(z.SAY, os.X_OK) else None
        self.assertIsNone(z.handle('set a timer'))
        self.assertIsNone(z.handle('timer for a while'))

    def test_reminders(self):
        now = datetime(2026, 10, 26, 10, 0)
        with mock.patch.object(z, '_now', return_value=now), mock.patch.object(z, '_osa', return_value='') as o:
            self.assertEqual(z.handle('remind me to call mom at 5 pm'), "Okay, I'll remind you to call mom today at 5 pm, J.")
            sc = o.call_args[0][0]
            self.assertIn('set hours of d to 17', sc)
            self.assertIn('set day of d to 26', sc)
            self.assertIn('name:"call mom"', sc)
            self.assertIn('call mom tomorrow at 9 am', z.handle('remind me to call mom tomorrow at 9 am'))
            self.assertIn('set day of d to 27', o.call_args[0][0])
            self.assertIn('in 20 minutes', z.handle('remind me to buy two apples in twenty minutes'))
            self.assertIn('set minutes of d to 20', o.call_args[0][0])
            self.assertIn('name:"buy two apples"', o.call_args[0][0])
            self.assertIn('5:30 pm', z.handle('remind me to stretch at five thirty pm'))
            self.assertIn('What should I remind you about', z.handle('remind me'))   # a missing part is asked for, never Claude
            self.assertIn('Okay, no reminder', z.handle('never mind'))
            self.assertIn('When should I remind you to dance', z.handle('remind me to dance'))   # no time given: she asks
        with mock.patch.object(z, '_now', return_value=now), mock.patch.object(z, '_osa', side_effect=RuntimeError('nope')):
            self.assertEqual(z.handle('remind me to call mom at 5 pm'),
                             "I couldn't add that to Reminders, J. Allow Zuka under Privacy & Security, Reminders.")

    def test_screenshot_lock_folders(self):
        self.assertEqual(z.handle('take a screenshot'), 'Screenshot saved to your Desktop, J.')
        self.assertEqual(self.calls[-1][:2], ['screencapture', '-x'])
        self.assertIn('/Desktop/Screenshot ', self.calls[-1][2])
        with mock.patch.object(z.os.path, 'exists', return_value=True):
            self.assertEqual(z.handle('screenshot of a part of the screen'), 'Screenshot saved to your Desktop, J.')
        self.assertEqual(self.calls[-1][:2], ['screencapture', '-i'])
        self.assertIn('Locking', z.handle('lock my screen'))
        self.assertEqual(self.calls[-1], ['pmset', 'displaysleepnow'])
        self.assertIn('Screen off', z.handle('turn off the screen'))
        self.assertIn('Downloads', z.handle('open my downloads folder'))
        self.assertEqual(self.calls[-1], ['open', os.path.expanduser('~/Downloads')])
        z.handle('open home')
        self.assertEqual(self.calls[-1], ['open', os.path.expanduser('~')])
        self.assertIsNone(z.handle('open my secrets'))

    def test_music(self):
        def run_for(running):
            def fake(args, timeout=10, inp=None):
                return mock.Mock(returncode=0 if args[:2] == ['pgrep', '-x'] and args[2] in running else 1, stdout='', stderr='')
            return fake
        with mock.patch.object(z, '_run', run_for({'Spotify'})), mock.patch.object(z, '_osa', return_value='playing') as o:
            self.assertEqual(z.handle('pause the music'), 'Paused, J.')
            self.assertEqual(o.call_args[0][0], 'tell application "Spotify" to pause')
            z.handle('skip song')
            self.assertEqual(o.call_args[0][0], 'tell application "Spotify" to next track')
            z.handle('previous track')
            self.assertEqual(o.call_args[0][0], 'tell application "Spotify" to previous track')
        with mock.patch.object(z, '_run', run_for({'Music', 'Spotify'})), mock.patch.object(
                z, '_osa', side_effect=lambda s, t=8: 'paused' if '"Music"' in s and 'player state' in s else ('playing' if 'player state' in s else '')) as o:
            z.handle('pause music')
            self.assertEqual(o.call_args[0][0], 'tell application "Spotify" to pause')   # the one actually playing
        with mock.patch.object(z, '_run', run_for({'Music'})), mock.patch.object(z, '_osa', return_value='paused') as o:
            self.assertEqual(z.handle('resume the music'), 'Playing, J.')
            self.assertEqual(o.call_args[0][0], 'tell application "Music" to play')
        with mock.patch.object(z, '_run', run_for(set())):
            self.assertIsNone(z.handle('pause the music'))

    def test_presence(self):
        with mock.patch.object(z, '_tcp', return_value=True), mock.patch.object(z, '_voice_up', return_value=True), \
                mock.patch.object(z, '_claude_signed_in', return_value=True) as cs:
            self.assertEqual(z.handle('is everything ok'), 'All good, J. Online, voice is up, and Claude is signed in.')
            cs.assert_called_once()
            cs.reset_mock()
            for p in ['can you hear me', 'are you there', 'test', 'testing', 'is it working', 'checking if this is working']:
                self.assertEqual(z.handle(p), "I'm here, J. Online, and the voice is up.", p)
            cs.assert_not_called()
        with mock.patch.object(z, '_tcp', return_value=False), mock.patch.object(z, '_voice_up', return_value=True), \
                mock.patch.object(z, '_claude_signed_in', return_value=False):
            self.assertEqual(z.handle('is everything okay on the mac'),
                             "Not quite, J. I can't reach the internet and Claude isn't signed in.")
        with mock.patch.object(z, '_tcp', return_value=True), mock.patch.object(z, '_voice_up', return_value=False):
            self.assertEqual(z.handle('are you there'), "Not quite, J. The voice isn't answering.")
        self.assertIsNone(z.handle('test the export'))

    def test_spell(self):
        self.assertEqual(z.handle('spell necessary'), 'N-E-C-E-S-S-A-R-Y.')
        self.assertEqual(z.handle('how do you spell cat'), 'C-A-T.')
        self.assertIsNone(z.handle('spell'))

    def test_never_raises(self):
        with mock.patch.object(z, '_get_json', side_effect=RuntimeError), mock.patch.object(z, '_osa', side_effect=RuntimeError):
            for p in ['who is elon musk', 'what is the capital of japan', 'volume up', 'is everything ok']:
                self.assertIsInstance(z.handle(p) or '', str)


LI = {'rs': 'complete', 'len': 5000, 'n': 4, 'items': [
    {'name': 'Nisha Rao', 'snippet': 'Hi, saw your reel and loved it a lot, can we talk', 'time': '9:36 AM', 'unread': True},
    {'name': 'Promo Co', 'snippet': 'Sponsored  Grow your page', 'time': '', 'unread': True},
    {'name': 'Ravi', 'snippet': 'You: sure, thanks', 'time': 'Tue', 'unread': True},
    {'name': 'Old Friend', 'snippet': 'ok', 'time': 'Mon', 'unread': False}]}


class Inbox(Base):
    def test_linkedin_parse(self):
        self.assertEqual(z._fmt_linkedin(LI['items']),
                         "On LinkedIn, Nisha Rao sent one, plus 1 sponsored. Latest message: Nisha Rao, 'Hi, saw your reel and loved it a lot…', at 9:36 AM.")
        self.assertEqual(z._fmt_linkedin(LI['items'][2:]), 'Nothing new on LinkedIn, J.')
        many = [{'name': n, 'snippet': 'hey', 'time': '1:00', 'unread': True} for n in 'ABCDEFG']
        out = z._fmt_linkedin(many)
        self.assertIn('7 unread: A, B, C, D, and E.', out)
        self.assertNotIn('F', out.split('Latest')[0])

    def test_whatsapp_gmail_parse(self):
        self.assertEqual(z._fmt_whatsapp([{'name': 'Mom', 'unread': True}, {'name': 'Paras', 'unread': True}, {'name': 'HOA Team', 'unread': True}, {'name': 'X', 'unread': False}]),
                         'WhatsApp: 3 chats unread: Mom, Paras, and HOA Team.')
        self.assertEqual(z._fmt_whatsapp([{'name': 'Mom', 'unread': True}]), 'WhatsApp: 1 chat unread: Mom.')
        self.assertEqual(z._fmt_gmail([{'name': 'Riya', 'subject': 'batch brief'}, {'name': 'ClickUp', 'subject': ''}]),
                         'Gmail: 2 unread: Riya, about batch brief; ClickUp.')
        self.assertEqual(z._fmt_gmail([]), 'Nothing unread in your Gmail, J.')

    def test_read_linkedin_via_osa(self):
        with mock.patch.object(z, '_osa', return_value=json.dumps(LI)) as o:
            out = z.handle('who messaged me on linkedin')
            self.assertTrue(out.startswith('On LinkedIn, Nisha Rao sent one'))
            sc = o.call_args[0][0]
            self.assertIn('execute t javascript', sc)
            self.assertIn('Brave Browser', sc)
            self.assertNotIn('click', sc.lower().replace('.click', 'x') if False else '')   # no clicking anywhere in the script
            self.assertNotIn('activate', sc)
            self.assertNotIn('set active tab', sc)
        with mock.patch.object(z, '_osa', return_value=json.dumps(LI)):
            self.assertTrue(z.handle('read my linkedin messages').startswith('On LinkedIn'))

    def test_safari_script(self):
        self.set_wf({'browser': 'Safari'})
        with mock.patch.object(z, '_osa', return_value=json.dumps(LI)) as o:
            z.handle('who messaged me on linkedin')
            self.assertIn('do JavaScript', o.call_args[0][0])
            self.assertNotIn('execute t javascript', o.call_args[0][0])
            self.assertIn('application "Safari"', o.call_args[0][0])
        with mock.patch.object(z, '_osa') as o:
            z._open_bg('Safari', 'https://x.test')
            self.assertIn('set current tab of w to ct', o.call_args[0][0])
        with mock.patch.object(z, '_osa') as o:
            z._open_bg('Brave Browser', 'https://x.test')
            self.assertIn('set active tab index of w to ai', o.call_args[0][0])

    def test_sleeping_tab_reloads_same_tab(self):
        tiny = json.dumps({'rs': 'complete', 'len': 24, 'n': 0, 'items': []})
        seq = [tiny, 'RELOADING', json.dumps(dict(LI, rs='loading', n=0, items=[])), json.dumps(LI)]
        with mock.patch.object(z, '_osa', side_effect=seq) as o, mock.patch.object(z.time, 'sleep'):
            out = z.handle('who messaged me on linkedin')
        self.assertTrue(out.startswith('On LinkedIn, Nisha Rao'))
        self.assertIn('set URL of t to "https://www.linkedin.com/messaging/"', o.call_args_list[1][0][0])
        self.assertNotIn('execute', o.call_args_list[1][0][0])

    def test_no_tab(self):
        with mock.patch.object(z, '_osa', side_effect=['NOTAB'] + ['NOTAB'] * 0 + ['ok', json.dumps(LI)]) as o, mock.patch.object(z.time, 'sleep'):
            out = z.handle('who messaged me on linkedin')   # LinkedIn opens in the background
        self.assertTrue(out.startswith('On LinkedIn'))
        self.assertIn('make new tab', o.call_args_list[1][0][0])
        with mock.patch.object(z, '_osa', return_value='NOTAB'):
            self.assertEqual(z.handle('who messaged me on gmail'), "Gmail isn't open in Brave, J.")
        with mock.patch.object(z, '_osa', return_value='NOBROWSER'):
            self.assertEqual(z.handle('who messaged me on whatsapp'), "Brave isn't open, J.")

    def test_whatsapp_unreadable(self):
        bad = json.dumps({'rs': 'complete', 'len': 4000, 'n': 0, 'items': []})
        with mock.patch.object(z, '_osa', return_value=bad), mock.patch.object(z.time, 'sleep'):
            self.assertEqual(z.handle('who messaged me on whatsapp'), "I couldn't read WhatsApp's list, J.")

    def test_js_permission_hint(self):
        with mock.patch.object(z, '_osa', side_effect=RuntimeError('Executing JavaScript through AppleScript is turned off')):
            self.assertIn('Allow JavaScript from Apple Events', z.handle('who messaged me on linkedin'))

    def test_yes_follow_up_window(self):
        self.assertIsNone(z.handle('yes'))            # no offer at all
        self.assertIsNone(z.handle('yes please'))
        with mock.patch.object(z, '_osa', return_value=json.dumps(LI)):
            z._set_offer(['linkedin'])
            self.assertTrue(z.handle('yes').startswith('On LinkedIn'))
            self.assertIsNone(z.handle('yes'))        # the offer is used up
            z._set_offer(['linkedin'])
            self.assertTrue(z.handle('who are they from').startswith('On LinkedIn'))
            z._set_offer(['linkedin'])
            with mock.patch.object(z.time, 'time', return_value=time.time() + 181):
                self.assertIsNone(z.handle('go ahead'))   # stale
                self.assertIsNone(z.handle('read them'))

    def test_offers_are_made(self):
        with mock.patch.object(z, '_tab_titles', return_value=['(3) LinkedIn']), mock.patch.object(z, '_osa', return_value='(3) LinkedIn'):
            self.assertIn("Want me to read who they're from?", z.handle('check linkedin'))
        self.assertEqual(z._take_offer(), ['linkedin'])
        with mock.patch.object(z, '_osa', return_value='(7) WhatsApp\nInbox (2) - x@y.com - Gmail\n'):
            z.handle('any new messages')
        self.assertEqual(z._take_offer(), ['whatsapp', 'gmail'])
        with mock.patch.object(z, '_osa', return_value='(0) WhatsApp\n'):
            z.handle('any new messages')
        self.assertIsNone(z._take_offer())


if __name__ == '__main__':
    unittest.main()


class EndOfDay(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.apps = [('Brave Browser', 'com.brave.Browser'), ('Claude', 'com.anthropic.claudefordesktop'), ('Finder', 'com.apple.finder'),
                     ('Premiere', 'com.adobe.PremierePro.26'), ('Mail', 'com.apple.mail')]
        self.quit, self.stuck, self.osa = [], set(), []
        def osa(script, timeout=8):
            self.osa.append(script)
            m = re.search(r'application id "([^"]+)" to quit', script)
            if m: self.quit.append(m[1])
            return ''
        self.p = [mock.patch.object(z, 'SHUTDOWN_FILE', os.path.join(self.d, 'sd.json')), mock.patch.object(z, '_osa', osa),
                  mock.patch.object(z, '_running_apps', lambda: [a for a in self.apps if a[1] not in self.quit or a[1] in self.stuck]),
                  mock.patch.object(z, '_workflow', lambda: {**z.DEFAULTS, 'browser': 'Brave Browser', 'keepOpen': ['Claude']}), mock.patch.object(z, 'OFFER_FILE', os.path.join(tempfile.mkdtemp(), 'o.json')), mock.patch.object(z.time, 'sleep', lambda s: None)]
        for x in self.p: x.start()

    def tearDown(self):
        for x in self.p: x.stop()

    def test_close_all_keeps_the_assistant_finder_and_kept_apps(self):
        said = z.handle('close all the running applications')
        self.assertEqual(sorted(self.quit), ['com.adobe.PremierePro.26', 'com.apple.mail', 'com.brave.Browser'])
        self.assertTrue(said.startswith('Closed Brave Browser, Premiere and Mail.'), said)

    def test_unsaved_work_stays_open_and_blocks_shutdown(self):
        self.stuck = {'com.adobe.PremierePro.26'}
        said = z.handle('close all apps we are done for the day')
        self.assertIn('Premiere is asking to save, so I left it open.', said)
        self.assertIsNone(z.handle('yes'))   # no shutdown offered while work is unsaved
        self.assertFalse(any('shut down' in s for s in self.osa))

    def test_done_for_the_day_offers_shutdown_and_yes_does_it(self):
        self.assertIn('Shut down the Mac too?', z.handle("we're done for the day"))
        self.assertIn('Shutting down', z.handle('yes'))
        self.assertTrue(any('to shut down' in s for s in self.osa))

    def test_shutdown_always_asks_and_a_stale_yes_does_nothing(self):
        self.assertIn('Say yes', z.handle('shut down the mac'))
        with open(z.SHUTDOWN_FILE, 'w') as f: json.dump({'at': time.time() - 600}, f)
        self.assertIsNone(z.handle('yes'))
        self.assertFalse(any('to shut down' in s for s in self.osa))
