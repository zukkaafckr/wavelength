import json
import os
import plistlib
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zuka_commands as z  # noqa: E402
import zuka_work as w  # noqa: E402
import zuka_apps as apps  # noqa: E402

WF = {'browser': 'Brave Browser',
      'clickup': {'listId': '123', 'editorFieldId': 'F1', 'me': 'Sam', 'assigner': 'alex', 'teamId': 'T1'},
      'trackers': {'takedown': 'https://claude.ai/artifact/AAA', 'winning': 'https://claude.ai/artifact/BBB'}}


def task(i, name, field=None, assignee=None, creator='Alex S'):
    return {'id': i, 'name': name, 'status': {'status': 'to do'}, 'url': f'https://app.clickup.com/t/{i}',
            'creator': {'username': creator}, 'assignees': [{'id': 9, 'username': assignee}] if assignee else [],
            'custom_fields': [field] if field else []}


DROP = {'id': 'F1', 'type': 'drop_down', 'value': 1, 'type_config': {'options': [{'orderindex': 0, 'name': 'Ali'}, {'orderindex': 1, 'name': 'Sam'}]}}
LABELS = {'id': 'F1', 'type': 'labels', 'value': ['x2'], 'type_config': {'options': [{'id': 'x1', 'label': 'Ali'}, {'id': 'x2', 'label': 'Sam'}]}}
USERS = {'id': 'F1', 'type': 'users', 'value': [{'id': 9, 'username': 'Sam R'}]}
OTHER = dict(DROP, value=0)
WA = {'rs': 'complete', 'len': 3000, 'n': 3, 'items': [
    {'name': 'Family🌎', 'snippet': '‪Sleeping?‬', 'unread': True, 'time': '11:42', 'me': False},
    {'name': 'Team Daily', 'snippet': 'EOD report for today with many many words in it', 'unread': False, 'time': 'Yesterday', 'me': False},
    {'name': 'Chris Lee', 'snippet': 'Photo', 'unread': False, 'time': 'Yesterday', 'me': True}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.wf = t / 'workflow.json'
        self.wf.write_text(json.dumps(WF))
        for tgt, val in ((z, {'WORKFLOW': str(self.wf)}),):
            for k, v in val.items():
                p = mock.patch.object(tgt, k, v); p.start(); self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {'ATTICUS_DIR': str(t)}); e.start(); self.addCleanup(e.stop)
        self.tok = mock.patch.object(w, '_token', return_value='tok'); self.tok.start(); self.addCleanup(self.tok.stop)
        self.snap = mock.patch.object(apps, 'clickup_snapshot', return_value=None); self.snapm = self.snap.start(); self.addCleanup(self.snap.stop)   # app unreadable -> silent API fallback
        self.ht = mock.patch.object(w, '_has_token', return_value=True); self.ht.start(); self.addCleanup(self.ht.stop)
        self.opened = []
        self.runs = []
        pr = mock.patch.object(z, '_run', lambda a, timeout=10, inp=None: self.runs.append(a) or mock.Mock(returncode=0, stdout='', stderr=''))
        pr.start(); self.addCleanup(pr.stop)
        for name, f in (('_open_browser', lambda u: self.opened.append(u) or True),):
            p = mock.patch.object(z, name, f); p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def api(self, tasks):
        return mock.patch.object(w, '_api', return_value={'tasks': tasks, 'last_page': True})


INBOX = '''Primary 54 unread
Change status Current status: learnings The Night Shift Story @Sam Rivers \u2014 assigned to you. Edit it. Oct 26 4 unread notifications
@Sam Rivers \u2014 assigned to you. Edit it.
The Night Shift Story
Current status: learnings
Change status Current status: winner The Chain @Arjun Mitra Ad approved. Sep 9 7 unread notifications
The Chain
Current status: winner
Change status Current status: loser OLD CONCEPT ClickBot assigned this task to you Sep 9 22 unread notifications
OLD CONCEPT
Current status: loser
'''
BOARD = '''IN PROGRESS
Collapse group
1
Change status for The Green Lie
Paras Valecha, ,
remove Paras Valecha
remove Sam Rivers
READY FOR EDITING
Collapse group
1
Change status for Fresh Script
remove alex
IN REVIEW
Collapse group
2
Change status for Done One
remove Emad Khan
'''


class AppReader(Base):
    def setUp(self):
        super().setUp()
        self.now = mock.patch.object(w, 'datetime', wraps=w.datetime); m = self.now.start(); self.addCleanup(self.now.stop)
        m.now.return_value = w.datetime(2026, 10, 27, 15, 0)
        self.snap.stop()
        snap = {'inbox': apps.parse_clickup_inbox(INBOX), 'unread': 54, 'board': apps.parse_clickup_board(BOARD, 'Sam'), 'team': '1'}
        self.snap = mock.patch.object(apps, 'clickup_snapshot', return_value=snap); self.snap.start(); self.addCleanup(self.snap.stop)

    def test_parse_inbox(self):
        rows = apps.parse_clickup_inbox(INBOX)
        self.assertEqual([r['task'] for r in rows], ['The Night Shift Story', 'The Chain', 'OLD CONCEPT'])
        self.assertTrue(rows[0]['assigned']); self.assertFalse(rows[1]['assigned'])
        self.assertEqual(rows[2]['who'], 'ClickBot')
        self.assertEqual(apps.inbox_total(INBOX), 54)

    def test_parse_board(self):
        b = apps.parse_clickup_board(BOARD, 'Sam')
        self.assertEqual([(t['name'], t['group'], t['mine']) for t in b],
                         [('The Green Lie', 'IN PROGRESS', True), ('Fresh Script', 'READY FOR EDITING', False), ('Done One', 'IN REVIEW', False)])

    def test_assigned_reply_reads_app_not_api(self):
        with mock.patch.object(w, '_api', side_effect=AssertionError('API must not be used')):
            out = z.handle('did Alex assign me any scripts')
        self.assertIn("1 script in your ClickUp inbox: 'The Night Shift Story', Oct 26.", out)   # the Sep 9 one is too old
        self.assertIn("down as editor on 'The Green Lie'", out)
        self.assertIn('54 unread', out)
        self.assertTrue(out.endswith('Want me to open ClickUp?'))

    def test_seen_and_new_only(self):
        z.handle('check clickup')
        self.assertIn('a:The Night Shift Story|Oct 26', json.loads((Path(self.tmp.name) / 'clickup-seen.json').read_text()))
        out = z.handle('any new scripts')
        self.assertTrue(out.startswith('Nothing new for you in ClickUp'))

    def test_ads_board_new(self):
        out = z.handle("what's new on the ads board")
        self.assertIn("'The Green Lie' and 'Fresh Script'", out)
        self.assertNotIn('Done One', out)

    def test_anything_from_alex(self):
        self.assertIn('Night Shift', z.handle('anything from Alex'))

    def test_offer_opens_app_inbox(self):
        z.handle('check clickup')
        with mock.patch.object(apps, 'open_view') as ov:
            self.assertEqual(z.handle('yes'), "ClickUp's up, J.")
        ov.assert_called_once_with('ClickUp', 'inbox')

    def test_check_script_uses_app_and_is_quiet_after(self):
        out = w.check_clickup()
        self.assertIn('Night Shift', out); self.assertNotIn('Want me', out)
        self.assertEqual(w.check_clickup(), '')

    def test_age(self):
        n = w.datetime(2026, 10, 27, 15, 0)
        self.assertEqual(w._age_days('Oct 26', n), 1); self.assertEqual(w._age_days('1:37 pm', n), 0); self.assertIsNone(w._age_days('??', n))


DISCORD = '''Direct Messages
unread, BOHT PYAARA BANDA (direct message), Online
Paras Valecha (direct message)
unread, VANGUARD (direct message)
10 mentions, Game Of Throwers
Unread messages, red room
'''
SLACK = '''Home
1
Home
DMs
0
DMs
Google Calendar (APP) (has 1 notification)
Alex
'''


class Chat(Base):
    def test_parsers(self):
        self.assertEqual(apps.parse_discord(DISCORD), {'dms': ['BOHT PYAARA BANDA', 'VANGUARD'], 'servers': ['Game Of Throwers (10 mentions)', 'red room']})
        p = apps.parse_slack(SLACK, 'Sam (DM) - Acmebrands - 1 new item - Slack')
        self.assertEqual((p['unread'], p['tabs']['Home'], p['new_items']), (['Google Calendar (APP)'], 1, 1))

    def test_discord_reply(self):
        st = {'app': 'Discord', 'badge': 73, 'unread': [], 'dms': ['A', 'B'], 'servers': ['red room'], 'was_running': True}
        with mock.patch.object(apps, 'chat_status', return_value=st):
            out = z.handle('any messages on discord')
        self.assertEqual(out, 'Discord shows 73 on its badge: unread messages from A and B; activity in red room.')

    def test_slack_reply_and_phrases(self):
        st = {'app': 'Slack', 'badge': 1, 'unread': ['Google Calendar (APP)'], 'dms': [], 'tabs': {}, 'was_running': True}
        with mock.patch.object(apps, 'chat_status', return_value=st) as cs:
            for q in ('any messages on slack', 'check slack', 'who messaged me on slack', 'any new messages on slack'):
                self.assertIn('Slack shows 1 on its badge: unread in Google Calendar (APP).', z.handle(q), q)
            cs.assert_called_with('slack')

    def test_nothing_and_unreadable(self):
        with mock.patch.object(apps, 'chat_status', return_value={'app': 'Slack', 'badge': 0, 'unread': [], 'dms': []}):
            self.assertEqual(z.handle('check slack'), 'Nothing unread on Slack, J.')
        with mock.patch.object(apps, 'chat_status', return_value=None):
            self.assertIn("couldn't read Slack", z.handle('check slack'))

    def test_dock_badges(self):
        out = 'Finder\t\nSlack\t3\nClickUp\t54\nMail\tnull\nDiscord\t\u2022\nSafari\t9\n'
        self.assertEqual(apps.parse_dock(out), {'Slack': 3, 'ClickUp': 54, 'Discord': 1, 'Safari': 9})
        with mock.patch.object(apps, '_run', return_value=mock.Mock(returncode=0, stdout=out)):
            self.assertEqual(apps.badges(), {'Slack': 3, 'ClickUp': 54, 'Discord': 1})
        with mock.patch.object(apps, 'badges', return_value={'Slack': 3, 'ClickUp': 54}), mock.patch.object(apps, 'running', return_value=True):
            self.assertEqual(apps.badge_sentence(), 'On your apps: 54 in ClickUp, and 3 on Slack.')

    def test_inbox_summary_includes_apps(self):
        with mock.patch.object(z, '_browser_titles', return_value=''), \
             mock.patch.object(z, '_parse_titles', return_value={'whatsapp': 2, 'gmail': []}), \
             mock.patch.object(z, '_set_offer'), \
             mock.patch.object(apps, 'badge_sentence', return_value='On your apps: 3 on Slack.'):
            self.assertIn('On your apps: 3 on Slack.', z._unread())


class Reader(Base):
    def test_read_app_launches_navigates_and_restores(self):
        calls = []
        base = {'text': 'board ' * 60, 'page': 'https://app.clickup.com/1/v/l/abc', 'window': 'W', 'web': True}
        inbox = {'text': 'Primary 3 unread', 'page': 'https://app.clickup.com/1/inbox', 'window': 'Inbox', 'web': True}
        reads = iter([base, base, inbox, inbox, base])
        with mock.patch.object(apps, 'frontmost', return_value='Claude'), mock.patch.object(apps, 'running', return_value=False), \
             mock.patch.object(apps, '_run', side_effect=lambda a, t=15: calls.append(a) or mock.Mock(returncode=0, stdout='')), \
             mock.patch.object(apps, 'hands_read', side_effect=lambda *a, **k: next(reads, base)), \
             mock.patch.object(apps, 'hands_click', side_effect=lambda n, l: calls.append(('click', n, l)) or True), \
             mock.patch.object(apps, 'time') as tm:
            tm.time.side_effect = iter(range(0, 1000)); tm.sleep = lambda s: None
            out = apps.read_app('ClickUp', view='inbox')
        self.assertEqual(out['view_text'], 'Primary 3 unread')
        self.assertIn(['open', '-g', '-a', 'ClickUp'], calls)
        self.assertEqual([c for c in calls if isinstance(c, tuple)], [('click', 'ClickUp', 'Inbox'), ('click', 'ClickUp', 'Go back')])


class ClickUp(Base):
    def test_field_types(self):
        for f in (DROP, LABELS, USERS):
            self.assertTrue(w._is_mine(task('1', 'a', f), WF['clickup']), f['type'])
        self.assertFalse(w._is_mine(task('1', 'a', OTHER), WF['clickup']))
        self.assertTrue(w._is_mine(task('1', 'a', OTHER, assignee='sam'), WF['clickup']))

    def test_assigned_today(self):
        ts = [task('1', 'River Story hook test', DROP), task('2', 'Other script', LABELS), task('3', 'Not mine', OTHER)]
        with self.api(ts):
            out = z.handle('did Alex assign me any scripts today')
        self.assertTrue(out.startswith("Alex assigned you 2 scripts today: 'River Story hook test' and 'Other script'."))
        self.assertTrue(out.endswith('Want me to open them?'))
        self.assertNotIn('Not mine', out)

    def test_offer_yes_opens(self):
        with self.api([task('1', 'A', DROP)]):
            z.handle('check clickup')
        self.assertEqual(z.handle('yes'), 'Opened 1 task, J.')
        self.assertEqual(self.opened, [])   # never the browser
        self.assertEqual(self.runs[-1], ['open', '-a', 'ClickUp', 'https://app.clickup.com/t/1'])
        self.assertIsNone(z.handle('yes'))

    def test_any_new_uses_seen(self):
        with self.api([task('1', 'A', DROP)]):
            self.assertIn("'A'", z.handle('any new scripts for me'))
            self.assertEqual(z.handle('any new scripts'), 'Nothing new for you on the ads board, J.')
        self.assertEqual(json.loads((Path(self.tmp.name) / 'clickup-seen.json').read_text()), ['1'])

    def test_none_assigned(self):
        with self.api([]):
            self.assertEqual(z.handle("what's assigned to me"), 'Nothing assigned to you in the last day, J.')

    def test_no_key_never_asked(self):
        with mock.patch.object(w, '_has_token', return_value=False):
            out = z.handle('check clickup')
        self.assertNotIn('key', out.lower())
        self.assertIn("couldn't read the ClickUp app", out)

    def test_token_lookup_uses_keychain(self):
        self.tok.stop()
        with mock.patch.object(z, '_run', return_value=mock.Mock(returncode=44, stdout='', stderr='')) as r:
            with self.assertRaises(w.NoToken):
                w._token()
            self.assertIn('wavelength-clickup', r.call_args[0][0])
        self.tok.start()

    def test_how_to(self):
        self.assertEqual(z.handle('how do I connect ClickUp'), w.NO_KEY_NEEDED)

    def test_team_discovery_cached(self):
        d = json.loads(self.wf.read_text()); d['clickup'].pop('teamId'); d['extra'] = 1; self.wf.write_text(json.dumps(d))
        calls = []

        def api(path, tok, timeout=10):
            calls.append(path)
            return {'teams': [{'id': '777'}]} if path == '/team' else {'tasks': [], 'last_page': True}
        with mock.patch.object(w, '_api', api):
            z.handle('check clickup')
        saved = json.loads(self.wf.read_text())
        self.assertEqual(saved['clickup']['teamId'], '777')
        self.assertEqual(saved['extra'], 1)
        self.assertEqual(saved['clickup']['me'], 'Sam')

    def test_check_script(self):
        with self.api([task('1', 'A', DROP)]):
            self.assertIn("'A'", w.check_clickup())
            self.assertNotIn('Want me', w.check_clickup() or 'x')
            self.assertEqual(w.check_clickup(), '')
        with mock.patch.object(w, '_token', side_effect=w.NoToken()):
            self.assertEqual(w.check_clickup(), '')

    def test_install_plist_temp_home(self):
        with mock.patch.dict(os.environ, {'HOME': self.tmp.name}):
            p = w.install_clickup_check(times=['15:00'])
        self.assertEqual(p, os.path.join(self.tmp.name, 'Library/LaunchAgents/com.wavelength.clickupcheck.plist'))
        with open(p, 'rb') as fh: d = plistlib.load(fh)
        self.assertEqual(d['Label'], 'com.wavelength.clickupcheck')
        self.assertEqual(sorted(x['Weekday'] for x in d['StartCalendarInterval']), [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(x['Hour'] == 15 for x in d['StartCalendarInterval']))
        self.assertIn('--check-clickup', d['ProgramArguments'][2])
        self.assertIn('atticus-say', d['ProgramArguments'][2])


class Trackers(Base):
    def test_unreadable_polite_and_open_offer(self):
        out = z.handle('how many ads did I take down')
        self.assertEqual(out, "I can't read the takedown tracker page right now, J. Want me to open it for you?")
        self.assertEqual(z.handle('yes'), 'Opened 1 task, J.')
        self.assertEqual(self.opened, ['https://claude.ai/artifact/AAA'])
        self.assertIn('winning tracker', z.handle('any new winners'))

    def test_not_configured(self):
        self.wf.write_text('{}')
        self.assertIn("isn't set up", z.handle('winning ads update'))


class WhatsApp(Base):
    def test_latest(self):
        with mock.patch.object(z, '_tab_exec', return_value=json.dumps(WA)):
            out = z.handle('who messaged me on whatsapp')
            self.assertEqual(out, "Latest on WhatsApp, 1 unread in all: Family, 'Sleeping?', at 11:42; Team Daily, 'EOD report for today with many many…', yesterday.")
            self.assertEqual(z.handle('latest whatsapp messages'), out)
            self.assertNotIn('click', z._WA_JS.lower())

    def test_up_to_five(self):
        items = [dict(WA['items'][0], name=f'P{i}') for i in range(8)]
        out = z._fmt_whatsapp(items)
        self.assertIn('P4', out); self.assertNotIn('P5', out)

    def test_what_did_x_say(self):
        with mock.patch.object(z, '_tab_exec', return_value=json.dumps(WA)):
            self.assertEqual(z.handle('what did Family say on WhatsApp'), "Family said 'Sleeping?', at 11:42.")
            self.assertEqual(z.handle('what did chris say on whatsapp'), "Your last message to Chris Lee was 'Photo', yesterday.")
            self.assertIn("don't see a chat with zed", z.handle('what did zed say on whatsapp'))
        with mock.patch.object(z, '_tab_exec', return_value='NOTAB'):
            self.assertIn("isn't open in Brave", z.handle('what did family say on whatsapp'))

    def test_never_raises(self):
        with mock.patch.object(z, '_tab_exec', side_effect=RuntimeError('boom')):
            self.assertIn("couldn't read WhatsApp", z.handle('what did family say on whatsapp'))
        self.assertIsNone(w.handle('hello there', 'hello there'))


if __name__ == '__main__':
    unittest.main()
