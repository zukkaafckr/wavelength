"""Things the owner actually said that must stay free (no Claude). A change that sends one of these to Claude fails here first."""
import os
import tempfile
import unittest
from unittest import mock

import atticus
import zuka_chat
import zuka_commands as z
import zuka_learn
import zuka_more
import zuka_work

FREE = [   # exactly as said (from the request log and conversation), each must be answered on the Mac
    'Remind me tomorrow', 'I want you to remind me tomorrow that I have to call mom', 'remind me in 10 minutes to check the oven',
    'do you have any messages', 'did anyone message me', 'check my messages please', 'who messaged me on linkedin', 'check linkedin',
    'Checking if that is working.', 'How are you?', 'Is everything OK on the cloud?',
    'I want to check if you can access the Mac and everything is right.',
    'Just checking is everything okay and this is the first time we are setting up.',
    'what is two plus two', 'what is 15% of 2400', 'what time is it', 'what is the weather',
    'Just open YouTube for me and play a song.', 'open youtube and play arijit singh', 'play kesariya', 'play a song',
    'open brave', 'Open Brave.', 'open calculator', 'close calculator',
    'close all the running applications we are done for the day', 'close all apps',
    'convert 10 km to miles', 'time in london', 'what is my battery', 'voice options', 'try the jarvis voice',
    # media: skip / again / similar / like on Music, Spotify or the YouTube tab
    'skip', 'next', 'previous', 'play it again', 'replay', 'go back', 'play more like this', 'play similar songs', 'more like this', 'play songs like this',
    'add this to my playlist', 'like this song', 'save this song', 'love this song', 'add this to my favourites',
    # ClickUp app reader, weather tomorrow, reminders, currency, screen time, day summary, trackers
    'any new tasks on ClickUp', "what's on my ClickUp", 'my ClickUp tasks', 'anything new on ClickUp',
    'weather tomorrow', 'will it rain tomorrow', "what's tomorrow's weather", 'is it going to rain tomorrow', 'forecast for tomorrow',
    'cancel my reminder', 'delete the reminder', 'cancel all reminders', 'cancel the last reminder',
    'convert 100 dollars to rupees', 'how much is 50 euros in rupees', '20 pounds to dollars', 'what is the dollar to rupee rate',
    'my screen time', 'screen time today', 'how long was I on Instagram today', 'what is my screen time', 'how long was I on Premiere today',
    'summarize my day', 'what did I do today', 'recap my day', 'how was my day',
    'open the takedown tracker', 'open winning ads tracker', 'open the winning ads tracker',
    'update on HOA takedown tracker', 'winning ads tracker update', 'takedown tracker update',
]
IDEAS = ['give me a caption idea', 'give me a hook idea for a copper bottle ad', 'give me a few caption ideas for my reel', 'suggest a name for my channel']   # the local brain answers these (chatty)


class OwnerPhrases(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        patches = [mock.patch.object(z, 'PENDING', os.path.join(d, 'p.json')), mock.patch.object(z, 'SHUTDOWN_FILE', os.path.join(d, 's.json')),
                   mock.patch.object(z, 'OFFER_FILE', os.path.join(d, 'o.json')), mock.patch.object(z, 'VOICE_PICK', os.path.join(d, 'v.json')),
                   mock.patch.object(z, '_osa', return_value=''), mock.patch.object(z, '_run', return_value=mock.Mock(returncode=0, stdout='80%; charging', stderr='')),
                   mock.patch.object(z, '_get_text', return_value='Clear +20°C'),
                   mock.patch.object(z, '_spawn', return_value=None), mock.patch.object(z, '_running_apps', return_value=[]),
                   mock.patch.object(atticus, 'show', return_value='opened x'), mock.patch.object(atticus, 'youtube_tab', return_value=True),
                   mock.patch.object(atticus, 'quit_app', return_value=True), mock.patch.object(atticus, 'app_running', return_value=True),
                   mock.patch('urllib.request.urlopen', side_effect=OSError),
                   mock.patch.object(atticus.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')),
                   mock.patch.object(atticus, 'osa', return_value=''), mock.patch.object(atticus, 'app_id', return_value='com.example.app'),
                   mock.patch.object(z, 'REMINDERS', os.path.join(d, 'r.json')), mock.patch.dict(os.environ, {'ATTICUS_DIR': d}),   # own cache dir: FX rates are cached 6 h
                   
                   mock.patch.object(zuka_more, '_yt_exec', return_value=('music.youtube.com', 'Blinding Lights')),   # a YouTube Music tab is open
                   mock.patch.object(zuka_work, '_clickup', return_value='Nothing new for you in ClickUp, J.'),
                   mock.patch.object(zuka_work, '_trackers', return_value={'takedown': 'https://claude.ai/artifact/AAA', 'winning': 'https://claude.ai/artifact/BBB'}),
                   mock.patch.object(zuka_work, '_focus_tab', return_value=True), mock.patch.object(z, '_open_browser', return_value=True),
                   mock.patch.object(zuka_work, '_tracker_text', return_value='Takedowns this week 42\nCopies reported 57\nTop editor Sam 19'),
                   mock.patch.object(zuka_chat, 'summarize', return_value=None),
                   mock.patch.object(zuka_learn, 'usage_today', return_value=({'com.brave.browser': 9000, 'com.adobe.Premiere': 4000}, True)),
                   mock.patch.object(zuka_learn, 'today_tasks', return_value=[('play kesariya', 'music'), ('what is the weather', 'weather')]),
                   mock.patch.object(z, '_get_json', side_effect=self._json)]
        for p in patches: p.start(); self.addCleanup(p.stop)

    @staticmethod
    def _json(url, timeout=4):
        if 'er-api' in url: return {'rates': {'INR': 83.2, 'USD': 1.0, 'EUR': 0.92, 'GBP': 0.79}}
        if 'wttr.in' in url and 'j1' in url: return {'weather': [{}, {'maxtempC': '31', 'mintempC': '24', 'hourly': [{'chanceofrain': '10', 'weatherDesc': [{'value': 'Partly cloudy'}]}] * 8}]}
        return {'current_condition': [{}]}

    def test_every_idea_request_goes_to_the_local_brain(self):
        self.assertEqual([p for p in IDEAS if not zuka_chat.chatty(p)], [])
        self.assertFalse(zuka_chat.chatty('write me an email about the shoot'))

    def test_every_owner_phrase_is_free(self):
        missed = [p for p in FREE if not atticus.fast(p)]
        self.assertEqual(missed, [], 'these went to Claude: ' + '; '.join(missed))


class NewFreeBehaviour(OwnerPhrases):
    """What the free answers actually do (the FREE list above only proves they never reach Claude)."""
    test_every_owner_phrase_is_free = test_every_idea_request_goes_to_the_local_brain = None   # already run by the parent class
    def test_skip_and_replay_drive_the_playing_app(self):
        calls = []
        z._osa.side_effect = lambda sc, t=8: calls.append(sc) or ('playing' if 'player state' in sc else '')
        self.assertEqual(atticus.fast('skip'), 'Next one, J.')
        self.assertEqual(atticus.fast('previous'), 'Going back, J.')
        self.assertEqual(atticus.fast('play it again'), 'From the top, J.')
        self.assertTrue(any('to next track' in c for c in calls) and any('to previous track' in c for c in calls))
        self.assertTrue(any('set player position to 0' in c for c in calls))

    def test_similar_on_music_plays_the_artist_and_on_youtube_a_mix(self):
        z._osa.side_effect = lambda sc, t=8: 'playing' if 'player state' in sc else 'The Weeknd' if 'artist of current track' in sc else ''
        self.assertEqual(atticus.fast('play more like this'), 'Playing more by The Weeknd, J.')
        z._osa.side_effect = None; z._osa.return_value = ''
        with mock.patch.object(atticus, 'youtube_play', return_value='Playing x') as yp:
            self.assertEqual(atticus.fast('play similar songs'), 'Playing a mix like Blinding Lights, J.')
            yp.assert_called_once_with('Blinding Lights mix', music=True)

    def test_like_on_youtube_clicks_the_button(self):
        with mock.patch.object(zuka_more, '_players', return_value=[]), mock.patch.object(zuka_more, '_yt_exec', return_value=('music.youtube.com', 'liked')):
            self.assertIn('Liked it on YouTube Music', atticus.fast('like this song'))
        with mock.patch.object(zuka_more, '_players', return_value=[]), mock.patch.object(zuka_more, '_yt_exec', return_value=('youtube.com/watch', 'already')):
            self.assertEqual(atticus.fast('save this song'), "You'd already liked it, J.")

    def test_reminders_cancel_latest_or_all(self):
        z._osa.return_value = 'rid1'
        atticus.fast('remind me in 10 minutes to check the oven')
        z._osa.return_value = 'rid2'
        atticus.fast('remind me in 20 minutes to call mom')
        z._osa.return_value = ''
        self.assertEqual(atticus.fast('cancel my reminder'), 'Cancelled your reminder to call mom, J.')
        self.assertIn('rid2', z._osa.call_args[0][0])
        atticus.fast('remind me in 30 minutes to stretch')   # id '' -> not logged, never cancelled by guess
        self.assertEqual(atticus.fast('cancel all reminders'), 'Cancelled your reminder to check the oven, J.')
        self.assertEqual(atticus.fast('cancel my reminder'), "I haven't set any reminders you could cancel, J.")

    def test_currency_cached_and_offline(self):
        with mock.patch.object(z, '_get_json', side_effect=self._json) as g:
            self.assertEqual(atticus.fast('convert 100 dollars to rupees'), '100 US dollars is about 8,320 rupees, J.')
            atticus.fast('convert 5 dollars to euros')
            self.assertEqual(g.call_count, 1)   # second ask is served from the 6 h cache
        with mock.patch.object(z, '_get_json', return_value=None):
            self.assertIsNone(z._fx_rates('EUR'))
            self.assertIsNone(atticus.fast('convert 100 euros to rupees'))

    def test_weather_tomorrow_rain_chance(self):
        d = {'weather': [{}, {'maxtempC': '28', 'mintempC': '22', 'hourly': [{'chanceofrain': '70', 'weatherDesc': [{'value': 'Light rain'}]}] * 8}]}
        with mock.patch.object(z, '_get_json', return_value=d):
            self.assertEqual(atticus.fast('will it rain tomorrow'), 'Probably, J. 70 percent chance of rain tomorrow, light rain.')
            self.assertEqual(atticus.fast('weather tomorrow'), "Tomorrow it'll be light rain, 22°C to 28°C, with a 70 percent chance of rain, J.")

    def test_unreadable_tracker_falls_to_claude(self):
        with mock.patch.object(zuka_work, '_tracker_text', return_value=''):
            self.assertIsNone(atticus.fast('winning ads tracker update'))

    def test_tracker_summary_uses_the_local_brain(self):
        with mock.patch.object(zuka_chat, 'summarize', return_value='42 takedowns this week.') as sm:
            self.assertEqual(atticus.fast('update on HOA takedown tracker'), '42 takedowns this week.')
            self.assertIn('Takedowns this week 42', sm.call_args[0][0])

    def test_screen_time_unreadable(self):
        with mock.patch.object(zuka_learn, 'usage_today', return_value=({}, False)):
            self.assertIn("can't read Screen Time", atticus.fast('my screen time'))


if __name__ == '__main__':
    unittest.main()
