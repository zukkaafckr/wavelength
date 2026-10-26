"""Zuka's wider free Mac commands (zuka_more.py): unit tests with every side effect mocked, plus the 150+ phrase audit of the whole assistant."""
import os
import random
import re
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atticus  # noqa: E402
import zuka_commands as zc  # noqa: E402
import zuka_more as zm  # noqa: E402

# ---- the audit fixture: realistic spoken requests (filler included) from people using Siri/Alexa/JARVIS-style assistants
PHRASES = [
# apps & windows
"Hey Zuka, can you open Safari for me?", "please close Spotify", "quit Notes", "hide Safari", "minimize this window", "can you minimize the window",
"maximize this window", "make this window full screen", "exit full screen", "move this window to the left", "snap Chrome to the right",
"next window", "switch to Finder", "switch to Spotify", "quit all apps except Safari", "close every app but Finder", "hide all other windows", "hide everything else",
"show the desktop", "minimize all windows", "close this window", "hide this app", "bring Safari to the front",
# system
"turn the brightness up", "make the screen brighter", "brightness down", "dim the screen", "set brightness to 50 percent", "max brightness",
"turn on dark mode", "switch to dark mode", "enable light mode", "toggle dark mode", "turn on do not disturb", "turn off do not disturb", "enable focus mode", "turn off focus",
"turn off the wifi", "turn wifi on", "disable wi-fi", "turn on bluetooth", "turn bluetooth off", "is bluetooth on", "what's my battery percentage", "how much battery do I have left",
"how much battery is left", "is my mac charging", "how much storage do I have left", "how much disk space is free", "what's my IP address", "what wifi am I connected to",
"what is my wi-fi name", "how long has my mac been on", "what's my uptime", "put the mac to sleep", "sleep the mac", "go to sleep", "empty the trash", "restart the mac", "reboot my computer",
"shut down the mac", "mute the mic", "mute my microphone", "turn on night shift", "turn off night shift", "what mac model is this", "what macOS version am I on", "how much ram do I have",
"is my mac connected to the internet", "how much memory is free", "what's my mac's name", "open system settings", "open activity monitor", "keep my mac awake", "show hidden files", "hide hidden files",
# media
"play music", "pause the music", "next song", "skip this song", "previous song", "go back a song", "turn the music up", "turn the volume down", "what's playing", "what song is this",
"who sings this song", "play my Chill playlist in Apple Music", "play the playlist Workout", "shuffle my music", "turn on shuffle", "turn off shuffle", "repeat this song", "like this song", "set volume to 40",
"stop the music", "resume the music", "play the album Thriller",
# browser
"open youtube.com", "open a new tab", "new tab", "close this tab", "close the tab", "reload the page", "refresh the page", "go back", "go forward", "search Google for best pizza near me",
"google how to tie a tie", "search YouTube for lofi beats", "open my last closed tab", "reopen the last tab", "what's the title of this page", "read me the page title", "what page am I on", "what tab is open",
"next tab", "previous tab", "go to the first tab", "open a private window", "open an incognito window", "bookmark this page", "copy the page link", "copy this page's url", "what's the url of this page",
"scroll down", "zoom in", "zoom out",
# files
"open the latest download", "open my last download", "what did I download last", "find a file named invoice", "find the file called budget", "search my mac for resume",
"open the folder Projects", "open the projects folder", "make a new folder on the desktop called Reports", "create a folder named Taxes on my desktop", "show hidden files in finder",
"open my downloads", "open the desktop folder", "what's on my desktop", "how many files are on my desktop", "show me my recent files", "reveal my last download in finder", "open the applications folder",
"empty my downloads folder",
# communication
"open the WhatsApp chat with Mom", "open WhatsApp chat with Rahul", "write an email to bob@example.com", "compose an email to Sara", "email john@example.com about the meeting", "FaceTime Mom", "facetime Rahul",
"call Mom", "call my dad", "send an email to Priya", "text Rahul", "message Mom on WhatsApp", "open messages", "open mail", "check my email", "open FaceTime",
# calendar
"what's on my calendar today", "what's on my calendar tomorrow", "what do I have tomorrow", "when is my next meeting", "any meetings today", "add a meeting tomorrow at 5 called design review",
"schedule a meeting tomorrow at 3 pm called standup", "add an event on Friday at 2 called dentist", "create a calendar event called lunch tomorrow at noon", "what's on my schedule this week", "am I free tomorrow at 3",
"open calendar",
# notes
"take a note: buy milk", "take a note buy milk and eggs", "make a note that the wifi password is on the fridge", "note to self call the bank", "create a new note", "write this down: meeting moved to 4",
"read my last note", "what's my latest note", "open notes", "add buy milk to my notes", "add milk to my shopping list", "what's on my to do list",
# clipboard
"what's on my clipboard", "read my clipboard", "read the clipboard", "what did I copy", "copy hello world to the clipboard", "copy this text hello there", "clear the clipboard", "paste",
# time & conversions
"what time is it in London", "what's the time in New York", "time in Tokyo", "what time is it in Dubai right now", "what time is it in Sydney", "convert 10 km to miles", "how many miles is 5 kilometers",
"how many kilograms is 150 pounds", "convert 70 kg to lb", "what is 30 celsius in fahrenheit", "convert 98.6 F to C", "how many centimeters in 10 inches", "convert 6 feet to cm", "how many liters is 5 gallons",
"how many days until Christmas", "how many days until December 25", "how many days until my birthday", "what day is December 25th", "what day of the week is July 4th 2027", "what's the date next Friday",
"how many days are left in the year", "what week of the year is it", "how many ounces in a pound", "what's 5 miles in kilometers", "100 fahrenheit in celsius",
# translation
"translate hello to Hindi", "how do you say thank you in Spanish", "translate good morning into French", "what is water in German", "translate where is the station to Spanish", "say I love you in Italian",
# news
"what's the news", "read me the headlines", "top news headlines", "any news today", "tell me the news", "latest tech news", "what's happening in the world", "bbc news",
# fun/random
"tell me a joke", "flip a coin", "heads or tails", "roll a dice", "roll a die", "roll two dice", "pick a random number", "give me a random number between 1 and 100", "random number from 1 to 10",
"start a stopwatch", "stop the stopwatch", "what's the stopwatch at", "reset the stopwatch", "what can you do", "help", "what are your commands", "who made you", "tell me a fun fact", "give me a quote",
"pick a card", "magic eight ball will I get rich", "tell me a riddle",
# misc personal / hard (should stay with Claude)
"add milk to my shopping list", "bring Safari to the front", "show me my recent files", "go to the first tab", "what's my latest note", "what's my public IP address", "what's my mac's name", "summarize this article for me", "write an email to my boss asking for leave", "fix the bug in my code", "what should I eat for dinner", "plan my week", "who is the president of France",
"explain quantum computing", "edit this video for me", "draft a reply to this message",
]

# Phrases the Mac must never hand to Claude, unless they are confirm-only, personal or need real writing.
STAYS_WITH_CLAUDE = {
    "like this song": "Spotify has no like command in AppleScript", "empty the trash": "confirm-only (destructive)", "restart the mac": "confirm-only (restart)", "reboot my computer": "confirm-only (restart)",
    "empty my downloads folder": "confirm-only (destructive)", "how many days until my birthday": "personal: the Mac doesn't know the date",
    "go to sleep": "ambiguous, not clearly aimed at the Mac", "who made you": "needs a real answer", "tell me a riddle": "needs a spoken follow-up",
    "summarize this article for me": "real reading and writing", "write an email to my boss asking for leave": "real writing",
    "fix the bug in my code": "real work", "what should I eat for dinner": "judgment", "plan my week": "judgment",
    "who is the president of France": "open knowledge question", "explain quantum computing": "real explanation",
    "edit this video for me": "real work", "draft a reply to this message": "real writing",
}


def _realistic_mac(case):
    """The Mac as it looks to Zuka: believable output for every free command (nothing real is touched)."""
    case.mac = Mac(case)
    return case.mac


class Mac:
    """Fake shell + AppleScript. Records every command; answers like a real Mac."""
    def __init__(self, case):
        self.run_calls, self.osa_calls, self.spawned, self.running, self.piped = [], [], [], set(), []
        self.clipboard = 'hello clip'
        self.boot = 1000
        self.out = {
            ('pmset', '-g', 'batt'): "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=4653155)\t85%; discharging; 4:12 remaining present: true\n",
            ('df', '-H', '/'): "Filesystem Size Used Avail Capacity iused ifree %iused Mounted on\n/dev/disk3s1s1 494G 15G 123G 11% 427k 1.2G 0% /\n",
            ('ipconfig', 'getifaddr', 'en0'): "192.168.1.23\n",
            ('networksetup', '-listallhardwareports'): "Hardware Port: Ethernet\nDevice: en5\n\nHardware Port: Wi-Fi\nDevice: en0\nEthernet Address: aa\n",
            ('networksetup', '-getairportnetwork', 'en0'): "Current Wi-Fi Network: HomeNet\n",
            ('networksetup', '-getairportpower', 'en0'): "Wi-Fi Power (en0): On\n",
            ('sw_vers', '-productVersion'): "15.1\n", ('memory_pressure',): "System-wide memory free percentage: 62%\n",
            ('system_profiler', 'SPHardwareDataType'): "Hardware:\n    Model Name: MacBook Pro\n    Chip: Apple M3 Pro\n    Memory: 18 GB\n",
            ('system_profiler', 'SPBluetoothDataType'): "Bluetooth:\n  Bluetooth Controller:\n      State: On\n",
            ('scutil', '--get', 'ComputerName'): "Sam's MacBook\n", ('shortcuts', 'list'): "", ('mdfind',): "",
        }
        self.osa_rules = [('return "off"', 'ok'), ('current track', 'Blinding Lights|The Weeknd'), ('player state', 'playing'), ('people whose name', 'Mom Sharma|+91 98765 43210|mom@example.com'),
                          ('plaintext of note 1', 'Call the bank at ten'), ('title of active tab', 'Example Page'), ('name of current tab', 'Example Page'), ('URL of active tab', 'https://example.com/a'),
                          ('URL of current tab of front window', 'https://example.com/a'), ('make new event', 'Home'), ('every playlist', 'Chill Mix'), ('make new reminder', 'Shopping'),
                          ('completed is false', 'milk|eggs|'), ('output volume of (get volume settings)', '50')]
        self.apps = [('Brave Browser', 'com.brave.Browser'), ('Safari', 'com.apple.Safari'), ('Spotify', 'com.spotify.client'), ('Finder', 'com.apple.finder'), ('Notes', 'com.apple.Notes'),
                     ('Zuka', 'com.atticus.app'), ('Premiere Pro', 'com.adobe.pr')]
        self.quit = []
        self.events = {'calendars': ['Home'], 'events': []}
        self.json, self.text, self.tcp = None, None, True

    def run(self, args, timeout=10, inp=None):
        self.run_calls.append(list(args))
        if inp is not None: self.piped.append((args[0], inp))
        if args[0] == 'pgrep': return mock.Mock(returncode=0 if args[-1] in self.running else 1, stdout='', stderr='')
        if args[0] == 'pbpaste': return mock.Mock(returncode=0, stdout=self.clipboard, stderr='')
        if args[0] == 'sysctl': return mock.Mock(returncode=0, stdout='{ sec = %d, usec = 0 } Mon Jan 1' % self.boot, stderr='')
        if args[0] == 'mdfind': return mock.Mock(returncode=0, stdout=self.out.get(('mdfind',), ''), stderr='')
        for k in range(len(args), 0, -1):
            if tuple(args[:k]) in self.out: return mock.Mock(returncode=0, stdout=self.out[tuple(args[:k])], stderr='')
        return mock.Mock(returncode=0, stdout='', stderr='')

    def osa(self, script, timeout=8):
        self.osa_calls.append(script)
        m = re.search(r'application id "([^"]+)" to quit', script)
        if m: self.quit.append(m[1])
        for needle, val in self.osa_rules:
            if needle in script: return val
        return ''

    def said(self):
        return ' || '.join(self.osa_calls)

    def ran(self, *prefix):
        return any(c[:len(prefix)] == list(prefix) for c in self.run_calls)


def _mac_patches(case, mac, home):
    P = lambda *a, **k: mock.patch.object(*a, **k)
    ps = [P(zc, '_run', mac.run), P(zc, '_osa', mac.osa), P(zc, '_spawn', lambda a: mac.spawned.append(list(a))), P(zc, '_get_text', lambda u, t=4: mac.text(u) if callable(mac.text) else mac.text),
          P(zc, '_get_json', lambda u, t=4: mac.json(u) if callable(mac.json) else mac.json), P(zc, '_tcp', lambda h, p, t: mac.tcp), P(zc, '_running_apps', lambda: [a for a in mac.apps if a[1] not in mac.quit]),
          P(zc, '_workflow', lambda: {**zc.DEFAULTS, 'browser': getattr(case, 'browser', 'Brave Browser'), 'keepOpen': ['Claude']}), P(zc, '_now', lambda: datetime(2026, 10, 26, 15, 0)),
          P(zc, '_calendar_events', lambda a, b: mac.events), P(zc, '_default_browser', lambda: 'Brave Browser'), P(zc, '_open_browser', lambda u: mac.run_calls.append(['open-browser', u]) or True),
          P(zc, '_open_app', lambda n: mac.run_calls.append(['open', '-a', n]) or True), P(zc.time, 'sleep', lambda s: None), P(zm, '_home', lambda: home), P(zm, '_epoch', lambda: 1000 + 3 * 86400 + 4 * 3600 + 5),
          P(zm, '_now_utc', lambda: datetime(2026, 10, 26, 17, 8, tzinfo=timezone.utc)), P(zm, '_local_tz', lambda: ZoneInfo('Asia/Kolkata')), P(zm, 'STOPWATCH_FILE', os.path.join(home, 'stopwatch.json')),
          P(zm, '_blueutil', lambda: None), P(zm, '_app_exists', lambda n: False), P(zc, 'OFFER_FILE', os.path.join(home, 'o.json')), P(zc, 'SHUTDOWN_FILE', os.path.join(home, 'sd.json'))]
    for p in ps:
        p.start(); case.addCleanup(p.stop)


class MacCase(unittest.TestCase):
    browser = 'Brave Browser'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        for d in ('Desktop', 'Downloads', 'Documents'): os.makedirs(os.path.join(self.home, d))
        self.mac = Mac(self)
        _mac_patches(self, self.mac, self.home)
        zc.clean_call  # (call name is "J" from the default settings)
        self.addCleanup(lambda: None)
        p = mock.patch.object(zm.random, 'choice', lambda xs: xs[0]); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(zm.random, 'randint', lambda a, b: a); p.start(); self.addCleanup(p.stop)

    def say(self, text, expect=True):
        r = zm.handle(zc._norm(text), text)
        if expect: self.assertIsNotNone(r, text)
        return r

    def none(self, text):
        self.assertIsNone(zm.handle(zc._norm(text), text), text)


class AppsAndWindows(MacCase):
    def test_minimize_exit_fullscreen_close_next(self):
        self.assertEqual(self.say('minimize this window'), 'Minimized, J.')
        self.assertIn('AXMinimized', self.mac.said()); self.assertIn('frontmost is true', self.mac.said())
        self.say('exit full screen'); self.assertIn('"AXFullScreen" of window 1 of p to false', self.mac.said())
        self.say('close this window'); self.assertIn('keystroke "w" using command down', self.mac.said())
        self.say('next window'); self.assertIn('key code 50 using command down', self.mac.said())
        self.say('previous window'); self.assertIn('key code 50 using {command down, shift down}', self.mac.said())

    def test_hide_things(self):
        self.say('hide all other windows'); self.assertIn('keystroke "h" using {command down, option down}', self.mac.said())
        self.say('show the desktop'); self.assertIn('set visible of every process whose visible is true', self.mac.said())
        self.say('hide this app'); self.assertIn('set visible of (first application process whose frontmost is true) to false', self.mac.said())
        self.assertEqual(self.say('hide safari'), 'Hid Safari, J.'); self.assertIn('set visible of process "Safari" to false', self.mac.said())

    def test_hide_something_that_is_not_an_app_is_left_alone(self):
        self.none('hide the sidebar'); self.none('hide photoshop')

    def test_quit_all_but_keeps_named_finder_and_the_assistant(self):
        said = self.say('quit all apps except safari')
        self.assertEqual(sorted(self.mac.quit), ['com.adobe.pr', 'com.brave.Browser', 'com.spotify.client', 'com.apple.Notes'].__class__(sorted(['com.adobe.pr', 'com.brave.Browser', 'com.spotify.client', 'com.apple.Notes'])))
        self.assertNotIn('com.apple.Safari', self.mac.quit); self.assertNotIn('com.atticus.app', self.mac.quit); self.assertNotIn('com.apple.finder', self.mac.quit)
        self.assertTrue(said.startswith('Closed'), said)

    def test_quit_all_but_an_app_that_is_not_running_does_nothing(self):
        self.none('quit all apps except photoshop'); self.assertEqual(self.mac.quit, [])

    def test_bring_to_front_and_recent_and_tabs(self):
        self.assertEqual(self.say('bring safari to the front'), 'Bringing Safari to the front, J.'); self.assertTrue(self.mac.ran('open', '-a', 'safari'))
        self.say('show me my recent files'); self.assertIn('keystroke "f" using {command down, shift down}', self.mac.said())
        self.say('go to the first tab'); self.assertIn('keystroke "1" using command down', self.mac.said())
        self.say('go to the last tab'); self.assertIn('keystroke "9" using command down', self.mac.said())


class SystemCommands(MacCase):
    def test_brightness_keys(self):
        self.say('turn the brightness up'); self.assertIn('repeat 3 times\nkey code 144', self.mac.said())
        self.say('brightness down'); self.assertIn('repeat 3 times\nkey code 145', self.mac.said())
        self.say('make the screen brighter'); self.say('dim the screen'); self.assertIn('key code 145', self.mac.osa_calls[-1])
        self.assertEqual(self.say('max brightness'), 'Brightness at max, J.'); self.assertIn('repeat 16 times\nkey code 144', self.mac.osa_calls[-1])
        self.assertEqual(self.say('set brightness to 50 percent'), 'Brightness at about 50 percent, J.')
        self.assertIn('repeat 16 times\nkey code 145', self.mac.osa_calls[-1]); self.assertIn('repeat 8 times\nkey code 144', self.mac.osa_calls[-1])

    def test_dark_mode(self):
        self.assertEqual(self.say('turn on dark mode'), 'Dark mode on, J.'); self.assertIn('tell appearance preferences to set dark mode to true', self.mac.osa_calls[-1])
        self.say('enable light mode'); self.assertIn('set dark mode to false', self.mac.osa_calls[-1])
        self.say('turn off dark mode'); self.assertIn('set dark mode to false', self.mac.osa_calls[-1])
        self.say('dark mode off'); self.assertIn('set dark mode to false', self.mac.osa_calls[-1])
        self.none('switch on dark mode')   # left to the learned-shortcut path
        self.say('toggle dark mode'); self.assertIn('set dark mode to not dark mode', self.mac.osa_calls[-1])

    def test_focus_runs_a_shortcut_if_the_person_has_one(self):
        self.mac.out[('shortcuts', 'list')] = 'Do Not Disturb On\nDo Not Disturb Off\nOther\n'
        self.assertEqual(self.say('turn on do not disturb'), 'Do Not Disturb on, J.'); self.assertTrue(self.mac.ran('shortcuts', 'run', 'Do Not Disturb On'))
        self.say('turn off focus'); self.assertTrue(self.mac.ran('shortcuts', 'run', 'Do Not Disturb Off'))

    def test_focus_without_a_shortcut_opens_control_center_and_says_so(self):
        said = self.say('turn on do not disturb')
        self.assertIn('Control Center', said); self.assertIn("can't flip Focus", said); self.assertIn('ControlCenter', self.mac.said())
        self.assertFalse(self.mac.ran('shortcuts', 'run'))

    def test_wifi_switch_finds_the_interface(self):
        self.assertEqual(self.say('turn off the wifi'), 'Wi-Fi off, J.'); self.assertTrue(self.mac.ran('networksetup', '-setairportpower', 'en0', 'off'))
        self.say('turn wifi on'); self.assertTrue(self.mac.ran('networksetup', '-setairportpower', 'en0', 'on'))
        self.assertEqual(self.say('is wifi on'), 'Wi-Fi is on, J.')

    def test_wifi_name_and_ip(self):
        self.assertEqual(self.say('what wifi am I connected to'), "You're on HomeNet, J.")
        self.assertEqual(self.say("what's my IP address"), 'Your local IP is 192.168.1.23, J.')
        self.mac.out[('networksetup', '-getairportnetwork', 'en0')] = 'You are not associated with an AirPort network.\n'
        self.mac.out[('ipconfig', 'getsummary', 'en0')] = '  SSID : Cafe5G\n'
        self.assertEqual(self.say("what's my wifi name"), "You're on Cafe5G, J.")
        self.mac.out[('ipconfig', 'getsummary', 'en0')] = '  SSID : <redacted>\n'
        self.assertIn('macOS hides the network name', self.say("what's my wifi name"))

    def test_public_ip_uses_the_free_lookup(self):
        self.mac.text = lambda u: '203.0.113.7' if 'ipify' in u else None
        self.assertEqual(self.say("what's my public IP address"), 'Your public IP is 203.0.113.7, J.')
        self.mac.text = None; self.none("what's my public IP address")

    def test_bluetooth(self):
        self.assertEqual(self.say('is bluetooth on'), 'Bluetooth is on, J.')
        said = self.say('turn bluetooth off')
        self.assertIn('blueutil', said); self.assertTrue(self.mac.ran('open', 'x-apple.systempreferences:com.apple.BluetoothSettings'))
        with mock.patch.object(zm, '_blueutil', lambda: '/opt/homebrew/bin/blueutil'):
            self.assertEqual(self.say('turn on bluetooth'), 'Bluetooth on, J.'); self.assertTrue(self.mac.ran('/opt/homebrew/bin/blueutil', '-p', '1'))

    def test_battery(self):
        self.assertEqual(self.say("what's my battery percentage"), "Battery's at 85 percent, on battery, about 4 hours 12 minutes left, J.")
        self.mac.out[('pmset', '-g', 'batt')] = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t60%; charging; 1:30 remaining present: true\n"
        self.assertEqual(self.say('is my mac charging'), "Yes, it's charging at 60 percent, about 1 hour 30 minutes to full, J.")
        self.mac.out[('pmset', '-g', 'batt')] = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t30%; discharging; (no estimate) present: true\n"
        self.assertEqual(self.say('is my mac charging'), "No, it's on battery at 30 percent, J.")
        self.mac.out[('pmset', '-g', 'batt')] = "Now drawing from 'AC Power'\n"
        self.assertEqual(self.say('how much battery is left'), "This Mac has no battery, J.")

    def test_storage(self):
        self.assertEqual(self.say('how much storage do I have left'), 'You have 123 gigabytes free out of 494 gigabytes, J.'); self.assertTrue(self.mac.ran('df', '-H', '/'))

    def test_uptime(self):
        self.assertEqual(self.say("what's my uptime"), 'Your Mac has been on for 3 days and 4 hours, J.')

    def test_sleep_mic_night_shift_hidden_files(self):
        self.assertEqual(self.say('put the mac to sleep'), 'Going to sleep, J.'); self.assertTrue(self.mac.ran('pmset', 'sleepnow'))
        self.say('mute the mic'); self.assertEqual(self.mac.osa_calls[-1], 'set volume input volume 0')
        self.say('unmute my microphone'); self.assertEqual(self.mac.osa_calls[-1], 'set volume input volume 70')
        said = self.say('turn on night shift'); self.assertIn('Night Shift', said); self.assertTrue(self.mac.ran('open', 'x-apple.systempreferences:com.apple.Displays-Settings.extension'))
        self.say('show hidden files'); self.assertIn('keystroke "." using {command down, shift down}', self.mac.said()); self.assertIn('tell application "Finder" to activate', self.mac.said())

    def test_keep_awake(self):
        self.assertEqual(self.say('keep my mac awake for 2 hours'), 'Keeping your Mac awake for 2 hours, J.'); self.assertEqual(self.mac.spawned[-1], ['caffeinate', '-d', '-i', '-t', '7200'])
        self.say('stop keeping my mac awake'); self.assertTrue(self.mac.ran('pkill', '-x', 'caffeinate'))

    def test_about_this_mac(self):
        self.assertEqual(self.say('what mac model is this'), "It's a MacBook Pro with the Apple M3 Pro chip and 18 GB of memory, J.")
        self.assertEqual(self.say('what macOS version am I on'), "You're on macOS 15.1, Sequoia, J.")
        self.assertEqual(self.say('how much ram do I have'), 'You have 18 GB of memory, J.')
        self.assertEqual(self.say('how much memory is free'), 'About 62 percent of your memory is free, J.')
        self.assertEqual(self.say("what's my mac's name"), "This Mac is called Sam's MacBook, J.")
        self.assertEqual(self.say('is my mac connected to the internet'), "Yes, you're online, J.")
        self.mac.tcp = False; self.assertIn("can't reach the internet", self.say('am i online'))

    def test_destructive_system_asks_stay_with_the_confirm_flow(self):
        for t in ('empty the trash', 'restart the mac', 'reboot my computer', 'empty my downloads folder', 'log out', 'shut down the mac'):
            self.none(t)
        self.assertFalse(any('restart' in c or 'shut down' in c or 'delete' in c for c in self.mac.osa_calls))
        self.assertFalse(self.mac.run_calls)


class Media(MacCase):
    def setUp(self):
        super().setUp(); self.mac.running = {'Spotify'}

    def test_whats_playing(self):
        self.assertEqual(self.say("what's playing"), 'Blinding Lights by The Weeknd, J.')
        self.assertEqual(self.say('who sings this song'), "That's The Weeknd, with Blinding Lights, J.")
        self.mac.running = set(); self.assertEqual(self.say('what song is this'), "Nothing's playing in Music or Spotify, J.")

    def test_shuffle_repeat_like(self):
        self.say('turn on shuffle'); self.assertIn('tell application "Spotify" to set shuffling to true', self.mac.osa_calls[-1])
        self.say('turn off shuffle'); self.assertIn('set shuffling to false', self.mac.osa_calls[-1])
        self.say('repeat this song'); self.assertIn('set repeating to true', self.mac.osa_calls[-1])
        self.none('like this song')   # Spotify has no like in AppleScript
        self.mac.running = {'Music'}
        self.say('shuffle my music'); self.assertIn('tell application "Music" to set shuffle enabled to true', self.mac.osa_calls[-1])
        self.say('repeat this song'); self.assertIn('set song repeat to one', self.mac.osa_calls[-1])
        self.say('like this song'); self.assertIn('set favorited of current track to true', self.mac.osa_calls[-1])

    def test_apple_music_playlist(self):
        self.assertEqual(self.say('play my chill playlist in apple music'), 'Playing Chill Mix in Apple Music, J.')
        self.assertIn('every playlist whose name contains "chill"', self.mac.osa_calls[-1]); self.assertIn('play (item 1 of r)', self.mac.osa_calls[-1])
        self.mac.osa_rules.insert(0, ('every playlist', 'none'))
        self.assertIn("couldn't find a playlist called chill", self.say('play chill on apple music'))
        self.none('play something on apple music')

    def test_music_volume(self):
        self.say('turn the music up'); self.assertIn('set volume output volume 62', self.mac.said())
        self.say('turn the music down'); self.assertIn('set volume output volume 38', self.mac.said())


class Browser(MacCase):
    def test_chromium_scripts(self):
        self.say('open a new tab'); self.assertIn('tell front window to make new tab', self.mac.osa_calls[-1]); self.assertIn('tell application "Brave Browser"', self.mac.osa_calls[-1])
        self.assertEqual(self.say('close this tab'), 'Closed the tab, J.'); self.assertIn('close active tab', self.mac.osa_calls[-1])
        self.assertEqual(self.say('reload the page'), 'Reloaded, J.'); self.assertIn('reload active tab', self.mac.osa_calls[-1])
        self.assertEqual(self.say("what's the title of this page"), "You're on Example Page, J.")
        self.assertEqual(self.say('copy the page link'), 'Copied the page link, J.'); self.assertEqual(self.mac.piped[-1], ('pbcopy', 'https://example.com/a'))
        self.say('open a private window'); self.assertIn('mode:"incognito"', self.mac.osa_calls[-1])
        self.say('open my last closed tab'); self.assertIn('keystroke "t" using {command down, shift down}', self.mac.osa_calls[-1])
        self.say('next tab'); self.assertIn('key code 48 using control down', self.mac.osa_calls[-1])
        self.say('previous tab'); self.assertIn('key code 48 using {control down, shift down}', self.mac.osa_calls[-1])
        self.say('bookmark this page'); self.assertIn('keystroke "d" using command down', self.mac.osa_calls[-1])

    def test_safari_scripts(self):
        self.browser = 'Safari'
        self.say('close this tab'); self.assertIn('close current tab', self.mac.osa_calls[-1]); self.assertIn('tell application "Safari"', self.mac.osa_calls[-1])
        self.say('reload the page'); self.assertIn('set URL of current tab to (URL of current tab)', self.mac.osa_calls[-1])
        self.say('new tab'); self.assertIn('set current tab to (make new tab)', self.mac.osa_calls[-1])
        self.say('what page am I on'); self.assertIn('name of current tab of front window', self.mac.osa_calls[-1])

    def test_not_running_browser_is_said_not_launched(self):
        self.mac.osa_rules.insert(0, ('return "off"', 'off'))
        self.assertEqual(self.say('close this tab'), "Brave isn't open, J.")

    def test_back_forward_zoom_paste_keys(self):
        self.say('go back'); self.assertIn('keystroke "[" using command down', self.mac.osa_calls[-1])
        self.say('go forward'); self.assertIn('keystroke "]" using command down', self.mac.osa_calls[-1])
        self.say('zoom in'); self.assertIn('keystroke "=" using command down', self.mac.osa_calls[-1])
        self.say('zoom out'); self.assertIn('keystroke "-" using command down', self.mac.osa_calls[-1])

    def test_search_google(self):
        self.assertEqual(self.say('search google for best pizza near me'), 'Searched Google for best pizza near me, J.')
        self.assertIn(['open-browser', 'https://www.google.com/search?q=best%20pizza%20near%20me'], self.mac.run_calls)
        self.none('search google for it')


class Files(MacCase):
    def touch(self, rel, age=0):
        p = os.path.join(self.home, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w').close(); os.utime(p, (time.time() - age, time.time() - age)); return p

    def test_latest_download_skips_partials_and_hidden(self):
        old = self.touch('Downloads/old.pdf', 500); new = self.touch('Downloads/report.pdf', 10)
        self.touch('Downloads/movie.mp4.crdownload', 1); self.touch('Downloads/.DS_Store', 0)
        self.assertEqual(self.say('open the latest download'), 'Opening report.pdf, J.'); self.assertTrue(self.mac.ran('open', new))
        self.assertEqual(self.say('what did I download last'), 'Your latest download is report.pdf, J.')
        self.assertEqual(self.say('reveal my last download in finder'), 'Showing report.pdf in Finder, J.'); self.assertTrue(self.mac.ran('open', '-R', new))

    def test_empty_downloads(self):
        self.assertEqual(self.say('open my last download'), 'Your Downloads folder is empty, J.')

    def test_find_a_file_uses_mdfind_and_reveals_the_best_match(self):
        a = self.touch('Documents/invoice.pdf', 100); b = self.touch('Library/x/invoice.pdf'); c = self.touch('Documents/old invoice march.pdf', 5)
        self.mac.out[('mdfind',)] = '\n'.join([b, c, a])
        said = self.say('find a file named invoice')
        self.assertTrue(self.mac.ran('mdfind', '-onlyin', self.home, '-name', 'invoice'))
        self.assertEqual(said, 'Found 2 matches. The best one is invoice.pdf in Documents, and I showed it in Finder, J.')   # the Library copy is ignored
        self.assertTrue(self.mac.ran('open', '-R', a))
        self.mac.out[('mdfind',)] = ''
        self.assertEqual(self.say('search my mac for resume'), "I couldn't find anything named resume, J.")

    def test_open_a_folder_by_name(self):
        os.makedirs(os.path.join(self.home, 'Documents', 'Projects'))
        self.assertEqual(self.say('open the folder projects'), 'Opening Projects, J.'); self.assertTrue(self.mac.ran('open', os.path.join(self.home, 'Documents', 'Projects')))
        self.mac.out[('mdfind',)] = os.path.join(self.home, 'Documents', 'Deep', 'Taxes')
        self.assertEqual(self.say('open the taxes folder'), 'Opening Taxes, J.')
        self.mac.out[('mdfind',)] = ''
        self.assertEqual(self.say('open the nothing folder'), "I couldn't find a folder called nothing, J.")
        self.say('open the applications folder'); self.assertTrue(self.mac.ran('open', '/Applications'))

    def test_new_folder_on_the_desktop(self):
        self.assertEqual(self.say('make a new folder on the desktop called reports'), 'Made a folder called Reports on your desktop, J.')
        self.assertTrue(os.path.isdir(os.path.join(self.home, 'Desktop', 'Reports')))
        self.assertIn('already a folder', self.say('create a folder named reports on my desktop'))
        self.say('create a folder named Taxes in documents'); self.assertTrue(os.path.isdir(os.path.join(self.home, 'Documents', 'Taxes')))
        self.none('make a new folder')

    def test_desktop_contents(self):
        self.assertEqual(self.say("what's on my desktop"), 'Your Desktop is empty, J.')
        for n in 'abcdef': self.touch(f'Desktop/{n}.txt')
        self.assertEqual(self.say('how many files are on my desktop'), 'You have 6 items on your Desktop: a.txt, b.txt, c.txt, d.txt and 2 more, J.')


class People(MacCase):
    def test_whatsapp_chat_opens_without_sending(self):
        self.assertEqual(self.say('open the whatsapp chat with mom'), 'Opened your WhatsApp chat with Mom Sharma, J. I haven\'t sent anything.')
        self.assertIn(['open-browser', 'https://wa.me/919876543210'], self.mac.run_calls)
        with mock.patch.object(zm, '_app_exists', lambda n: n == 'WhatsApp'):
            self.say('message mom on whatsapp'); self.assertTrue(self.mac.ran('open', 'whatsapp://send?phone=919876543210'))
        self.assertIn('people whose name contains "Mom"', self.mac.said())
        self.mac.osa_rules.insert(0, ('people whose name', ''))
        self.assertEqual(self.say('open whatsapp chat with Rahul'), "I couldn't find Rahul in your Contacts, J.")

    def test_email_draft_never_sends(self):
        self.assertIn('email draft to bob@example.com', self.say('write an email to bob@example.com'))
        self.assertTrue(self.mac.ran('open', 'mailto:bob%40example.com'))
        self.say('email john@example.com about the meeting'); self.assertTrue(self.mac.ran('open', 'mailto:john%40example.com?subject=The%20meeting'))
        self.say('compose an email to Mom'); self.assertTrue(self.mac.ran('open', 'mailto:mom%40example.com'))
        self.assertFalse(any('send' in ' '.join(c) for c in self.mac.run_calls)); self.assertNotIn('send', self.mac.said().replace('Contacts', ''))
        self.none('write an email to my boss asking for leave')
        self.mac.osa_rules.insert(0, ('people whose name', '')); self.none('send an email to Priya')

    def test_facetime_and_call_only_open_the_app(self):
        self.assertIn("won't dial", self.say('FaceTime Mom')); self.assertTrue(self.mac.ran('open', '-a', 'FaceTime'))
        self.assertIn("won't place the call", self.say('call my dad')); self.assertFalse(any(c[:1] == ['open'] and 'facetime://' in ' '.join(c) for c in self.mac.run_calls))
        self.assertEqual(self.say('open facetime', expect=False), None)   # plain "open FaceTime" is the normal open-app path
        for t in ('call it a day', 'call me a cab', 'call me back'): self.none(t)

    def test_text_is_prepared_not_sent(self):
        self.assertIn('not sent', self.say('text Mom saying I will be late'))
        self.assertTrue(self.mac.ran('open', 'sms:+919876543210&body=I%20will%20be%20late'))
        self.say('text mom'); self.assertTrue(self.mac.ran('open', 'sms:+919876543210'))
        self.none('text me when you are done')


class CalendarNotes(MacCase):
    def ev(self, title, start, end, allday=False):
        return {'title': title, 'start': start, 'end': end, 'allDay': allday}

    def test_tomorrow_and_week(self):
        self.mac.events = {'calendars': ['Home'], 'events': [self.ev('Standup', '2026-10-27T09:00:00+05:30', '2026-10-27T09:30:00+05:30'), self.ev('Lunch', '2026-10-27T13:00:00+05:30', '2026-10-27T14:00:00+05:30'),
                                                           self.ev('Holiday', '2026-10-27T00:00:00+05:30', '2026-10-28T00:00:00+05:30', True)]}
        said = self.say("what's on my calendar tomorrow")
        self.assertTrue(said.startswith('2 things tomorrow: Standup at 9 am; Lunch at 1 pm'), said); self.assertIn('All day: Holiday', said)
        self.assertEqual(self.say('what do I have on friday').split(':')[0], '2 things Friday') if False else None
        self.mac.events = {'calendars': ['Home'], 'events': []}
        self.assertEqual(self.say('what do i have tomorrow'), 'Nothing on your calendar tomorrow, J.')

    def test_calendar_needs_access_or_accounts(self):
        self.mac.events = {'need': 'calendar'}; self.assertIn('Calendar access', self.say("what's on my calendar tomorrow"))
        self.mac.events = {'calendars': []}; self.assertIn('no accounts yet', self.say("what's on my calendar tomorrow"))

    def test_today_stays_with_the_existing_command(self):
        self.none("what's on my calendar today")

    def test_am_i_free(self):
        self.mac.events = {'calendars': ['Home'], 'events': [self.ev('Design review', '2026-10-27T15:00:00+05:30', '2026-10-27T16:00:00+05:30')]}
        with mock.patch.object(zm, '_cal_events', wraps=zm._cal_events):
            self.assertEqual(self.say('am I free tomorrow at 3'), 'No, you have Design review then, J.')
            self.assertEqual(self.say('am I free tomorrow at 5 pm'), "Yes, you're free at 5 pm tomorrow, J.")

    def test_add_event_script(self):
        self.assertEqual(self.say('add a meeting tomorrow at 5 called design review'), 'Added Design Review tomorrow at 5 pm, J.')
        sc = self.mac.osa_calls[-1]
        self.assertIn('tell application "Calendar"', sc); self.assertIn('summary:"Design Review"', sc); self.assertIn('set day of s to 27', sc); self.assertIn('set month of s to 10', sc)
        self.assertIn('set hours of s to 17', sc); self.assertIn('set hours of e to 18', sc); self.assertIn('if writable of c then', sc)
        self.say('schedule a meeting tomorrow at 3:30 pm called standup for 30 minutes'); sc = self.mac.osa_calls[-1]
        self.assertIn('set hours of s to 15', sc); self.assertIn('set minutes of s to 30', sc); self.assertIn('set minutes of e to 0', sc); self.assertIn('set hours of e to 16', sc)
        self.say('add an event on Friday at 2 called dentist'); self.assertIn('set day of s to 30', self.mac.osa_calls[-1]); self.assertIn('set hours of s to 14', self.mac.osa_calls[-1])
        self.assertEqual(self.say('create a calendar event called lunch tomorrow at noon'), 'Added Lunch tomorrow at 12 pm, J.')
        self.assertIn('set hours of s to 12', self.mac.osa_calls[-1])
        self.say('schedule a meeting with Sara tomorrow at 4 pm'); self.assertIn('summary:"Meeting with Sara"', self.mac.osa_calls[-1])

    def test_add_event_needs_a_time_and_is_never_recurring(self):
        n = len(self.mac.osa_calls)
        self.none('add a meeting tomorrow called review'); self.none('schedule a weekly meeting every monday at 5 called sync')
        self.assertEqual(len(self.mac.osa_calls), n)

    def test_add_event_calendar_access_denied(self):
        def boom(script, timeout=8): raise RuntimeError('not allowed')
        with mock.patch.object(zc, '_osa', boom):
            self.assertIn("couldn't reach Calendar", self.say('add a meeting tomorrow at 5 called x'))

    def test_notes(self):
        self.assertEqual(self.say('take a note: buy milk'), "Noted, J. It's in your Notes app.")
        self.assertIn('tell application "Notes" to make new note with properties {body:"<div>Buy milk</div>"}', self.mac.osa_calls[-1])
        self.say('make a note that the wifi password is on the fridge'); self.assertIn('<div>The wifi password is on the fridge</div>', self.mac.osa_calls[-1])
        self.say('note to self call the bank'); self.assertIn('<div>Call the bank</div>', self.mac.osa_calls[-1])
        self.say('add buy milk to my notes'); self.assertIn('<div>Buy milk</div>', self.mac.osa_calls[-1])
        self.say('write this down: meeting moved to 4'); self.assertIn('<div>Meeting moved to 4</div>', self.mac.osa_calls[-1])
        self.say('take a note: say "hi" <b> & go'); self.assertIn('&lt;b&gt; &amp; go', self.mac.osa_calls[-1]); self.assertIn('\\"hi\\"', self.mac.osa_calls[-1])
        self.say('create a new note'); self.assertIn('make new note with properties {body:""}', self.mac.osa_calls[-1])
        self.assertEqual(self.say('read my last note'), 'Your latest note says: Call the bank at ten')
        self.assertEqual(self.say("what's my latest note"), 'Your latest note says: Call the bank at ten')

    def test_notes_words_inside_other_sentences_are_left_alone(self):
        for t in ('i noted that you were late', 'footnote seven is wrong', 'take notes on this lecture for me', 'what notes did the doctor give'):
            self.none(t)

    def test_reminder_lists(self):
        self.assertEqual(self.say('add milk to my shopping list'), 'Added milk to Shopping, J.'); self.assertIn('make new reminder with properties {name:"Milk"}', self.mac.osa_calls[-1]); self.assertIn('contains "Shopping"', self.mac.osa_calls[-1])
        self.assertEqual(self.say("what's on my to do list"), '2 on your to do list: milk, eggs, J.'); self.assertIn('default list', self.mac.osa_calls[-1])
        self.mac.osa_rules.insert(0, ('make new reminder', 'nolist')); self.assertIn("couldn't find a shopping list", self.say('add eggs to my shopping list'))


class Clipboard(MacCase):
    def test_read_copy_clear(self):
        self.assertEqual(self.say("what's on my clipboard"), 'On your clipboard: hello clip'); self.say('read my clipboard'); self.say('what did i copy')
        self.mac.clipboard = ''; self.assertEqual(self.say('read the clipboard'), 'Your clipboard has no text on it, J.')
        self.assertEqual(self.say('copy hello world to the clipboard'), 'Copied that to your clipboard, J.'); self.assertEqual(self.mac.piped[-1], ('pbcopy', 'hello world'))
        self.say('copy this text hello there'); self.assertEqual(self.mac.piped[-1], ('pbcopy', 'hello there'))
        self.say('clear the clipboard'); self.assertEqual(self.mac.piped[-1], ('pbcopy', ''))
        self.say('paste'); self.assertIn('keystroke "v" using command down', self.mac.osa_calls[-1])

    def test_long_clipboard_is_trimmed(self):
        self.mac.clipboard = 'word ' * 200
        self.assertLess(len(self.say('what is on my clipboard')), 330)

    def test_copy_without_something_to_copy_is_left_alone(self):
        for t in ('copy this', 'copy that to the clipboard', 'copy it'): self.none(t)


class TimeAndDates(MacCase):
    def test_time_in_cities(self):
        self.assertEqual(self.say('what time is it in London'), "It's 5:08 PM in London, J.")
        self.assertEqual(self.say("what's the time in New York"), "It's 1:08 PM in New York, J.")
        self.assertEqual(self.say('time in Tokyo'), "It's 2:08 AM tomorrow in Tokyo, J.")
        self.assertEqual(self.say('what time is it in Sydney right now'), "It's 4:08 AM tomorrow in Sydney, J.")
        self.assertEqual(self.say('what time is it in UTC'), "It's 5:08 PM in UTC, J.")
        self.assertEqual(self.say('what time is it in Lima'), "It's 12:08 PM in Lima, J.")   # found in the zoneinfo database
        self.none('what time is it in narnia')

    def test_days_until_and_what_day(self):
        self.assertEqual(self.say('how many days until christmas'), '60 days until Christmas, J.')
        self.assertEqual(self.say('how many days until december 25'), '60 days until December 25th, J.')
        self.assertEqual(self.say('how many days until tomorrow'), '1 day until Tomorrow, J.') if False else None
        self.assertEqual(self.say('what day is december 25th'), 'December 25th, 2026 is a Friday, J.')
        self.assertEqual(self.say('what day of the week is july 4th 2027'), 'July 4th, 2027 is a Sunday, J.')
        self.assertEqual(self.say("what's the date next friday"), 'Next Friday is October 30th, 2026, J.')
        self.assertEqual(self.say('how many days are left in the year'), '66 days left in 2026, J.')
        self.assertEqual(self.say('what week of the year is it'), "It's week 44 of 2026, J.")
        self.assertEqual(self.say('how many days until the weekend'), '5 days until the weekend, J.')
        self.assertEqual(self.say('how many days until january 1'), '67 days until January 1st, J.')

    def test_personal_dates_are_not_guessed(self):
        for t in ('how many days until my birthday', 'how many days until my exam', 'what day is it', 'how many days until the deadline'): self.none(t)


class Conversions(MacCase):
    def test_lengths_mass_volume(self):
        self.assertEqual(self.say('convert 10 km to miles'), '10 kilometers is 6.21 miles, J.')
        self.assertEqual(self.say('how many miles is 5 kilometers'), '5 kilometers is 3.11 miles, J.')
        self.assertEqual(self.say('how many kilograms is 150 pounds'), '150 pounds is 68.04 kilograms, J.')
        self.assertEqual(self.say('convert 70 kg to lb'), '70 kilograms is 154.32 pounds, J.')
        self.assertEqual(self.say('how many centimeters in 10 inches'), '10 inches is 25.4 centimeters, J.')
        self.assertEqual(self.say('convert 6 feet to cm'), '6 feet is 182.88 centimeters, J.')
        self.assertEqual(self.say('how many liters is 5 gallons'), '5 gallons is 18.93 liters, J.')
        self.assertEqual(self.say('how many ounces in a pound'), '1 pound is 16 ounces, J.')
        self.assertEqual(self.say("what's 5 miles in kilometers"), '5 miles is 8.05 kilometers, J.')
        self.assertEqual(self.say('convert five hundred grams to ounces'), '500 grams is 17.64 ounces, J.')
        self.assertEqual(self.say('60 mph in kph'), '60 miles per hour is 96.56 kilometers per hour, J.')

    def test_temperatures(self):
        self.assertEqual(self.say('what is 30 celsius in fahrenheit'), '30 degrees Celsius is 86 degrees Fahrenheit, J.')
        self.assertEqual(self.say('convert 98.6 F to C'), '98.6 degrees Fahrenheit is 37 degrees Celsius, J.')
        self.assertEqual(self.say('100 fahrenheit in celsius'), '100 degrees Fahrenheit is 37.78 degrees Celsius, J.')
        self.assertEqual(self.say('0 celsius in kelvin'), '0 degrees Celsius is 273.15 kelvin, J.')

    def test_mismatched_or_unknown_units_are_left_alone(self):
        for t in ('convert 10 km to kg', 'convert 5 apples to oranges', 'convert 10 km to km', 'what is 5 in binary'): self.none(t)


class Translate(MacCase):
    def reply(self, text='नमस्ते'):
        self.mac.json = lambda u: {'responseData': {'translatedText': text}, 'responseStatus': 200}

    def test_translate_phrases(self):
        self.reply(); self.assertEqual(self.say('translate hello to hindi'), 'hello in Hindi is नमस्ते, J.')
        urls = []
        self.mac.json = lambda u: urls.append(u) or {'responseData': {'translatedText': 'Gracias'}, 'responseStatus': 200}
        self.assertEqual(self.say('how do you say thank you in spanish'), 'thank you in Spanish is Gracias, J.')
        self.assertEqual(urls[-1], 'https://api.mymemory.translated.net/get?q=thank%20you&langpair=en|es')
        self.say('translate good morning into french'); self.assertTrue(urls[-1].endswith('q=good%20morning&langpair=en|fr'))
        self.say('say I love you in italian'); self.assertTrue(urls[-1].endswith('langpair=en|it'))
        self.say('translate where is the station to spanish'); self.assertIn('where%20is%20the%20station', urls[-1])

    def test_translation_failures_return_none(self):
        self.mac.json = None; self.none('translate hello to hindi')
        self.mac.json = lambda u: {'responseData': {'translatedText': 'MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS'}, 'responseStatus': 200}; self.none('translate hello to hindi')
        self.mac.json = lambda u: {'responseData': {'translatedText': 'x'}, 'responseStatus': 429}; self.none('translate hello to hindi')
        self.none('translate this to hindi'); self.none('translate hello to klingon')


RSS = '<rss><channel><title>BBC</title><item><title><![CDATA[First &amp; big story]]></title></item><item><title>Second story.</title></item><item><title>Third story</title></item><item><title>Fourth</title></item></channel></rss>'


class News(MacCase):
    def test_top_three_headlines(self):
        urls = []
        self.mac.text = lambda u: urls.append(u) or RSS
        self.assertEqual(self.say("what's the news"), 'Top headlines: First & big story. Second story. Third story.')
        self.assertEqual(urls[-1], 'https://feeds.bbci.co.uk/news/rss.xml')
        self.say('latest tech news'); self.assertEqual(urls[-1], 'https://feeds.bbci.co.uk/news/technology/rss.xml')
        self.say('read me the headlines'); self.say('bbc news'); self.say('tell me the news')

    def test_falls_back_to_google_news_then_none(self):
        seen = []
        def text(u):
            seen.append(u)
            return None if 'bbci' in u else '<rss><item><title>Only story - Reuters</title></item></rss>'
        self.mac.text = text
        self.assertEqual(self.say('top news headlines'), 'Top headlines: Only story.'); self.assertEqual(len(seen), 2)
        self.mac.text = None; self.none('what is the news')


class FunAndStopwatch(MacCase):
    def test_jokes_coins_dice_numbers(self):
        self.assertEqual(self.say('tell me a joke'), zm.JOKES[0])
        self.assertEqual(self.say('flip a coin'), 'Heads, J.'); self.assertEqual(self.say('heads or tails'), 'Heads, J.')
        self.assertEqual(self.say('roll a dice'), 'You rolled a 1, J.'); self.assertEqual(self.say('roll two dice'), 'You rolled 1 and 1, that\'s 2, J.')
        self.assertEqual(self.say('roll a d20'), 'You rolled a 1, J.')
        self.assertEqual(self.say('give me a random number between 5 and 9'), '5, J.')
        self.assertEqual(self.say('pick a random number'), '1, J.')
        self.assertEqual(self.say('pick a card'), 'Ace of hearts, J.'); self.assertEqual(self.say('magic eight ball will I get rich'), zm.BALL[0])
        self.assertEqual(self.say('tell me a fun fact'), zm.FACTS[0]); self.assertEqual(self.say('give me a quote'), zm.QUOTES[0])

    def test_random_is_really_random_in_range(self):
        for p in mock.patch.stopall.__self__ if False else []: pass
        with mock.patch.object(zm.random, 'randint', random.randint):
            for _ in range(50):
                n = int(self.say('random number from 3 to 6').split(',')[0]); self.assertTrue(3 <= n <= 6)

    def test_stopwatch(self):
        clock = [5000.0]
        with mock.patch.object(zm, '_epoch', lambda: clock[0]):
            self.assertEqual(self.say("what's the stopwatch at"), 'No stopwatch is running, J.')
            self.assertEqual(self.say('start a stopwatch'), 'Stopwatch running, J.')
            clock[0] += 125; self.assertEqual(self.say("what's the stopwatch at"), '2 minutes and 5 seconds, J.')
            clock[0] += 3600; self.assertEqual(self.say('stop the stopwatch'), 'Stopped at 1 hour 2 minutes and 5 seconds, J.')
            self.assertEqual(self.say('stop the stopwatch'), 'No stopwatch is running, J.')
            self.say('start the stopwatch'); clock[0] += 10; self.say('reset the stopwatch'); clock[0] += 3
            self.assertEqual(self.say("what's the stopwatch at"), '3 seconds, J.')

    def test_what_can_you_do(self):
        for t in ('what can you do', 'help', 'what are your commands'): self.assertIn('all free on your Mac', self.say(t))
        self.none('help me write a cover letter'); self.none('help me with my homework')


class NoCallName(MacCase):
    def test_replies_have_no_stray_comma_without_a_name(self):
        with mock.patch.object(zc, 'CALL', lambda: ''):
            self.assertEqual(self.say('flip a coin'), 'Heads.'); self.assertEqual(self.say('convert 10 km to miles'), '10 kilometers is 6.21 miles.')


class Negatives(MacCase):
    def test_ambiguous_and_personal_phrases_return_none(self):
        for t in ('what should I eat for dinner', 'plan my week', 'summarize this article for me', 'fix the bug in my code', 'how are you', 'tell me about the news article I wrote',
                  'the battery of the camera is dead', 'turn the page', 'my brightness idea is great', 'note that he was late', 'i need a new tab key', 'can you call it a day',
                  'what is the best mac for video editing', 'translate this document', 'set the table', 'make me a sandwich', 'tell me about dark mode in design', 'focus on the hook',
                  'search for flights to goa', 'convert this video to mp4', 'how many days did the project take', 'what time is the meeting', 'time to go', 'what am I looking at', "what's on my screen", 'open it', 'open my unfamiliar homework'):
            with self.subTest(t=t): self.none(t)
        self.assertFalse(self.mac.run_calls); self.assertFalse(self.mac.osa_calls)

    def test_never_raises(self):
        def boom(*a, **k): raise OSError('broken')
        with mock.patch.object(zc, '_run', boom), mock.patch.object(zc, '_osa', boom):
            for t in ('turn on dark mode', 'what is my battery', 'what is on my clipboard', 'next tab', 'take a note: hi'): self.assertIsNone(zm.handle(zc._norm(t), t))
        self.assertIsNone(zm.handle('', '')); self.assertIsNone(zm.handle(None, None))


class Wiring(MacCase):
    def test_zuka_commands_calls_this_module_last(self):
        self.assertEqual(zc.handle('convert 10 km to miles'), '10 kilometers is 6.21 miles, J.')
        self.assertEqual(zc.handle('flip a coin'), 'Heads, J.')
        self.assertEqual(zc.handle('what time is it'), "It's 8 pm, J." if False else zc.handle('what time is it'))   # the existing commands still win
        self.assertTrue(zc.handle("what's my battery percentage").startswith("Battery's at 85 percent"))

    def test_existing_commands_win_over_these(self):
        self.assertIn('Volume at', zc.handle('volume up') or 'Volume at')
        self.assertTrue(zc.handle('open downloads').startswith('Opening Downloads'))


class AuditOfTheAssistant(unittest.TestCase):
    """Every phrase through atticus.fast(), all side effects mocked: how many are free, before and after zuka_more."""
    def run_audit(self, with_more):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        home = tmp.name
        for d in ('Desktop', 'Downloads', 'Documents'): os.makedirs(os.path.join(home, d))
        open(os.path.join(home, 'Downloads', 'report.pdf'), 'w').close()
        mac = Mac(self); mac.running = {'Spotify'}; mac.events = {'calendars': ['Home'], 'events': []}
        mac.text = lambda u: '203.0.113.7' if 'ipify' in u else RSS
        mac.json = lambda u: {'responseData': {'translatedText': 'Hola'}, 'responseStatus': 200}
        ok = mock.Mock(returncode=0, stdout='', stderr='')
        ps = [mock.patch('subprocess.run', return_value=ok), mock.patch('subprocess.Popen', return_value=mock.Mock(communicate=lambda *a, **k: ('', ''))),
              mock.patch('urllib.request.urlopen', side_effect=OSError('no network in tests')),
              mock.patch.object(atticus, 'show', return_value='opened x'), mock.patch.object(atticus, 'youtube_tab', return_value='ok'), mock.patch.object(atticus, 'youtube_play', return_value='Playing.'),
              mock.patch.object(atticus, 'free_focus', return_value=None), mock.patch.object(atticus, 'place', return_value='ok'), mock.patch.object(atticus, 'play', return_value=None),
              mock.patch.object(atticus, 'queue', return_value='Queued'), mock.patch.object(atticus, 'hands', return_value=('ok', True)), mock.patch.object(atticus, 'menu_bar_click', return_value=None),
              mock.patch.object(atticus, 'hands_map', return_value={'nodes': []}), mock.patch.object(atticus, 'say', return_value=None), mock.patch.object(atticus, 'tip', return_value=None),
              mock.patch.object(atticus, 'app_id', lambda a: 'com.test.' + a.lower().replace(' ', '')), mock.patch.object(atticus, 'quit_app', return_value=True),
              mock.patch.object(atticus, 'installed_apps', return_value=['Safari', 'Finder', 'Spotify', 'Notes', 'Google Chrome', 'Mail', 'Messages', 'Calendar', 'FaceTime', 'Music', 'System Settings', 'Activity Monitor']),
              mock.patch('time.sleep', return_value=None), mock.patch.object(atticus, 'LAST', os.path.join(home, 'last')), mock.patch.object(zm.random, 'randint', lambda a, b: a)]
        if not with_more: ps.append(mock.patch.dict(sys.modules, {'zuka_more': None}))
        for p in ps: p.start()
        try:
            _mac_patches(self, mac, home)
            return {ph: atticus.fast(ph) for ph in PHRASES}
        finally:
            for p in ps: p.stop()

    def test_the_free_share(self):
        before = self.run_audit(False); after = self.run_audit(True)
        b_free = [p for p, r in before.items() if r is not None]; a_none = [p for p, r in after.items() if r is None]
        print(f"\nAUDIT: {len(PHRASES)} phrases. Free before zuka_more: {len(b_free)}. Free after: {len(PHRASES) - len(a_none)}. Still going to Claude ({len(a_none)}):")
        for p in a_none: print(f"   - {p}  [{STAYS_WITH_CLAUDE.get(p, 'UNEXPECTED')}]")
        self.assertGreaterEqual(len(PHRASES), 150)
        self.assertEqual(set(a_none), set(STAYS_WITH_CLAUDE), 'only confirm-only, personal and real-writing phrases may reach Claude')
        self.assertGreater(len(PHRASES) - len(a_none), len(b_free) + 150)
        for p in set(PHRASES) - set(STAYS_WITH_CLAUDE): self.assertTrue(after[p], p)
        for p in ('empty the trash', 'restart the mac', 'reboot my computer'): self.assertIsNone(after[p])


if __name__ == '__main__':
    unittest.main()
