"""Phrase sweep: 300+ ways the owner actually talks (Indian English, fillers like "can you", "I want you to", "once", "na", "yaar", trailing "for me"),
across messages, music, apps, ClickUp/trackers, reminders/timers, Mac controls, time/weather/calc, day start/end and small talk.
Every phrase goes through atticus.fast() with all side effects mocked. One that falls to Claude (fast() falsy AND the local brain says not chatty), or
that only the local chat brain would "answer" although it is clearly an action, is a routing bug. Names here are neutral fixtures."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atticus  # noqa: E402
import zuka_apps  # noqa: E402
import zuka_chat  # noqa: E402
import zuka_commands as z  # noqa: E402
import zuka_learn  # noqa: E402
import zuka_more  # noqa: E402
import zuka_msg  # noqa: E402
import zuka_work  # noqa: E402

MESSAGES = [   # WhatsApp / Slack / Discord / Gmail: read + send (a send only drafts and asks "Send ...?")
    'any messages', 'Any messages yaar', 'do I have any messages', 'did anyone message me', 'who messaged me', 'who messaged me on WhatsApp',
    'Read me out WhatsApp once.', 'read my WhatsApp', 'read my WhatsApp messages', 'can you read my WhatsApp messages for me', 'I want you to read my WhatsApp messages',
    'read WhatsApp messages', "what's on WhatsApp", 'any new WhatsApp messages', 'any WhatsApp messages na', 'check WhatsApp', 'check my WhatsApp please',
    'what did Athar say', 'what did Athar say on WhatsApp', "read Athar's message", 'did Athar message me', 'did Sam reply', 'any message from Alex', 'read the last message from Chris',
    'I want you to open WhatsApp', 'open WhatsApp', 'open WhatsApp web', 'can you open WhatsApp for me', 'please open WhatsApp once',
    'read my Slack', 'read Slack messages', 'any Slack DMs', 'any new messages on Slack', 'what is on Slack', 'check Slack for me', 'who messaged me on Slack', 'do I have anything on Slack',
    'read Discord', 'read my Discord messages', 'any Discord DMs', 'check Discord', 'what is on Discord', 'who messaged me on Discord', 'any new messages on Discord please',
    'open Slack', 'open Discord', 'open my Slack for me',
    'check my Gmail', 'read my emails', 'any new emails', 'do I have any new mail', 'who emailed me', 'read my Gmail', 'any unread mail', 'how many unread emails do I have', 'check my inbox',
    'check LinkedIn', 'who messaged me on LinkedIn',
    'Can you message Athar and tell him that I am working', 'message Athar I am working', 'message Athar and tell him I am working', 'I want you to text Athar and say I am working',
    'send Athar a message saying I am working', 'send a message to Athar saying I am working', 'tell Athar on WhatsApp that I am working', 'tell Athar I am working',
    'reply to Athar saying okay', 'reply to Sam I am on my way', 'text Sam I will be late', 'text Alex saying call me', 'whatsapp Chris that I reached', 'WhatsApp Sam I am coming',
    'message Chris on Slack the deck is done', 'message Chris on Discord saying hi', 'slack Chris that I am in a meeting', 'tell Chris on Slack I am running late',
    'message mom and tell her I will call later', 'text mom saying I reached home', 'send Sam a text saying thanks yaar',
]
MUSIC = [
    'play kesariya', 'play Kesariya on YouTube', 'play Ake on Spotify', 'play Ake', 'play Blinding Lights by The Weeknd', 'play a song by Arijit Singh', 'play Arijit Singh songs',
    'play the latest Arijit Singh song', 'play the latest Diljit song on YouTube', 'play latest Punjabi songs', 'play something', 'play a song', 'play some music', 'put on some music',
    'I want you to play a song', 'can you play a song for me', 'play a song na', 'just play something yaar', 'play my music',
    'open YouTube and play Tum Hi Ho', 'play Tum Hi Ho on YouTube Music', 'play Shape of You on YT Music', 'play Levitating on Apple Music', 'play Hanuman Chalisa on YouTube',
    'play Believer on Spotify', 'play my Liked Songs on Spotify', 'play Chill playlist on Spotify', 'queue Kesariya', 'add Kesariya to the queue', 'play Kesariya next',
    'skip', 'skip this song', 'next song', 'next', 'play the next song', 'previous song', 'go to the previous song', 'play it again', 'pause', 'pause the music', 'stop the music', 'resume the music',
    'continue the music', 'resume', 'louder', 'make it louder', 'a bit louder', 'turn the volume up', 'volume down', 'turn the volume down a bit', 'quieter', 'turn it up', 'turn it down', 'set the volume to 50',
    'volume to 30 percent', 'mute', 'unmute', 'what is playing', 'what song is this', 'who sings this', 'play more like this', 'like this song', 'shuffle my music',
    'play the latest English song', 'play a Hindi song', 'play lo-fi', 'play some lofi beats for me', 'play romantic songs', 'play workout music', 'play something relaxing',
    'play Daft Punk on Spotify', 'play Imagine Dragons on YouTube Music', 'play AP Dhillon latest song', 'play the new Taylor Swift song',
]
APPS = [
    'open Brave', 'open Premiere', 'open Premiere Pro for me', 'I want you to open Chrome', 'can you open Safari', 'open Finder', 'open Notes', 'open the calculator', 'open Spotify',
    'launch Slack', 'start Discord', 'open Terminal', 'open System Settings', 'open Activity Monitor', 'open ClickUp', 'open Gmail', 'open LinkedIn', 'open YouTube', 'open Google Drive', 'open ChatGPT',
    'open Photoshop yaar', 'open Mail', 'open Calendar', 'open Messages', 'open Music', 'open Zoom', 'open Capcut',
    'close Brave', 'close Spotify', 'quit Chrome', 'quit Premiere', 'close Slack', 'close the calculator', 'close Notes please', 'can you close Safari',
    'switch to Brave', 'switch to Premiere', 'go to Finder', 'switch to Slack', 'hide Spotify', 'hide Brave', 'hide this app', 'minimize this window', 'maximize this window', 'full screen',
    'quit all apps', 'close all apps', 'close all the running applications', 'close everything', 'quit everything yaar', 'close all apps except Brave', 'hide all other windows',
    'show the desktop', 'next window', 'close this window', 'close this tab', 'new tab', 'open a new tab', 'reload the page', 'go back', 'scroll down',
    'move this window to the left', 'snap Brave to the right', 'open the downloads folder', 'open my desktop', 'open documents',
]
WORK = [
    'any new tasks on ClickUp', "what's on my ClickUp", 'my ClickUp tasks', 'any new ClickUp tasks for me', 'anything new on ClickUp', 'check ClickUp', 'read my ClickUp',
    'any new scripts on ClickUp', 'what tasks do I have', 'what is on my plate',
    'open the takedown tracker', 'open winning ads tracker', 'update on the takedown tracker', 'winning ads tracker update', 'how is the takedown tracker', 'show me the winning ads tracker',
    'new task 501 sample ad', 'start my day', 'start my work', 'lets start work', 'good morning lets begin', 'lets edit', 'edit mode', 'export check', 'how many exports', 'check exports',
    'what is my next meeting', 'when is my next meeting', 'what is on my calendar today', 'any meetings today', 'my schedule today',
    'done for the day', 'we are done for the day', 'I am done for today', 'call it a day', 'wrap up for the day', 'that is all for today close everything', 'shut down the mac',
    'summarize my day', 'what did I do today', 'my screen time', 'how long was I on Instagram today',
]
REMIND = [
    'remind me tomorrow', 'remind me in 10 minutes to check the oven', 'remind me in an hour to call mom', 'remind me to drink water in 30 minutes', 'I want you to remind me tomorrow that I have to call Sam',
    'remind me at 6 pm to stretch', 'remind me tomorrow at 9 am to send the invoice', 'remind me tonight to charge my phone', 'set a reminder for 5 pm', 'set a reminder to call Alex tomorrow',
    'can you remind me in 5 minutes', 'remind me in half an hour to eat', 'remind me tomorrow morning to pay the bill', 'cancel my reminder', 'cancel all reminders', 'delete the last reminder',
    'set a timer for 10 minutes', 'timer for 5 minutes', 'start a 20 minute timer', 'set a timer for 30 seconds', 'set a 25 minute timer for me', 'set a timer of 2 hours',
    'set an alarm for 7 am', 'wake me up at 6 30', 'set an alarm for 6 am tomorrow', 'alarm at 5 pm', 'set alarm for 8 am please',
]
MAC = [
    'volume up', 'make the volume higher', 'set volume to 70', 'brightness up', 'brightness down', 'turn the brightness up', 'make the screen brighter', 'dim the screen', 'set brightness to 50 percent',
    'turn off the wifi', 'turn wifi on', 'turn on the wifi please', 'wifi off', 'switch off wifi', 'turn on bluetooth', 'turn bluetooth off', 'bluetooth on',
    'turn on do not disturb', 'turn off do not disturb', 'do not disturb on', 'enable focus mode', 'turn off focus', 'put on DND',
    'take a screenshot', 'take a screenshot of an area', 'screenshot', 'lock the screen', 'lock my mac', 'lock the computer', 'turn off the screen', 'put the mac to sleep',
    'turn on dark mode', 'switch to light mode', 'what is my battery', 'how much battery is left', 'is my mac charging', 'how much storage do I have left', 'what is my IP address',
    'what wifi am I on', 'open system settings', 'show hidden files', 'mute the mic', 'turn on night shift', 'keep my mac awake',
    'what is on my clipboard', 'copy this text hello there', 'take a note buy milk', 'note to self call the bank', 'open the latest download', 'find a file named invoice',
]
INFO = [
    'what time is it', 'what is the time', 'what is the time now', 'time in London', 'what time is it in New York', 'what is the date', 'what day is it today', 'what is todays date',
    'what is the weather', 'whats the weather like', 'is it going to rain', 'will it rain tomorrow', 'weather tomorrow', 'how hot is it outside', 'what is the temperature', 'weather in Mumbai',
    'what is two plus two', 'what is 15% of 2400', 'calculate 45 times 12', '120 divided by 8', 'what is 18 percent of 650', 'square root of 144', 'what is 7 times 8',
    'convert 10 km to miles', 'convert 100 dollars to rupees', 'how much is 50 euros in rupees', 'convert 5 feet to cm', '20 pounds to dollars', 'what is the dollar to rupee rate',
    'how many days until Diwali', 'capital of France', 'who is Elon Musk', 'define serendipity', 'spell necessary', 'flip a coin', 'roll a dice',
]
TALK = [
    'hello', 'hi Zuka', 'hey Zuka', 'good morning', 'good evening', 'how are you', 'how are you doing', 'thank you', 'thanks yaar', 'thanks a lot', 'who are you', 'what is your name',
    'can you hear me', 'are you there', 'testing', 'test one two', 'is everything okay', 'what can you do', 'good night', 'bye', 'that is all', 'no thanks', 'nothing',
    'give me a caption idea', 'give me a hook idea for a copper bottle ad', 'tell me a joke', 'I am bored', 'you are awesome', 'how is your day',
]
CATS = dict(messages=MESSAGES, music=MUSIC, apps=APPS, work=WORK, reminders=REMIND, mac=MAC, info=INFO, talk=TALK)
ALL = [p for ps in CATS.values() for p in ps]
CHAT_OK = set(TALK) | {'what is the weather', 'capital of France', 'who is Elon Musk', 'define serendipity', 'how many days until Diwali'}   # knowledge questions the local brain may answer   # small talk and ideas may be answered by the local brain; everything else is an action and must run on the Mac

# Genuinely Claude's (real writing, research, multi-step unknowns): none of the above should end up here, but these long asks do.
CLAUDE_ONLY = ['write me an email to the client about the delay', 'research the top ten competitor ads this week and summarise them', 'edit this video and add captions',
               'plan my whole week of content and write the scripts', 'draft a long reply to this message', 'write a script for a 30 second ad']


def sweep():
    """-> (free list, chat-only list, claude list) for the 300+ phrases."""
    free, chat, claude = [], [], []
    for p in ALL:
        r = atticus.fast(p)
        (free if r else chat if zuka_chat.chatty(p) else claude).append(p)
    return free, chat, claude


class Sweep(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        ok = mock.Mock(returncode=0, stdout='80%; charging', stderr='')
        wa = json.dumps({'rs': 'complete', 'len': 3000, 'n': 2, 'items': [
            {'name': 'Athar', 'snippet': 'are you coming?', 'unread': True, 'time': '7:40', 'me': False}, {'name': 'Mom', 'snippet': 'call me', 'unread': True, 'time': '7:12', 'me': False}]})
        patches = [mock.patch.object(z, 'PENDING', os.path.join(d, 'p.json')), mock.patch.object(z, 'SHUTDOWN_FILE', os.path.join(d, 's.json')),
                   mock.patch.object(z, 'OFFER_FILE', os.path.join(d, 'o.json')), mock.patch.object(z, 'VOICE_PICK', os.path.join(d, 'v.json')),
                   mock.patch.object(zuka_msg, 'SEND_FILE', os.path.join(d, 'send.json')), mock.patch.object(z, 'REMINDERS', os.path.join(d, 'r.json')),
                   mock.patch.dict(os.environ, {'ATTICUS_DIR': d}), mock.patch.object(atticus, 'LAST', os.path.join(d, 'last')),
                   mock.patch.object(z, '_osa', return_value=''), mock.patch.object(z, '_run', side_effect=lambda a, timeout=10, inp=None: mock.Mock(returncode=0, stdout='Filesystem Size Used Avail Cap\n/dev/disk3 494G 300G 150G 67% /' if a[:1] == ['df'] else '80%; charging', stderr='')), mock.patch.object(z, '_get_text', return_value='Clear +20°C'),
                   mock.patch.object(z, '_spawn', return_value=None), mock.patch.object(z, '_running_apps', return_value=[('Brave Browser', 'com.brave.Browser'), ('Spotify', 'com.spotify.client'), ('Adobe Premiere Pro', 'com.adobe.PremierePro')]),
                   mock.patch.object(z, '_tab_exec', return_value=wa), mock.patch.object(z, '_browser', return_value='Brave Browser'),
                   mock.patch.object(z, '_focus_or_open', return_value=True), mock.patch.object(z, '_open_browser', return_value=True),
                   mock.patch.object(zuka_msg.time, 'sleep'), mock.patch('time.sleep', return_value=None),
                   mock.patch('subprocess.run', return_value=ok), mock.patch('subprocess.Popen', return_value=mock.Mock(communicate=lambda *a, **k: ('', ''))),
                   mock.patch('urllib.request.urlopen', side_effect=OSError('no network in tests')),
                   mock.patch.object(atticus, 'show', return_value='opened x'), mock.patch.object(atticus, 'youtube_tab', return_value=True),
                   mock.patch.object(atticus, 'quit_app', return_value=True), mock.patch.object(atticus, 'app_running', return_value=True),
                   mock.patch.object(atticus, 'osa', return_value=''), mock.patch.object(atticus, 'app_id', lambda a: 'com.test.' + a.lower().replace(' ', '')),
                   mock.patch.object(atticus, 'say', return_value=None), mock.patch.object(atticus, 'tip', return_value=None), mock.patch.object(atticus, 'free_focus', return_value=None),
                   mock.patch.object(atticus, 'place', return_value='ok'), mock.patch.object(atticus, 'hands', return_value=('ok', True)), mock.patch.object(atticus, 'menu_bar_click', return_value=None),
                   mock.patch.object(atticus, 'hands_map', return_value={'nodes': []}), mock.patch.object(atticus, 'spotify_item', return_value=None),
                   mock.patch.object(atticus, 'installed_apps', return_value=['Safari', 'Finder', 'Spotify', 'Notes', 'Google Chrome', 'Brave Browser', 'Mail', 'Messages', 'Calendar', 'Music',
                                                                           'System Settings', 'Activity Monitor', 'Adobe Premiere Pro', 'Slack', 'Discord', 'Calculator', 'Terminal', 'ClickUp',
                                                                           'Adobe Photoshop', 'zoom.us', 'CapCut', 'ChatGPT', 'Zoom']),
                   mock.patch.object(zuka_apps, '_run', return_value=mock.Mock(returncode=1, stdout='', stderr='')), mock.patch.object(zuka_apps, 'hands_read', return_value=None),
                   mock.patch.object(zuka_apps, 'chat_status', return_value={'app': 'Slack', 'badge': 2, 'unread': ['Alex'], 'dms': ['Alex: lunch?'], 'servers': []}),
                   mock.patch.object(zuka_more, '_yt_exec', return_value=('music.youtube.com', 'Blinding Lights')),
                   mock.patch.object(zuka_work, '_clickup', return_value='Nothing new for you in ClickUp, J.'),
                   mock.patch.object(zuka_work, '_trackers', return_value={'takedown': 'https://claude.ai/artifact/AAA', 'winning': 'https://claude.ai/artifact/BBB'}),
                   mock.patch.object(zuka_work, '_focus_tab', return_value=True), mock.patch.object(zuka_work, '_tracker_text', return_value='Takedowns this week 42\nTop editor Sam 19'),
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

    def test_the_sweep_has_over_300_phrases(self):
        self.assertGreaterEqual(len(ALL), 300)
        self.assertEqual(len(ALL), len(set(ALL)))

    def test_nothing_falls_to_claude_and_no_action_is_left_to_chat(self):
        free, chat, claude = sweep()
        print(f"\nSPOKEN VARIETY: {len(ALL)} phrases: {len(free)} free on the Mac, {len(chat)} chat-only, {len(claude)} to Claude")
        self.assertEqual(claude, [], 'these fall to Claude: ' + '; '.join(claude))
        self.assertEqual([p for p in chat if p not in CHAT_OK], [], 'actions the chat brain would wrongly "answer": ' + '; '.join(p for p in chat if p not in CHAT_OK))

    def test_long_writing_and_research_still_go_to_claude(self):
        for p in CLAUDE_ONLY:
            self.assertFalse(atticus.fast(p), p)
            self.assertFalse(zuka_chat.chatty(p), p)

    def test_no_message_phrase_ever_sends(self):
        sent = []
        with mock.patch.object(zuka_msg, '_wa_send', side_effect=lambda p: sent.append(p)), mock.patch.object(zuka_msg, '_app_send', side_effect=lambda p: sent.append(p)):
            for p in MESSAGES: atticus.fast(p)
        self.assertEqual(sent, [])


if __name__ == '__main__':
    unittest.main()
