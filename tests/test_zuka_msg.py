"""Reading and sending WhatsApp / Slack / Discord messages, free. A send needs a spoken yes; nothing here touches a real browser or app."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atticus  # noqa: E402
import zuka_apps as apps  # noqa: E402
import zuka_commands as z  # noqa: E402
import zuka_msg as m  # noqa: E402
import zuka_work as w  # noqa: E402

WA = {'rs': 'complete', 'len': 3000, 'n': 4, 'items': [
    {'name': 'Athar', 'snippet': 'are you coming?', 'unread': True, 'time': '7:40', 'me': False},
    {'name': 'Mom', 'snippet': 'call me', 'unread': True, 'time': '7:12', 'me': False},
    {'name': 'Sam', 'snippet': 'ok thanks', 'unread': False, 'time': 'Yesterday', 'me': False},
    {'name': 'Chris', 'snippet': 'Photo', 'unread': False, 'time': 'Yesterday', 'me': True}]}


class FakeWA:
    """A tiny stand-in for web.whatsapp.com: tells the injected scripts apart and keeps the chat / composer state."""
    def __init__(self, contacts=('Athar', 'Sam', 'Chris')):
        self.contacts, self.query, self.chat, self.box, self.sent, self.send_works = list(contacts), '', '', '', [], True

    def __call__(self, b, host, js, goto=None):
        if js is z._WA_JS:
            return json.dumps(WA)
        if js.startswith('(function(n){var s=document.querySelector(\'#side'):
            self.query = js.split('})(')[-1].rstrip(')')
            self.query = json.loads(self.query) if self.query else ''
            return 'OK'
        if 'JSON.stringify(out)' in js:
            return json.dumps([c for c in self.contacts if self.query and self.query.lower() in c.lower()])
        if 'dispatchEvent' in js:
            self.chat = json.loads(js.rsplit('})(', 1)[1].rstrip(')'))
            return 'OK'
        if 'insertText' in js and 'JSON.stringify({chat' in js:
            self.box = json.loads(js.rsplit('})(', 1)[1].rstrip(')'))
            return json.dumps({'chat': self.chat, 'text': self.box})
        if 'JSON.stringify({chat' in js:
            return json.dumps({'chat': self.chat, 'text': self.box})
        if 'NOSEND' in js:
            if self.send_works:
                self.sent.append((self.chat, self.box)); self.box = ''
            return 'OK'
        raise AssertionError('unexpected script ' + js[:60])


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.fake = FakeWA()
        for p in (mock.patch.object(m, 'SEND_FILE', os.path.join(d, 'send.json')), mock.patch.object(z, 'OFFER_FILE', os.path.join(d, 'o.json')),
                  mock.patch.object(z, 'PENDING', os.path.join(d, 'p.json')), mock.patch.object(z, 'SHUTDOWN_FILE', os.path.join(d, 's.json')),
                  mock.patch.object(z, '_browser', return_value='Brave Browser'), mock.patch.object(z, '_tab_exec', self.fake),
                  mock.patch.object(z, '_focus_or_open', return_value=True) , mock.patch.object(m.time, 'sleep'),
                  mock.patch.object(z, '_osa', return_value=''), mock.patch.object(z, '_run', return_value=mock.Mock(returncode=0, stdout='', stderr='')),
                  mock.patch.object(w, '_trackers', return_value={})):
            p.start(); self.addCleanup(p.stop)
        self.focus = z._focus_or_open


class Reading(Base):
    def test_read_whatsapp_speaks_names_and_snippets_newest_first(self):
        want = "2 unread chats on WhatsApp. Athar: 'are you coming?', at 7:40. Mom: 'call me', at 7:12."
        for p in ['read my WhatsApp messages', 'Read me out WhatsApp once.', 'read WhatsApp messages', "what's on WhatsApp", 'who messaged me on WhatsApp',
                  'any new WhatsApp messages', 'read my whatsapp', 'can you read out my whatsapp messages please', 'I want you to read me my whatsapp messages']:
            self.assertEqual(atticus.fast(p), want, p)

    def test_yes_after_the_unread_offer_reads_them_out(self):
        z._set_offer(['whatsapp'])
        self.assertIn("Athar: 'are you coming?'", atticus.fast('yes'))
        for ans in ['read them', 'read them out', 'who are they from']:
            z._set_offer(['whatsapp'])
            self.assertIn("Mom: 'call me'", atticus.fast(ans), ans)

    def test_the_unread_offer_includes_slack_and_discord_badges(self):
        info = {'whatsapp': 60, 'gmail': []}
        with mock.patch.object(z, '_parse_titles', return_value=info), mock.patch.object(z, '_browser_titles', return_value=''), \
             mock.patch.object(z, '_unread_reply', return_value='60 unread on WhatsApp.'), mock.patch.object(apps, 'badge_sentence', return_value='On your apps: 5 on Slack.'):
            self.assertTrue(z._unread().endswith('Want me to read who they\'re from?'))
        with mock.patch.object(apps, 'chat_status', return_value={'app': 'Slack', 'badge': 5, 'unread': ['Alex'], 'dms': ['Alex: lunch?']}):
            self.assertEqual(z._take_offer(), ['whatsapp', 'slack'])
            z._set_offer(['whatsapp', 'slack'])
            out = atticus.fast('read them out')
        self.assertIn("Athar: 'are you coming?'", out); self.assertIn('Slack shows 5', out)

    def test_what_did_athar_say(self):
        for p in ['what did Athar say', 'read Athar\'s message', 'what did Athar say on WhatsApp', 'did Athar message me']:
            self.assertEqual(atticus.fast(p), "Athar said 'are you coming?', at 7:40.", p)

    def test_slack_and_discord_reads_use_the_apps(self):
        st = {'app': 'Slack', 'badge': 5, 'unread': ['Alex'], 'dms': ['Alex: lunch today?']}
        with mock.patch.object(apps, 'chat_status', return_value=st) as cs:
            for p in ['read my Slack', 'any Slack DMs', 'read Slack messages', 'what is on Slack']:
                self.assertIn('Slack shows 5', atticus.fast(p), p)
            self.assertEqual(cs.call_args[0][0], 'slack')
        with mock.patch.object(apps, 'chat_status', return_value={'app': 'Discord', 'badge': 3, 'unread': ['Alex'], 'dms': ['Alex'], 'servers': []}) as cs:
            self.assertIn('Discord shows 3', atticus.fast('read Discord'))
            self.assertEqual(cs.call_args[0][0], 'discord')

    def test_open_whatsapp_focuses_the_tab(self):
        for p in ['I want you to open WhatsApp', 'open whatsapp', 'open WhatsApp web please']:
            self.focus.reset_mock()
            self.assertEqual(atticus.fast(p), "WhatsApp's up.", p)
            self.focus.assert_called_once()
            self.assertEqual(self.focus.call_args[0][0], 'web.whatsapp.com')


class Parsing(unittest.TestCase):
    def test_send_phrasings(self):
        cases = {
            'Can you message Athar and tell him that I am working': ('whatsapp', 'Athar', 'I am working'),
            'message Athar and tell him I am working': ('whatsapp', 'Athar', 'I am working'),
            'text Sam saying I will be late': ('whatsapp', 'Sam', 'I will be late'),
            'whatsapp Alex that the file is ready': ('whatsapp', 'Alex', 'The file is ready'),
            'send Athar a message saying call me': ('whatsapp', 'Athar', 'Call me'),
            'send a message to Athar saying I am on my way': ('whatsapp', 'Athar', 'I am on my way'),
            'tell Athar on WhatsApp that I am working': ('whatsapp', 'Athar', 'I am working'),
            'tell Sam I am running late': ('whatsapp', 'Sam', 'I am running late'),
            'reply to Athar I am coming': ('whatsapp', 'Athar', 'I am coming'),
            'reply to Athar saying okay': ('whatsapp', 'Athar', 'Okay'),
            'message Chris on Slack the deck is done': ('slack', 'Chris', 'The deck is done'),
            'message Chris on Discord saying hi': ('discord', 'Chris', 'Hi'),
            'slack Chris that I am in a meeting': ('slack', 'Chris', 'I am in a meeting'),
            'I want you to text Athar and say hello for me': ('whatsapp', 'Athar', 'Hello'),
            'message Athar Khan and tell him that I am working': ('whatsapp', 'Athar Khan', 'I am working'),
            'text mom saying I reached': ('whatsapp', 'Mom', 'I reached'),
            'text sam saying i m late': ('whatsapp', 'Sam', "I'm late"),
        }
        for said, want in cases.items():
            self.assertEqual(m.parse_send(said), want, said)

    def test_not_sends(self):
        for said in ['tell me a joke', 'text me the address', 'message me when it is done', 'tell me about the weather', 'what is the time', 'open WhatsApp', 'read my messages',
                     'send', 'message', 'text size bigger', 'tell time']:
            self.assertIsNone(m.parse_send(said), said)


class Sending(Base):
    def ask(self, said='Can you message Athar and tell him that I am working'):
        return atticus.fast(said)

    def test_draft_types_without_sending_and_asks(self):
        self.assertEqual(self.ask(), "Send 'I am working' to Athar on WhatsApp?")
        self.assertEqual((self.fake.chat, self.fake.box, self.fake.sent), ('Athar', 'I am working', []))
        self.assertTrue(m._load())

    def test_yes_sends_and_replies_sent(self):
        self.ask()
        self.assertEqual(atticus.fast('yes'), 'Sent, J.')
        self.assertEqual(self.fake.sent, [('Athar', 'I am working')])
        self.assertIsNone(m._load())
        self.assertNotEqual(atticus.fast('yes'), 'Sent, J.')   # a second yes never re-sends
        self.assertEqual(len(self.fake.sent), 1)

    def test_every_yes_word_sends(self):
        for yes in ['send it', 'go ahead', 'haan', 'Yes.', 'yeah', 'sure', 'ok send it', 'please do']:
            self.fake.sent.clear(); self.ask()
            self.assertEqual(atticus.fast(yes), 'Sent, J.', yes)
            self.assertEqual(len(self.fake.sent), 1, yes)

    def test_no_clears_the_draft(self):
        for no in ['no', 'cancel', 'never mind', 'nahi', 'No.']:
            self.ask()
            self.assertEqual(atticus.fast(no), 'Okay, not sent.', no)
            self.assertEqual((self.fake.box, self.fake.sent), ('', []), no)
            self.assertIsNone(m._load())

    def test_pending_expires_after_two_minutes(self):
        self.ask()
        with mock.patch.object(m.time, 'time', return_value=m.time.time() + 121):
            self.assertIsNone(m.confirm('yes'))
        self.assertEqual(self.fake.sent, [])
        self.assertIsNone(m._load())

    def test_yes_without_a_pending_send_goes_on_to_the_other_handlers(self):
        self.assertIsNone(m.confirm('yes'))
        z._offer_shutdown()
        with mock.patch.object(z, '_shut_down', return_value='Shutting down.') as sd:
            self.assertEqual(atticus.fast('yes'), 'Shutting down.'); sd.assert_called_once()

    def test_pending_send_wins_over_a_shutdown_yes(self):
        z._offer_shutdown(); self.ask()
        with mock.patch.object(z, '_shut_down') as sd:
            self.assertEqual(atticus.fast('yes'), 'Sent, J.'); sd.assert_not_called()

    def test_unrelated_words_leave_the_draft_pending(self):
        self.ask()
        self.assertIsNone(m.confirm('what time is it'))
        self.assertTrue(m._load())

    def test_no_contact_and_several_contacts(self):
        self.assertEqual(self.ask('message Zed and tell him hello'), "I don't see anyone called Zed on WhatsApp, J.")
        self.assertIsNone(m._load())
        self.fake.contacts = ['Athar Khan', 'Athar Ali', 'Sam']
        said = self.ask()
        self.assertEqual(said, 'I see Athar Khan and Athar Ali on WhatsApp. Which one should get it?')
        self.assertEqual(self.fake.sent, [])
        self.assertEqual(atticus.fast('the second one'), "Send 'I am working' to Athar Ali on WhatsApp?")
        self.assertEqual(atticus.fast('yes'), 'Sent, J.')
        self.assertEqual(self.fake.sent, [('Athar Ali', 'I am working')])

    def test_which_one_by_name(self):
        self.fake.contacts = ['Athar Khan', 'Athar Ali']
        self.ask()
        self.assertEqual(atticus.fast('Khan'), "Send 'I am working' to Athar Khan on WhatsApp?")

    def test_exact_name_beats_longer_names(self):
        self.fake.contacts = ['Athar', 'Athar Ali']
        self.assertEqual(self.ask(), "Send 'I am working' to Athar on WhatsApp?")

    def test_chat_changed_before_yes_means_not_sent(self):
        self.ask()
        self.fake.chat = 'Someone Else'
        self.assertEqual(atticus.fast('yes'), "The chat changed, so I didn't send it, J.")
        self.assertEqual(self.fake.sent, [])

    def test_whatsapp_not_open(self):
        with mock.patch.object(z, '_tab_exec', return_value='NOTAB'):
            self.assertIn("WhatsApp isn't open in Brave", self.ask())
        self.assertIsNone(m._load())

    def test_unreliable_send_button_is_reported(self):
        self.ask(); self.fake.send_works = False
        self.assertIn("still in the box", atticus.fast('yes'))

    def test_slack_draft_then_yes_presses_return(self):
        keys = []
        z._osa.side_effect = lambda sc, t=8: keys.append(sc) or ''
        with mock.patch.object(apps, 'running', return_value=True), mock.patch.object(apps, 'hands_read', return_value={'window': 'Chris (DM) - Team - Slack', 'page': '', 'text': '', 'web': True}):
            self.assertEqual(atticus.fast('message Chris on Slack the deck is done'), "Send 'The deck is done' to Chris on Slack?")
            self.assertFalse(any('key code 36' in k and 'The deck' in k for k in keys))
            before = len(keys)
            self.assertEqual(atticus.fast('yes'), 'Sent, J.')
        self.assertTrue(any('key code 36' in k for k in keys[before:]))
        self.assertTrue(any('keystroke "The deck is done"' in k for k in keys[:before]))

    def test_discord_wrong_window_aborts(self):
        with mock.patch.object(apps, 'running', return_value=True), mock.patch.object(apps, 'hands_read', return_value={'window': 'Someone - Discord', 'page': '', 'text': '', 'web': True}):
            self.assertEqual(atticus.fast('message Chris on Discord saying hi'), "I couldn't find Chris on Discord, J. Nothing was sent.")
        self.assertIsNone(m._load())

    def test_slack_cancel_clears_the_box(self):
        keys = []
        z._osa.side_effect = lambda sc, t=8: keys.append(sc) or ''
        with mock.patch.object(apps, 'running', return_value=True), mock.patch.object(apps, 'hands_read', return_value={'window': 'Chris (DM) - Slack', 'page': '', 'text': '', 'web': True}):
            atticus.fast('message Chris on Slack hello there')
            self.assertEqual(atticus.fast('no'), 'Okay, not sent.')
        self.assertTrue(any('keystroke "a" using command down' in k for k in keys))


if __name__ == '__main__':
    unittest.main()
