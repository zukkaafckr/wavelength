"""Zuka's free on-device conversation brain (zuka_chat.py): routing, the model call against a mock local server, history, names, knowledge."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atticus  # noqa: E402
import zuka_chat as zc  # noqa: E402


class Mock(BaseHTTPRequestHandler):
    reply = 'Doing great, thanks!'
    delay = 0
    seen = []

    def log_message(self, *a): pass

    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"version":"mock"}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        Mock.seen.append(body)
        threading.Event().wait(Mock.delay)   # real wait even if another test left time.sleep patched
        self.send_response(200); self.end_headers()
        try: self.wfile.write(json.dumps({'message': {'role': 'assistant', 'content': Mock.reply}}).encode())
        except OSError: pass


class ChatBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(('127.0.0.1', 0), Mock)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        Mock.reply, Mock.delay, Mock.seen = 'Doing great, thanks!', 0, []
        for p in (mock.patch.dict(os.environ, {'ZUKA_CHAT_URL': f'http://127.0.0.1:{self.srv.server_port}', 'ATTICUS_DIR': self.tmp.name}),
                  mock.patch.object(zc, 'LLM_DIR', self.tmp.name), mock.patch.object(zc, 'STAMP', os.path.join(self.tmp.name, 'last_used')),
                  mock.patch.object(atticus, 'assistant_name', return_value='Zuka'), mock.patch.object(atticus, 'call_name', return_value='J')):
            p.start(); self.addCleanup(p.stop)


class RoutingRule(unittest.TestCase):
    def test_conversation_goes_local(self):
        for t in ["how are you doing today", "I'm feeling tired", "tell me a fun fact about space", "what should I eat tonight", "why is the sky blue", "and why at sunset?",
                  "why?", "tell me a joke", "another one", "help me plan my evening", "what's the difference between weather and climate", "what's the difference between a stock and a mutual fund",
                  "recommend a movie for tonight", "do you think robots can feel", "what does serendipity mean", "give me three video hook ideas", "how do you say thank you in Spanish",
                  "tell me about yourself", "I'm so stressed about tomorrow"]:
            self.assertTrue(zc.chatty(t), t)

    def test_actions_live_data_and_long_writing_go_to_claude(self):
        for t in ["open my downloads", "send a message to John", "email my boss about leave", "rename this file", "delete the old folder", "close all my tabs", "play some jazz on Spotify",
                  "write a long email to my boss", "write me an essay on the French revolution", "draft a script for my ad", "what's the weather like tomorrow in Mumbai", "who won the cricket match yesterday",
                  "latest news about AI", "what's the price of gold", "what's 100 dollars in rupees", "if I buy 3 shirts at 450 rupees each and get 10 percent off what do I pay",
                  "can you open Brave", "please send this to Sam", "wake me up at 6", "sing me a song", "x" * 500, ""]:
            self.assertFalse(zc.chatty(t), t[:40])


class Answer(ChatBase):
    def test_reply_comes_back_trimmed_to_two_spoken_sentences(self):
        Mock.reply = '**Pretty good!** I am here. And ready to chat. Really.'
        self.assertEqual(zc.answer('how are you', []), 'Pretty good! I am here.')

    def test_need_claude_and_empty_and_errors_fall_through(self):
        for r in ('NEED_CLAUDE', 'need_claude', 'NEED CLAUDE.', '', '   '):
            Mock.reply = r
            self.assertIsNone(zc.answer('hello', []), r)
        Mock.reply = 'ok'
        with mock.patch.object(zc, 'enabled', return_value=False): self.assertIsNone(zc.answer('hello', []))
        self.assertIsNone(zc.answer('', []))
        with mock.patch.dict(os.environ, {'ZUKA_CHAT_URL': 'http://127.0.0.1:9'}): self.assertIsNone(zc.answer('hello', []))

    def test_timeout_falls_through(self):
        Mock.delay = 1.5
        with mock.patch.object(zc, 'TIMEOUT', .6):
            t = time.time()
            self.assertIsNone(zc.answer('hello', []))
            self.assertLess(time.time() - t, 1.4)

    def test_never_names_a_model_maker(self):
        Mock.reply = 'I am the assistant here. It was created by Claude.'
        self.assertEqual(zc.answer('who made you', []), 'I am the assistant here.')

    def test_history_is_sent_and_capped(self):
        hist = [(f'q{i}', f'a{i}') for i in range(9)]
        zc.answer('and then?', hist)
        msgs = Mock.seen[-1]['messages']
        self.assertEqual([m['content'] for m in msgs[1:]], [x for i in range(3, 9) for x in (f'q{i}', f'a{i}')] + ['and then?'])
        self.assertEqual(msgs[1]['role'], 'user'); self.assertEqual(msgs[2]['role'], 'assistant')

    def test_history_defaults_to_the_apps_recent_turns(self):
        rows = [{'t': time.time() - 30, 'q': 'why is the sky blue', 'a': 'Scattered sunlight.'}, {'t': time.time() - 4000, 'q': 'old', 'a': 'stale'}, {'t': 'bad'}]
        Path(self.tmp.name, 'recent.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\nnot json\n')
        zc.answer('and at sunset?')
        sent = [m['content'] for m in Mock.seen[-1]['messages'][1:]]
        self.assertEqual(sent, ['why is the sky blue', 'Scattered sunlight.', 'and at sunset?'])

    def test_name_and_call_name_in_the_prompt(self):
        zc.answer('hi', [])
        sys_prompt = Mock.seen[-1]['messages'][0]['content']
        self.assertIn('You are Zuka, a warm, quick voice assistant talking with J.', sys_prompt)
        self.assertIn('NEED_CLAUDE', sys_prompt); self.assertIn('1-2 short spoken sentences', sys_prompt)
        with mock.patch.object(atticus, 'call_name', return_value=''), mock.patch.object(atticus, 'assistant_name', return_value='Nova'):
            zc.answer('hi', [])
        p = Mock.seen[-1]['messages'][0]['content']
        self.assertIn('You are Nova, a warm, quick voice assistant.', p); self.assertNotIn('talking with', p)

    def test_short_follow_ups_get_a_hint(self):
        zc.answer('another one', [('tell me a joke', 'Why did the chicken...')])
        self.assertIn('new one', Mock.seen[-1]['messages'][-1]['content'])
        zc.answer('another one', [])
        self.assertEqual(Mock.seen[-1]['messages'][-1]['content'], 'another one')

    def test_off_when_not_installed_and_in_plain_tests(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ZUKA_CHAT_URL')
            self.assertFalse(zc.enabled())   # ATTICUS_DIR is set: a test run never starts the real model server


class Knowledge(ChatBase):
    def write(self, text):
        Path(self.tmp.name, 'knowledge.md').write_text(text)

    def test_only_relevant_lines_are_included(self):
        self.write('# People\nAlex is the creative strategist who writes ad scripts.\nAarif runs a moulding workshop.\n# Projects and batches\n'
                   'Night Shift Story 472: full ELI5 VSL.\nShowreel 2026: Remotion reel.\n')
        zc.answer("who's Alex", [])
        p = Mock.seen[-1]['messages'][0]['content']
        self.assertIn('creative strategist', p); self.assertNotIn('moulding', p); self.assertIn('never invent', p)
        zc.answer('why is the sky blue', [])
        self.assertNotIn('creative strategist', Mock.seen[-1]['messages'][0]['content'])
        self.assertNotIn('What you know about', Mock.seen[-1]['messages'][0]['content'])

    def test_no_file_no_knowledge(self):
        zc.answer("who's Alex", [])
        self.assertNotIn('What you know about', Mock.seen[-1]['messages'][0]['content'])

    def test_recent_projects_answer_what_am_i_working_on(self):
        self.write('# People\nSam is an editor.\n# Projects and batches\nNewest thing: the latest batch.\nOlder thing.\n')
        self.assertEqual(zc.knowledge_lines('what am I working on')[0], 'Newest thing: the latest batch.')

    def test_refresh_strips_secrets_and_stays_small(self):
        mem = Path(self.tmp.name, 'mem'); mem.mkdir()
        (mem / 'MEMORY.md').write_text(
            '# Memory Index\n- [Profile](user-x.md) — who\n'
            + '\n'.join(f'- [Project {i}](project-{i}.md) — Batch {i} video; mail sam@example.com, call +91 98765 43210, see https://x.com/a?id=1, key sk-abcdefghijklmnop12 id 9286d15d-1234-5678 ' + 'filler ' * 30
                        for i in range(80)) + '\n')
        (mem / 'user-sam-profile.md').write_text('---\nname: x\n---\nSam is a video editor. Email sam@example.com.\nTools: CapCut.\n')
        out, size = zc.refresh_knowledge(str(mem), os.path.join(self.tmp.name, 'k.md'))
        text = Path(out).read_text()
        self.assertLessEqual(size, 6000)
        for bad in ('@example', '98765', 'https://', 'sk-abc', '9286d15d'): self.assertNotIn(bad, text)
        self.assertIn('video editor', text); self.assertIn('CapCut', text); self.assertIn('Project 79', text)   # newest first


class Wiring(unittest.TestCase):
    def test_local_chat_is_free_and_falls_through(self):
        with mock.patch.object(zc, 'answer', return_value='Hello there!') as ans:
            self.assertEqual(atticus.local_chat('how are you'), 'Hello there!'); ans.assert_called_once()
            ans.reset_mock()
            self.assertIsNone(atticus.local_chat('open my downloads')); ans.assert_not_called()   # actions never reach the model
        with mock.patch.object(zc, 'answer', return_value=None): self.assertIsNone(atticus.local_chat('tell me a joke'))
        with mock.patch.object(zc, 'answer', side_effect=RuntimeError('boom')): self.assertIsNone(atticus.local_chat('tell me a joke'))

    def test_main_tries_local_chat_after_free_commands_and_before_the_claude_card(self):
        src = Path(atticus.__file__).read_text()
        card, offline = src.index("pref('usageCheck', False) and not os.environ.get('ZUKA_USAGE_OK')"), src.index("pref('usageCheck', False) and not online()")
        local = src.index("local = local_chat(")
        self.assertLess(src.index('    if quick:\n'), local); self.assertLess(local, offline); self.assertLess(local, card)
        block = src[local - 300:local + 900]
        self.assertIn("pref('localChat', True)", block); self.assertIn("path='local-ai'", block); self.assertIn("model='local'", block)
        self.assertIn('remember_turn(task, local)', block)

    def test_fast_still_runs_first_for_free_questions(self):
        self.assertIn('def fast(', Path(atticus.__file__).read_text())
        with mock.patch.object(zc, 'answer', side_effect=AssertionError('chat must not run inside fast()')):
            atticus.fast('what time is it')


if __name__ == '__main__':
    unittest.main()
