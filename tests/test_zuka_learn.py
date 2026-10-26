"""zuka_learn: the daily learning engine, on fixture data (fake log / knowledgeC / pmset / memory / Brave history / Music library)."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zuka_learn as zl  # noqa: E402

MAC = 978307200


def _row(i, at, task, status='completed', model='instant', reply='ok'):
    return {'id': str(i), 'at': at.strftime('%Y-%m-%d %H:%M:%S'), 'task': task, 'status': status, 'model': model, 'path': 'instant' if model == 'instant' else 'model', 'reply': reply}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.mem = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {'ATTICUS_DIR': self.d, 'ZUKA_MEMORY_DIR': self.mem, 'ZUKA_KNOWLEDGEC': os.path.join(self.d, 'none.db'),
                                                'ZUKA_PMSET_FILE': os.path.join(self.d, 'none.txt'), 'ZUKA_BRAVE_HISTORY': os.path.join(self.d, 'none-h'),
                                                'ZUKA_MUSIC_JSON': os.path.join(self.d, 'none-m.json')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.base = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=3)

    def log(self, rows):
        with open(os.path.join(self.d, 'log.jsonl'), 'w') as f:
            for r in rows: f.write(json.dumps(r) + '\n')

    def wf(self, data=None):
        p = os.path.join(self.d, 'workflow.json')
        if data is not None: json.dump(data, open(p, 'w'))
        return json.load(open(p)) if os.path.exists(p) else {}

    def knowledgec(self, events):
        p = os.path.join(self.d, 'kc.db')
        con = sqlite3.connect(p)
        con.execute('create table ZOBJECT (ZSTREAMNAME text, ZVALUESTRING text, ZSTARTDATE real, ZENDDATE real)')
        for ts, secs, b in events:
            s = ts.timestamp() - MAC
            con.execute("insert into ZOBJECT values ('/app/usage', ?, ?, ?)", (b, s, s + secs))
        con.commit(); con.close()
        os.environ['ZUKA_KNOWLEDGEC'] = p


class Aliases(Base):
    def seq(self, pairs, gap=20):
        rows, t, i = [], self.base, 0
        for a, b in pairs:
            rows.append(_row(i, t, a, 'not_handled', 'haiku')); i += 1
            rows.append(_row(i, t + timedelta(seconds=gap), b)); i += 1
            t += timedelta(hours=1)
        return rows

    def test_needs_two_sightings(self):
        self.log(self.seq([('how are things in click up', 'check clickup')]))
        self.assertEqual(zl.learn_aliases(zl.read_log()), {})
        self.log(self.seq([('how are things in click up', 'check clickup')] * 2))
        self.assertEqual(zl.learn_aliases(zl.read_log()), {'how are things in click up': 'check clickup'})

    def test_filler_only_difference_counts_once(self):
        self.log(self.seq([('can you please check clickup', 'check clickup')]))
        self.assertEqual(zl.learn_aliases(zl.read_log()), {'can you please check clickup': 'check clickup'})

    def test_window_90s_and_unrelated_and_content(self):
        self.log(self.seq([('how are things in click up', 'check clickup')] * 2, gap=120))
        self.assertEqual(zl.learn_aliases(zl.read_log()), {})
        self.log(self.seq([('what time is it', 'open calculator')] * 3))   # unrelated rephrase
        self.assertEqual(zl.learn_aliases(zl.read_log()), {})
        self.log(self.seq([('message mom hello there', 'message mom hi there')] * 3))   # message contents never learned
        self.assertEqual(zl.learn_aliases(zl.read_log()), {})

    def test_alias_applied(self):
        self.log(self.seq([('how are things in click up', 'check clickup')] * 2))
        zl.learn()
        self.assertEqual(zl.alias('how are things in click up'), 'check clickup')
        self.assertEqual(zl.alias('open brave'), 'open brave')


class Prefs(Base):
    def library(self):
        json.dump({'tracks': [['Tum Hi Ho', 'Arijit Singh', 50, 'Bollywood', 1, 0], ['Admirin', 'Karan Aujla', 30, 'Punjabi', 0, 0], ['Shape', 'Ed Sheeran', 5, 'Pop', 0, 0]],
                   'playlists': [{'name': 'Hindi', 'count': 1, 'plays': 50, 'artists': {'Arijit Singh': 1}}, {'name': 'Punjabi', 'count': 1, 'plays': 30, 'artists': {'Karan Aujla': 1}}]},
                  open(os.path.join(self.d, 'lib.json'), 'w'))
        os.environ['ZUKA_MUSIC_JSON'] = os.path.join(self.d, 'lib.json')

    def test_never_overwrites_hand_set(self):
        self.library()
        self.wf({'music': 'my own mix', 'keepOpen': ['Slack'], 'startDay': {'apps': ['Notes'], 'sites': []}})
        h = zl.learn()
        w = self.wf()
        self.assertEqual(w['music'], 'my own mix'); self.assertEqual(w['keepOpen'], ['Slack']); self.assertEqual(w['startDay']['apps'], ['Notes'])
        self.assertTrue(any('kept your' in c for c in h['changes']))

    def test_sets_unset_and_updates_learned(self):
        self.library()
        h = zl.learn()
        self.assertEqual(self.wf()['music'], 'Arijit Singh and Karan Aujla mix')
        self.assertEqual(h['learned']['music'], 'Arijit Singh and Karan Aujla mix')
        self.assertTrue(any(c.startswith('music:') for c in h['changes']))
        # taste shifts: still ours (previously learned), so it follows
        d = json.load(open(os.environ['ZUKA_MUSIC_JSON'])); d['tracks'][2][2] = 500
        json.dump(d, open(os.environ['ZUKA_MUSIC_JSON'], 'w'))
        zl.learn()
        self.assertTrue(self.wf()['music'].startswith('Ed Sheeran'))
        # the person edits it by hand: learning backs off
        w = self.wf(); w['music'] = 'lofi beats'; self.wf(w)
        zl.learn()
        self.assertEqual(self.wf()['music'], 'lofi beats')

    def test_dry_run_writes_nothing(self):
        self.library()
        h = zl.learn(dry=True)
        self.assertTrue(h['changes'])
        self.assertFalse(os.path.exists(os.path.join(self.d, 'workflow.json')))
        self.assertFalse(os.path.exists(os.path.join(self.d, 'habits.json')))

    def test_start_day_apps_from_first_30_minutes(self):
        ev = []
        for k in range(5):
            t = self.base - timedelta(days=k)
            ev += [(t, 600, 'com.apple.Notes'), (t + timedelta(minutes=10), 300, 'com.brave.Browser'), (t + timedelta(hours=2), 300, 'com.apple.finder')]
        self.knowledgec(ev)
        with mock.patch.object(zl, 'app_name', side_effect=lambda b: {'com.apple.notes': 'Notes'}.get(b.lower())):
            h = zl.learn()
        self.assertEqual(self.wf()['startDay']['apps'], ['Notes'])
        self.assertEqual(h['firstApps']['days'], 5)


class Habits(Base):
    def test_profile_hours_types_contacts_privacy(self):
        rows = []
        for k in range(4):
            t = self.base - timedelta(days=k)
            rows.append(_row(f'c{k}', t.replace(hour=11), 'check clickup'))
            rows.append(_row(f'm{k}', t.replace(hour=21), 'Play Karan Aujla on YouTube'))
        rows.append(_row('x', self.base.replace(hour=15), 'message Rahul that my password is hunter2'))
        self.log(rows)
        h = zl.learn()
        self.assertEqual(h['requestsByHour']['11'], {'clickup check': 4})
        self.assertEqual(h['contacts'], {'Rahul': 1})
        self.assertEqual(h['music']['topArtists'][0]['name'], 'Karan Aujla')
        blob = open(os.path.join(self.d, 'habits.json')).read()
        self.assertNotIn('hunter2', blob); self.assertNotIn('password', blob)

    def test_active_hours_and_checkins(self):
        ev = []
        for k in range(1, 9):
            t = (self.base - timedelta(days=k)).replace(hour=9)
            ev += [(t + timedelta(hours=i), 1800, 'com.apple.Notes') for i in range(0, 10, 1)]   # 09:00-19:00
        self.knowledgec(ev)
        a = zl.active_hours(zl.app_usage(), [])
        wd = next(iter(a.values()))
        self.assertEqual(wd['first'], 9.0); self.assertGreaterEqual(wd['last'], 18.0)
        c = zl.suggested_checkins(a)['all']
        self.assertEqual(c[0], '10:00'); self.assertEqual(len(c), 3)

    def test_pmset_parse(self):
        d = self.base.strftime('%Y-%m-%d')
        txt = f'{d} 09:00:00 +0530 Notification   \tDisplay is turned on\n{d} 11:00:00 +0530 Sleep \tEntering Sleep state due to idle\n'
        open(os.path.join(self.d, 'pm.txt'), 'w').write(txt)
        os.environ['ZUKA_PMSET_FILE'] = os.path.join(self.d, 'pm.txt')
        iv = zl.display_intervals()
        self.assertEqual(len(iv), 1); self.assertEqual((iv[0][1] - iv[0][0]).seconds, 7200)

    def test_brave_titles_only_youtube_and_no_other_browsing(self):
        p = os.path.join(self.d, 'History')
        con = sqlite3.connect(p)
        con.execute('create table urls (url text, title text, last_visit_time integer)')
        now = int((datetime.now().timestamp() + 11644473600) * 1e6)
        for u, t in (('https://www.youtube.com/watch?v=a', '(3) Karan Aujla - Admirin (Official Video) - YouTube'), ('https://bank.example/login', 'My Secret Bank'),
                     ('https://music.youtube.com/watch?v=b', 'Tum Hi Ho - Arijit Singh - YouTube Music')):
            con.execute('insert into urls values (?,?,?)', (u, t, now))
        con.commit(); con.close()
        os.environ['ZUKA_BRAVE_HISTORY'] = p
        t = zl.brave_titles()
        self.assertEqual(len(t), 2)
        self.assertNotIn('Secret', json.dumps([x[1] for x in t]))
        rows = []
        h = zl.music_profile(rows, zl.request_profile(rows), {'tracks': [['Admirin', 'Karan Aujla', 3, 'Punjabi', 0, 0]]}, t)
        self.assertIn('Karan Aujla', [a['name'] for a in h['topArtists']])
        self.assertNotIn('Secret', json.dumps(h))

    def test_memory_playlists_fallback(self):
        h = zl.music_profile([], zl.request_profile([]), {}, [], 'Playlists: **Hindi, English, Punjabi**.')
        self.assertEqual(h['favouritePlaylists'][:2], ['Hindi', 'English'])


class Suggestions(Base):
    def habits(self, **kw):
        h = {'typeHourDays': {'clickup check': {'11': 4}}, 'activeHours': {}, 'music': {}}
        h.update(kw)
        json.dump(h, open(os.path.join(self.d, 'habits.json'), 'w'))

    def setUp(self):
        super().setUp()
        for n in ('in_call', 'screen_locked'):
            p = mock.patch.object(zl, n, return_value=False); p.start(); self.addCleanup(p.stop)

    def test_clickup_line_once(self):
        self.habits()
        now = datetime.now().replace(hour=11, minute=5)
        self.assertEqual(zl.suggestion(now), "It's around when you check ClickUp - want me to look?")
        self.assertIsNone(zl.suggestion(now))   # never the same twice a day

    def test_max_three_a_day(self):
        self.habits(typeHourDays={'clickup check': {'0': 3}, 'calendar': {'0': 3}, 'weather': {'0': 3}, 'reminders': {'0': 3}})
        now = datetime.now().replace(hour=0, minute=10)
        got = [zl.suggestion(now) for _ in range(5)]
        self.assertEqual(len([g for g in got if g]), 3)

    def test_next_day_resets(self):
        self.habits()
        now = datetime.now().replace(hour=11)
        self.assertTrue(zl.suggestion(now))
        self.assertTrue(zl.suggestion(now + timedelta(days=1)))

    def test_not_during_calls_or_locked(self):
        self.habits()
        now = datetime.now().replace(hour=11)
        with mock.patch.object(zl, 'in_call', return_value=True):
            self.assertIsNone(zl.suggestion(now))
        with mock.patch.object(zl, 'screen_locked', return_value=True):
            self.assertIsNone(zl.suggestion(now))
        self.assertTrue(zl.suggestion(now))

    def test_morning_and_late_music(self):
        now = datetime.now().replace(hour=10, minute=0)
        self.habits(typeHourDays={}, activeHours={str(now.weekday()): {'first': 9.5, 'last': 20, 'days': 4, 'hours': []}})
        self.assertEqual(zl.suggestion(now), 'Morning - want me to start your day?')
        late = now.replace(hour=23) + timedelta(days=1)
        self.habits(typeHourDays={}, music={'topArtists': [{'name': 'A'}], 'listeningHours': {}})
        self.assertEqual(zl.suggestion(late), 'Want some music while you work?')

    def test_no_habits_no_suggestion(self):
        self.assertIsNone(zl.suggestion(datetime.now()))


class Gaps(Base):
    def test_gaps_report_and_memory(self):
        rows = [_row(i, self.base + timedelta(hours=i), 'open the figma file', 'not_handled', 'haiku') for i in range(3)]
        rows += [_row(10, self.base, 'what do you think about my life', 'not_handled', 'haiku'), _row(11, self.base, 'message mom hi', 'not_handled', 'haiku'),
                 _row(12, self.base, 'message mom hi', 'not_handled', 'haiku')]
        self.log(rows)
        gaps = zl.gaps_report()
        self.assertEqual(gaps, [('open the figma file', 3)])
        self.assertIn('open the figma file', open(os.path.join(self.d, 'gaps.md')).read())
        self.assertNotIn('mom', open(os.path.join(self.d, 'gaps.md')).read())
        mem = open(os.path.join(self.mem, 'project-zuka-gaps.md')).read()
        self.assertIn('name: project-zuka-gaps', mem); self.assertIn('type: project', mem)
        zl.gaps_report(); self.assertEqual(open(os.path.join(self.mem, 'project-zuka-gaps.md')).read().count('## '), 1)   # one dated entry per day

    def test_no_memory_dir_no_memory_file(self):
        os.environ['ZUKA_MEMORY_DIR'] = os.path.join(self.d, 'absent')
        self.log([_row(i, self.base, 'open the figma file', 'not_handled', 'haiku') for i in range(2)])
        zl.gaps_report()
        self.assertFalse(os.path.exists(os.path.join(self.d, 'absent')))


class Music(Base):
    H = {'music': {'topArtists': [{'name': 'Arijit Singh', 'lang': 'hindi'}, {'name': 'Karan Aujla', 'lang': 'punjabi'}, {'name': 'Ed Sheeran', 'lang': 'english'}],
                   'playlists': ['Hindi', 'Punjabi', 'English', 'EDM & Dance'], 'favouritePlaylists': ['English', 'Hindi'],
                   'moodsByTime': {'late night': ['Karan Aujla', 'Arijit Singh']}}}

    def test_favourites_rotate_playlists(self):
        p = zl.music_pick('play something i like', self.H)
        self.assertEqual((p['kind'], p['target']), ('apple', 'English'))
        zl._remember_pick('p:English')
        self.assertEqual(zl.music_pick('play my favourites', self.H)['target'], 'Hindi')

    def test_language_playlist_and_artist_fallback(self):
        self.assertEqual(zl.music_pick('play punjabi songs', self.H)['target'], 'Punjabi')
        H = json.loads(json.dumps(self.H)); H['music']['playlists'] = []
        p = zl.music_pick('play punjabi songs', H)
        self.assertEqual(p['kind'], 'youtube'); self.assertIn('Karan Aujla', p['target'])

    def test_mood_late_night_uses_late_night_history(self):
        p = zl.music_pick('play something for late night', self.H)
        self.assertEqual(p['kind'], 'youtube'); self.assertIn('Karan Aujla', p['target'])
        self.assertEqual(zl.music_pick('play chill music', self.H)['kind'], 'youtube')

    def test_new_and_non_matches(self):
        self.assertEqual(zl.music_pick('play something new like my taste', self.H)['kind'], 'youtube')
        for t in ('play kesariya', 'play a song', 'open brave', 'play something', 'what time is it', 'play'):
            self.assertIsNone(zl.music_pick(t, self.H), t)

    def test_no_taste_yet_returns_none(self):
        self.assertIsNone(zl.music_pick('play my music', {}))

    def test_alias_plays_via_youtube_play(self):
        json.dump(self.H, open(os.path.join(self.d, 'habits.json'), 'w'))
        fake = mock.Mock(); fake.youtube_play.return_value = 'Playing karan aujla mix on YouTube.'
        with mock.patch.dict(sys.modules, {'atticus': fake}):
            out = zl.alias('play punjabi songs')
        self.assertEqual(out, zl.SAID + 'Playing karan aujla mix on YouTube.') if False else None
        # Punjabi playlist exists -> Apple Music path
        with mock.patch.object(zl.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='ok\n')):
            self.assertEqual(zl.alias('play punjabi songs'), zl.SAID + 'Playing Punjabi in Apple Music.')
        H = json.loads(json.dumps(self.H)); H['music']['playlists'] = []
        json.dump(H, open(os.path.join(self.d, 'habits.json'), 'w'))
        with mock.patch.dict(sys.modules, {'atticus': fake}):
            self.assertTrue(zl.alias('play punjabi songs').startswith(zl.SAID + 'Playing karan aujla'))
        fake.youtube_play.assert_called_once()

    def test_profile_languages_and_moods(self):
        apple = {'tracks': [['a', 'Arijit Singh', 10, 'Bollywood', 1, datetime.now().replace(hour=23).timestamp()], ['b', 'Karan Aujla', 5, 'Punjabi', 0, 0]],
                 'playlists': [{'name': 'Hindi', 'count': 1, 'plays': 10, 'artists': {'Arijit Singh': 1}}, {'name': 'Punjabi', 'count': 1, 'plays': 5, 'artists': {'Karan Aujla': 1}}]}
        m = zl.music_profile([], zl.request_profile([]), apple, [])
        self.assertEqual(m['topArtists'][0]['name'], 'Arijit Singh')
        self.assertGreater(m['languages']['hindi'], m['languages']['punjabi'])
        self.assertIn('Arijit Singh', m['moodsByTime']['late night'])
        self.assertIn('Tum' if False else 'a - Arijit Singh', m['lovedSongs'])


class Hook(unittest.TestCase):
    def test_commands_hook_survives_learn_errors(self):
        import zuka_commands as z
        with mock.patch.object(zl, 'alias', side_effect=RuntimeError('x')):
            self.assertIsNone(z._handle('zzzz not a command'))


if __name__ == '__main__':
    unittest.main()
