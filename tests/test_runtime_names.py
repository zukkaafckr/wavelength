"""The assistant's name and what it calls the user are read from settings at runtime, never baked into source."""
import importlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import atticus  # noqa: E402
import zuka_commands as z  # noqa: E402

SWIFT = (ROOT / 'Atticus.swift').read_text()
BARE_CALL = re.compile(r"(?<=[ ,])J(?=[.?!,:])")


class Names(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patcher = mock.patch.dict(os.environ, {'ATTICUS_DIR': self.dir}); patcher.start(); self.addCleanup(patcher.stop)
        pref = mock.patch.object(atticus, 'PREFS', os.path.join(self.dir, 'settings.json')); pref.start(); self.addCleanup(pref.stop)

    def configure(self, **values):
        (Path(self.dir) / 'settings.json').write_text(json.dumps(values))

    def test_defaults_keep_the_current_install_unchanged(self):
        self.assertEqual((atticus.assistant_name(), atticus.call_name()), ('Zuka', 'J'))
        self.assertEqual((z.NAME(), z.CALL()), ('Zuka', 'J'))
        self.assertIn('You are Zuka,', atticus.system_prompt(atticus.ASK_FIRST))
        self.assertIn('Call them J.', atticus.system_prompt(atticus.ASK_FIRST))
        self.assertIn('"assistantName": "Zuka", "userCallName": "J"', SWIFT)

    def test_system_prompt_uses_the_configured_names(self):
        self.configure(assistantName='Nova', userCallName='Sam')
        prompt = atticus.system_prompt(atticus.ASK_FIRST)
        self.assertIn('You are Nova,', prompt); self.assertIn('Call them Sam.', prompt)
        self.assertNotIn('Zuka', prompt); self.assertNotIn('ASSISTANT_NAME', prompt); self.assertNotIn('CALL_NAME', prompt)
        self.assertEqual(prompt, atticus.system_prompt(atticus.ASK_FIRST))   # stable for a given user

    def test_names_are_sanitised(self):
        self.configure(assistantName='No"va\\', userCallName='   ')
        self.assertEqual((atticus.assistant_name(), atticus.call_name()), ('Nova', 'J'))

    def test_small_talk_uses_the_configured_names(self):
        self.assertIn('Zuka', atticus.small_talk('who are you')[0])
        self.configure(assistantName='Nova', userCallName='Sam')
        self.assertEqual(atticus.small_talk('who are you')[0], "I'm Nova, your assistant on Wavelength. What can I do for you?")
        for t in ('hello', 'thanks', 'good morning', 'how are you'):
            reply = atticus.small_talk(t)[0]
            self.assertIn('Sam', reply); self.assertNotRegex(reply, r'\bJ\b')
        self.assertEqual(atticus.small_talk('hello nova open spotify')[1], 'open spotify')

    def test_zuka_commands_replies_use_the_configured_names(self):
        self.configure(assistantName='Nova', userCallName='Sam')
        self.assertEqual(z.NAME(), 'Nova')
        self.assertEqual(z.FAIL.format(call=z.CALL()), 'That one slipped past me, Sam. Try again in a moment.')
        with mock.patch.object(z, '_osa', side_effect=RuntimeError('nope')), mock.patch.object(z, '_now', return_value=__import__('datetime').datetime(2026, 10, 26, 10, 0)):
            self.assertEqual(z.handle('remind me to call mom at 5 pm'),
                             "I couldn't add that to Reminders, Sam. Allow Nova under Privacy & Security, Reminders.")
        self.assertEqual(z._MUSIC[0][2].format(call=z.CALL()), 'Paused, Sam.')

    def test_swift_menu_and_spoken_lines_use_the_runtime_names(self):
        for text in ('"Ask \\(Prefs.assistantName)"', '"Quit \\(Prefs.assistantName)"', '"\\(Prefs.assistantName) is paused"',
                     'That one needs Claude, \\(Prefs.callName). ', 'Say yes or no, \\(Prefs.callName).'):
            self.assertIn(text, SWIFT)
        self.assertNotRegex(SWIFT, r'"(?:[^"\n]*[ ,])?(?:Ask|Pause|Resume|Quit) Zuka')
        code = re.sub(r'//.*', '', SWIFT)
        self.assertNotRegex(code, r'"[^"\n]*(?<=[ ,])J(?=[.?!,:])[^"\n]*"')   # no spoken or visible call-name left in a string literal

    def test_pages_take_names_from_the_loader_and_keep_no_baked_call_name(self):
        self.assertIn('/*NAMES*/', SWIFT); self.assertIn('window.__names', SWIFT)
        for page in sorted((ROOT / 'ui').glob('*.html')):
            html = page.read_text()
            self.assertFalse(BARE_CALL.search(re.sub(r'<!--.*?-->', '', html, flags=re.S)), page.name)   # the placeholder reads --call
            if 'Zuka' in re.sub(r'<script>/\*NAMES\*/.*?</script>', '', re.sub(r'<!--.*?-->', '', html, flags=re.S), flags=re.S):
                self.assertIn('/*NAMES*/', html, page.name)   # a page with the default name in its text swaps it from window.__names
        self.assertIn('var(--call', (ROOT / 'ui' / 'ui.html').read_text())

    def test_no_reply_literal_in_zuka_commands_holds_the_bare_call_name(self):
        import ast
        tree = ast.parse((ROOT / 'zuka_commands.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertFalse(BARE_CALL.search(node.value), node.value)


if __name__ == '__main__':
    unittest.main()
