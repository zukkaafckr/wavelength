"""Zuka's own changes: offline answer, usage check, paid-credit block, greeting, focus view and the renamed menu."""
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import atticus

ROOT = Path(__file__).resolve().parents[1]
SWIFT = (ROOT / 'Atticus.swift').read_text()
UI = (ROOT / 'ui' / 'ui.html').read_text()


class OnlineTests(unittest.TestCase):
    def conn(self, **kw):
        return patch('socket.create_connection', **kw)

    def test_a_real_connection_is_online(self):
        with self.conn(return_value=SimpleNamespace(close=lambda: None)): self.assertTrue(atticus.online())

    def test_no_dns_or_no_route_is_offline(self):
        import socket
        with self.conn(side_effect=socket.gaierror(8, 'nodename nor servname provided')): self.assertFalse(atticus.online())
        with self.conn(side_effect=TimeoutError()): self.assertFalse(atticus.online())
        with self.conn(side_effect=OSError(51, 'Network is unreachable')): self.assertFalse(atticus.online())

    def test_odd_errors_let_the_request_try(self):
        with self.conn(side_effect=OSError(13, 'Permission denied')): self.assertTrue(atticus.online())


class GateTests(unittest.TestCase):
    def gate(self, tool):
        out = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps({'tool_name': tool, 'tool_input': {}}))), patch('sys.stdout', out):
            atticus.gate()
        return json.loads(out.getvalue())['hookSpecificOutput']

    def test_atria_and_higgsfield_are_blocked_under_any_connector_name(self):
        for tool in ('mcp__claude_ai_atria__get_advertiser', 'mcp__claude_ai_Higgsfield__balance',
                     'mcp__0f3a__search_library_ads', 'mcp__abc__generate_video', 'mcp__x__execute_preset'):
            with self.subTest(tool=tool):
                d = self.gate(tool)
                self.assertEqual(d['permissionDecision'], 'deny')
                self.assertIn('Zuka never uses Atria or Higgsfield', d['permissionDecisionReason'])

    def test_other_connectors_still_reach_the_normal_approval(self):
        d = self.gate('mcp__claude_ai_ClickUp__clickup_search')
        self.assertNotIn('Zuka never uses', d.get('permissionDecisionReason', ''))


class UsageCheckTests(unittest.TestCase):
    def test_off_by_default_so_a_fresh_config_never_blocks(self):
        src = (ROOT / 'atticus.py').read_text()
        self.assertIn("pref('usageCheck', False) and not os.environ.get('ZUKA_USAGE_OK')", src)
        self.assertIn("pref('usageCheck', False) and not online()", src)

    def test_offline_check_comes_after_the_free_commands(self):
        src = (ROOT / 'atticus.py').read_text()
        self.assertLess(src.index('    if quick:\n'), src.index("pref('usageCheck', False) and not online()"))
        self.assertLess(src.index("pref('usageCheck', False) and not online()"), src.index("pref('usageCheck', False) and not os.environ.get('ZUKA_USAGE_OK')"))

    def test_no_telemetry_key_is_built_in(self):
        self.assertIn("POSTHOG_KEY = os.environ.get('ATTICUS_POSTHOG_KEY', '')", (ROOT / 'atticus.py').read_text())


class NativeTests(unittest.TestCase):
    def test_menu_is_atticus_menu_with_zuka_name(self):
        menu = SWIFT[SWIFT.index('    func menuNeedsUpdate'):SWIFT.index('    func add(_ m: NSMenu')]
        for item in ('"Ask Zuka"', '"Dictation History…"', '"Settings…"', '"Setup & Permissions…"', '"Report Feedback…"',
                     '"Leave a Tip…"', '"Quit Zuka"', '"Resume Zuka" : "Pause Zuka"', '"Zuka is paused"'):
            self.assertIn(item, menu)
        self.assertNotIn('Atticus', menu)
        self.assertIn('menu.delegate = self; item.menu = menu', SWIFT)   # a click opens the menu, as before

    def test_greeting_only_on_a_fresh_open_then_listens(self):
        start = SWIFT[SWIFT.index('    var greeter: Process?'):SWIFT.index('    func startDictation()')]
        self.assertIn('guard !clickTalk, !panel.isVisible, !busy, !engine.isRunning, Prefs.bool("greet"),', start)
        self.assertIn('Prefs.str("talkMode") == "toggle"', start)   # hold-to-talk would lose the key release
        self.assertIn('if self.gen == g && self.panel.isVisible && !self.engine.isRunning { self.start(dictate: false) }', start)
        for part in ('"morning"', '"afternoon"', '"evening"', '"night"'): self.assertIn(part, start)
        self.assertIn('"greet": true', SWIFT)

    def test_quick_ack_unless_an_hour_passed_and_never_the_same_line_twice(self):
        start = SWIFT[SWIFT.index('    var greeter: Process?'):SWIFT.index('    func startDictation()')]
        self.assertIn('let long = Date().timeIntervalSince(lastLongGreeting) > 3600', start)
        self.assertIn('greetingClip(long ? [dayPart()] : ["ack"])', start)
        self.assertIn('all.count > 1 ? all.filter { $0 != last } : all', start)

    def test_login_and_unlock_hello_without_the_mic(self):
        welcome = SWIFT[SWIFT.index('    func welcome(after s: Double)'):SWIFT.index('    func start() {   // Zuka')]
        self.assertIn('Date().timeIntervalSince(lastLongGreeting) > 600', welcome)
        self.assertIn('greetingClip(["login", dayPart()])', welcome)
        self.assertNotIn('start(dictate', welcome)   # a hello only: the mic stays off
        self.assertIn('Notification.Name("com.apple.screenIsUnlocked")', SWIFT)
        self.assertIn('app.welcome(after: 6)', SWIFT)

    def test_greeting_stops_when_she_closes(self):
        # close() bumps gen, so a greeting ending after Esc never opens the mic (checked in the termination handler)
        gone = SWIFT[SWIFT.index('    func gone() {'):SWIFT.index('    func gone() {') + 200]
        self.assertIn('if let g = greeter { greeter = nil; g.terminate() }', gone)

    def test_no_blur_or_centered_focus_mode(self):
        for gone in ('focusMode', 'Backdrop', 'enterFocus'): self.assertNotIn(gone, SWIFT)
        self.assertNotIn('body.focus', UI)

    def test_top_center_listening_capsule(self):
        self.assertIn('Prefs.str("corner") == "top-center" ? vf.midX - panel.frame.width / 2', SWIFT)
        cap = SWIFT[SWIFT.index('    func capsule(_ on: Bool)'):SWIFT.index('    var pillOn = false')]
        self.assertIn('let w = CGFloat(on ? 212 : max(340, Prefs.num("boxW")))', cap)
        self.assertIn('js("listen"); capsule(true);', SWIFT)                       # listening = capsule
        self.assertEqual(SWIFT.count('capsule(false); warmedVoice = false; js("think")'), 2)           # thinking/answering = the box
        self.assertIn('capsule(true); show()', SWIFT)                              # the greeting opens as the capsule too
        gone = SWIFT[SWIFT.index('    func gone() {'):SWIFT.index('    func gone() {') + 200]
        self.assertIn('capsule(false)', gone)
        self.assertIn("capsule(on) { document.body.classList.toggle('capsule', !!on); fit(); }", UI)
        self.assertIn('body.hearing:not(.dictate) .q.empty { display: none; }', UI)   # one Listening line, no placeholder bubble

    def test_usage_card_says_what_it_costs_and_answers_show_what_they_used(self):
        src = (ROOT / 'atticus.py').read_text()
        self.assertIn("'q': 'Answering this needs Claude.'", src)
        self.assertIn("bit of your plan\\'s session limit{more}. Free commands never ask.", src)
        self.assertIn("print(f'$ {plan_size(used)} use of your plan', flush=True)", src)
        self.assertNotIn('extra credits', src)   # never promise what only the account setting controls
        self.assertEqual(atticus.plan_size(0.0015), 'a tiny'); self.assertEqual(atticus.plan_size(0.2), 'a large')
        self.assertEqual(atticus.money(0.0004), '<$0.001'); self.assertEqual(atticus.money(0.0153), '$0.015')
        self.assertIn("usage ? '<b></b><p class=\"cost\"></p><div><button>Skip</button><button class=\"go\">Go ahead</button></div>'", UI)
        self.assertIn("} else if (tag === '$' && turn()) {", UI)

    def test_first_phrase_is_prerecorded_while_the_answer_streams(self):
        self.assertIn('if line.hasPrefix("… ") { self.warmVoice(String(line.dropFirst(2))) }', SWIFT)
        self.assertIn('p.arguments = ["--warm", "--", partial]', SWIFT)

    def test_settings_has_zuka_switches(self):
        html = (ROOT / 'ui' / 'settings.html').read_text()
        self.assertIn('data-k="greet"', html); self.assertIn('data-k="usageCheck"', html)

    def test_visible_name_is_zuka(self):
        self.assertIn('<key>CFBundleName</key><string>Wavelength</string>', (ROOT / 'build.sh').read_text())   # the app is Wavelength, the assistant Zuka
        self.assertIn('w.title = "Wavelength Settings"', SWIFT)
        self.assertIn('"Zuka", "Atticus"', SWIFT)   # speech recognition knows her name


if __name__ == '__main__':
    unittest.main()
