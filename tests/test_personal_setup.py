"""First-run "Make it yours" in the packaged app: gating, the empty call-name wording, the setup page's fields, and personal-settings-only saving."""
import importlib.machinery
import importlib.util
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
PAGE = (ROOT / 'ui/onboarding.html').read_text()
SETTINGS = (ROOT / 'ui/settings.html').read_text()
MANAGED = json.loads((ROOT / 'packaging/managed.json').read_text())
GAP = re.compile(r'[ ,][.?!]|\s,|\s{2}')   # what a missing name must not leave behind: "Done, ." "Hey !" "Hi , how"


def enum_body(name):
    start = SWIFT.index(f'enum {name} {{')
    return SWIFT[start:SWIFT.index('\n}\n', start) + 3]


class Packaged(unittest.TestCase):
    """The app as the packaged build runs it: WAVELENGTH_RUNTIME set, its settings in a scratch folder."""
    runtime = '/App/runtime'

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        env = {'ATTICUS_DIR': self.dir}
        if self.runtime: env['WAVELENGTH_RUNTIME'] = self.runtime
        patcher = mock.patch.dict(os.environ, env); patcher.start(); self.addCleanup(patcher.stop)
        if not self.runtime: os.environ.pop('WAVELENGTH_RUNTIME', None)
        pref = mock.patch.object(atticus, 'PREFS', os.path.join(self.dir, 'settings.json')); pref.start(); self.addCleanup(pref.stop)

    def configure(self, **values):
        (Path(self.dir) / 'settings.json').write_text(json.dumps(values))


class EmptyCallName(Packaged):
    def test_packaged_app_has_no_default_name_before_setup(self):
        self.assertEqual((atticus.call_name(), z.CALL()), ('', ''))
        self.configure(userCallName='J')   # an old build saved its default; setup was never done
        self.assertEqual((atticus.call_name(), z.CALL()), ('', ''))
        self.configure(userCallName='')
        self.assertEqual((atticus.call_name(), z.CALL()), ('', ''))

    def test_a_chosen_name_is_used_and_j_is_fine_once_setup_is_done(self):
        self.configure(userCallName='Sam', setupDone=True)
        self.assertEqual((atticus.call_name(), z.CALL()), ('Sam', 'Sam'))
        self.configure(userCallName='J', setupDone=True)
        self.assertEqual((atticus.call_name(), z.CALL()), ('J', 'J'))

    def test_the_dev_build_keeps_its_default(self):
        os.environ.pop('WAVELENGTH_RUNTIME', None)
        self.assertEqual((atticus.call_name(), z.CALL()), ('J', 'J'))
        self.assertEqual(z.clean_call('Done, J.'), 'Done, J.')   # a name: nothing touched

    def test_clean_call_closes_the_gap(self):
        for raw, want in (('Done, .', 'Done.'), ('Hey !', 'Hey!'), ('Hello, !', 'Hello!'), ('Hi , how do I sound?', 'Hi, how do I sound?'),
                          ('Morning, . Gmail is up.', 'Morning. Gmail is up.'), ('Long day, ? You did good.', 'Long day? You did good.'),
                          ('Hey , good to hear you.', 'Hey, good to hear you.'), ('No name here, just words.', 'No name here, just words.')):
            self.assertEqual(z.clean_call(raw, ''), want)
        self.assertEqual(z.clean_call(None, ''), None)

    def test_replies_read_naturally_without_a_name(self):
        self.assertEqual(z.handle('what is 2 plus 2'), "That's 4.")
        self.assertEqual(z.FAIL.format(call=z.CALL()), 'That one slipped past me, . Try again in a moment.')   # raw template: handle() cleans it
        self.assertEqual(z.clean_call(z.FAIL.format(call=z.CALL())), 'That one slipped past me. Try again in a moment.')
        self.assertEqual(z.clean_call(z._MUSIC[0][2].format(call=z.CALL())), 'Paused.')
        self.assertEqual(z.clean_call(z.NO_TASKS.format(call=z.CALL())), "Task folders aren't set up for you yet. You can set them up in your setup.")
        self.assertEqual(z.call_suffix(), '')
        self.configure(userCallName='Sam', setupDone=True)
        self.assertEqual(z.handle('what is 2 plus 2'), "That's 4, Sam.")
        self.assertEqual(z.call_suffix(), ', Sam')

    def test_every_small_talk_reply_and_the_timer_and_offline_lines_are_clean(self):
        for _, replies in atticus.SMALL_TALK:
            for template in replies:
                said = atticus.call_clean(template.format(call=atticus.call_name(), name='Zuka'))
                self.assertNotRegex(said, GAP, said)
        for t in ('hello', 'thanks', 'good morning', 'how are you'):
            self.assertNotRegex(atticus.small_talk(t)[0], GAP)
        self.assertEqual(atticus.call_suffix(), '')
        zsrc = (ROOT / 'zuka_commands.py').read_text()
        self.assertIn("Time's up{call_suffix()}.", zsrc); self.assertNotIn("Time's up, {CALL()}", zsrc)   # the spoken timer line

    def test_the_system_prompt_does_not_say_call_them_nothing(self):
        prompt = atticus.system_prompt(atticus.ASK_FIRST)
        self.assertNotIn('Call them .', prompt); self.assertNotIn('CALL_NAME', prompt)
        self.assertIn("Don't use a name for them.", prompt)
        self.configure(userCallName='Sam', setupDone=True)
        self.assertIn('Call them Sam.', atticus.system_prompt(atticus.ASK_FIRST))

    def test_the_bundled_checkin_drops_the_name_cleanly(self):
        loader = importlib.machinery.SourceFileLoader('zuka_checkin', str(ROOT / 'packaging/zuka-checkin'))
        spec = importlib.util.spec_from_loader('zuka_checkin', loader); checkin = importlib.util.module_from_spec(spec); loader.exec_module(checkin)
        for part, lines in checkin.LINES.items():
            for template in lines:
                with mock.patch.object(checkin.random, 'choice', return_value=template):
                    self.assertNotRegex(checkin.line_for(part, ''), GAP, template)
                    self.assertNotIn('{user}', checkin.line_for(part, 'Sam'))
        with mock.patch.object(checkin.random, 'choice', return_value='Evening, {user}! How did today go?'):
            self.assertEqual(checkin.line_for('evening', ''), 'Evening! How did today go?')
            self.assertEqual(checkin.line_for('evening', 'Sam'), 'Evening, Sam! How did today go?')
        self.assertEqual((checkin.part_for(9), checkin.part_for(14), checkin.part_for(20)), ('morning', 'afternoon', 'evening'))
        src = (ROOT / 'packaging/zuka-checkin').read_text()
        self.assertIn('userCallName', src); self.assertNotIn('chatterbox', src)   # the runtime's own say, not the owner's install


class SetupGating(unittest.TestCase):
    def test_setup_is_for_a_packaged_app_until_setup_is_done(self):
        self.assertIn('static var needsSetup: Bool { packaged && !bool("setupDone") }', SWIFT)
        self.assertIn('/runtime/python/bin/python3") }', SWIFT)   # packaged = the bundled Python exists, the same test as runtimeDir
        self.assertIn('let runtimeDir: String? =', SWIFT)

    def test_every_place_that_shows_or_sends_setup_is_gated_by_it(self):
        self.assertIn('if Prefs.needsSetup { cfg.userContentController.addUserScript(', SWIFT)
        self.assertIn('window.__setup = true;', SWIFT)
        self.assertIn('if Prefs.needsSetup { self?.call("ob.setup", PersonalSetup.options()) }', SWIFT)
        self.assertIn('if !UserDefaults.standard.bool(forKey: "onboarded") || Prefs.needsSetup { DispatchQueue.main.async { onboarding.open() } }', SWIFT)
        self.assertIn('UserDefaults.standard.bool(forKey: "onboarded") && !Prefs.needsSetup ? settings.open() : onboarding.open()', SWIFT)
        self.assertEqual(SWIFT.count('window.__setup'), 1)   # nothing else turns the page on
        first = SWIFT[SWIFT.index('func packagedFirstRun()'):]
        self.assertIn('if !Prefs.needsSetup, !((try? fm.contentsOfDirectory(atPath: greet))', first[:first.index('\n}\n')])   # setup records the greetings

    def test_the_page_only_starts_on_setup_when_told_to_and_skips_it_after(self):
        self.assertIn('setupNeeded = window.__setup === true', PAGE)
        self.assertIn("go(setupNeeded ? 'you' : 'welcome')", PAGE)
        self.assertIn("(id === 'you' && !setupNeeded)", PAGE)
        self.assertIn('setupNeeded = false;', PAGE)   # after saving, Back never returns to it
        self.assertLess(PAGE.index("const pages = ['you', 'welcome', 'perms'"), PAGE.index("'tip', 'done']"))   # before the permission steps
        self.assertEqual(re.search(r'<div id="dots">(.*?)</div>', PAGE).group(1).count('<i></i>'), len(re.search(r"const pages = \[(.*?)\];", PAGE).group(1).split(',')))   # a dot for every page

    def test_prefs_default_to_no_call_name_in_a_packaged_app_before_setup(self):
        self.assertIn('"assistantName": "Zuka", "userCallName": "J"', SWIFT)   # the dev default is untouched
        self.assertIn('if packaged, saved["setupDone"] as? Bool != true,', SWIFT)
        self.assertIn('values["userCallName"] = ""', SWIFT)
        self.assertIn('k == "userCallName" && packaged ? ""', SWIFT)
        self.assertIn('static var callSuffix: String { callName.isEmpty ? "" : ", " + callName }', SWIFT)
        self.assertNotIn('\\(Prefs.callName).', SWIFT)   # spoken lines use callSuffix, so ", ." never reaches the voice

    def test_the_checkin_script_ships_in_the_runtime(self):
        self.assertIn('packaging/zuka-checkin', (ROOT / 'packaging/make-runtime.sh').read_text())
        self.assertTrue(os.access(ROOT / 'packaging/zuka-checkin', os.X_OK))
        self.assertIn('rt + "/voice/zuka-checkin"', SWIFT)
        self.assertIn('com.wavelength.checkin', SWIFT)
        self.assertIn('<key>Weekday</key>', SWIFT)
        self.assertIn('(1...6)', SWIFT)   # Monday to Saturday


class SetupPage(unittest.TestCase):
    def test_the_fields_exist(self):
        for ident in ('y-name', 'y-call', 'y-voices', 'y-wake', 'y-greet', 'y-check', 'y-times', 'y-browser', 'y-music', 'y-keep', 'y-save', 'y-note', 'y-skipwork'):
            self.assertIn(f'id="{ident}"', PAGE, ident)
        self.assertIn('<section class="page" id="you">', PAGE)
        self.assertIn('Make it yours', PAGE)
        self.assertIn('What should your assistant be called?', PAGE)
        self.assertIn('What should it call you?', PAGE)
        self.assertIn('id="y-name" value="Zuka" maxlength="31"', PAGE)
        self.assertIn('value="10:00, 14:30, 18:30"', PAGE)
        self.assertIn('id="y-keep" value="Claude"', PAGE)
        self.assertIn('Uses the mic on this Mac only.', PAGE)
        for voice in ('warm', 'bright', 'smooth', 'calm', 'british', 'indian', 'jarvis', 'deep', 'friendly-male', 'indian-male'):
            self.assertIn(f"['{voice}'", PAGE, voice)
        self.assertIn('#c4325f', PAGE)

    def test_the_voices_match_what_the_voice_engine_and_commands_offer(self):
        listed = re.findall(r"\['([a-z-]+)', '[A-Za-z ]+'\]", PAGE[PAGE.index('const Y_VOICES'):PAGE.index('let yVoice')])
        self.assertEqual(listed, list(z.VOICES))
        self.assertEqual(re.findall(r'"([a-z-]+)"', re.search(r'static let voices = \[(.*?)\]', SWIFT).group(1)), list(z.VOICES))
        self.assertEqual(re.findall(r'<option value="([a-z-]+)">', SETTINGS[SETTINGS.index('data-k="voice"'):][:900]), list(z.VOICES))

    def test_the_call_name_is_required_and_names_follow_the_character_rule(self):
        self.assertIn("$('y-save').disabled = !call || yBusy", PAGE)
        self.assertIn(r"[^\p{L}\p{N} \-]", PAGE)
        self.assertIn('slice(0, 31)', PAGE)
        self.assertIn('guard !call.isEmpty else { return "Tell me what to call you." }', SWIFT)
        self.assertIn('CharacterSet(charactersIn: " -")', SWIFT)
        self.assertIn('.prefix(31)', SWIFT)

    def test_the_page_talks_to_the_app_only_through_the_setup_calls(self):
        for call in ("do: 'setupPreview'", "do: 'setupSave'", 'setup(d)', 'setupSaved(r)', 'window.__rename'):
            self.assertIn(call, PAGE, call)
        self.assertIn('Done — say “${r.name}” or press ${key}', PAGE)
        self.assertIn("setTimeout(() => go('welcome'), 1800)", PAGE)   # then the permission steps

    def test_settings_keeps_the_personal_choices_editable(self):
        group = SETTINGS[SETTINGS.index('id="yougroup"'):SETTINGS.index('<h3>Shortcut</h3>')]
        for key in ('assistantName', 'userCallName', 'voice', 'wakeWord', 'checkins'):
            self.assertIn(f'data-k="{key}"', group, key)
        self.assertIn('data-k="greet"', SETTINGS)   # greetings: already there
        self.assertIn('managed(d.locked || [])', SETTINGS)   # locked keys stay hidden by the existing logic
        for key in ('assistantName', 'userCallName', 'voice', 'wakeWord', 'checkins', 'greet'):
            self.assertNotIn(key, MANAGED['locked'], key)


class SavingIsPersonalOnly(unittest.TestCase):
    def test_save_writes_only_personal_keys_and_never_a_locked_one(self):
        body = enum_body('PersonalSetup')
        save = body[body.index('static func save('):]
        keys = set(re.findall(r'\("([A-Za-z]+)",', save[:save.index('for (k, v) in personal')])) | set(re.findall(r'Prefs\.set\("([A-Za-z]+)"', save))
        self.assertEqual(keys, {'assistantName', 'userCallName', 'greet', 'wakeWord', 'checkins', 'setupDone'})
        locked = set(MANAGED['locked']) | set(MANAGED['values'])
        self.assertFalse(keys & locked, keys & locked)
        self.assertIn('where !Prefs.locked.contains(k)', save)   # a key the owner locks in managed.json is skipped, whatever the list says
        self.assertIn('if locked.contains(k) { return false }', SWIFT)   # and Prefs.set itself refuses it
        self.assertLess(save.index('Prefs.set("setupDone", true)'), save.index('rerecordGreetings()'))
        self.assertGreater(save.index('Prefs.set("setupDone", true)'), save.index('applyCheckins(times)'))   # setupDone last: a failure runs setup again
        for developer in ('client', 'model', 'routing', 'safe', 'apiBase', 'apiKey', 'quietAgents', 'usageCheck', 'autoUpdate', 'improve', 'stats'):
            self.assertNotIn(f'"{developer}"', save)

    def test_the_other_files_are_the_users_own_and_merged(self):
        body = enum_body('PersonalSetup')
        self.assertIn('writeJSON(["pick": pick], configDir + "/voice.json")', body)
        save = body[body.index('static func save('):]
        self.assertIn('var w = readJSON(configDir + "/workflow.json")', save)   # merged, not replaced
        for key in ('browser', 'music', 'keepOpen'):
            self.assertIn(f'w["{key}"]', save)
        for other in ('tools', 'startDay', 'editMode', 'tasks'):
            self.assertNotIn(f'w["{other}"]', save)
        self.assertIn('make-greetings.py', body)
        self.assertIn('launchctl(["bootout", label])', body)   # off removes the check-in agent

    def test_settings_edits_go_through_the_same_checks(self):
        apply = SWIFT[SWIFT.index('func apply(_ k: String, _ v: Any)'):]
        apply = apply[:apply.index('guard Prefs.set(k, v)')]
        for key in ('assistantName', 'userCallName', 'voice', 'checkins'):
            self.assertIn(f'"{key}"', apply)
        self.assertIn('PersonalSetup.cleanName', apply)
        self.assertIn('PersonalSetup.parseTimes', apply)


class SetupLogic(unittest.TestCase):
    """The pure Swift helpers (names, times, the check-in agent), compiled on their own."""
    def test_names_times_and_the_checkin_plist(self):
        from tests import run_swift
        body = enum_body('PersonalSetup')
        out = run_swift(self, 'import Cocoa\nlet runtimeDir: String? = "/App/runtime"\nlet sayHelper: String? = nil\n' + '''enum Prefs { static let locked: Set<String> = []; static var needsSetup: Bool { true }; static func str(_ k: String) -> String { "" }
  static func set(_ k: String, _ v: Any) -> Bool { true }; static var assistantName: String { "Zuka" }; static var callName: String { "" } }
''' + body + r'''
precondition(PersonalSetup.cleanName("  Sam <b>O'Neil-Smith 3 ") == "Sam bONeil-Smith 3", PersonalSetup.cleanName("  Sam <b>O'Neil-Smith 3 "))
precondition(PersonalSetup.cleanName(String(repeating: "a", count: 40)).count == 31)
precondition(PersonalSetup.cleanName("!!!").isEmpty)
let t = PersonalSetup.parseTimes("10:00, 14:30, 6pm")!
precondition(t.map { $0.0 * 100 + $0.1 } == [1000, 1430, 1800], "\(t)")
precondition(PersonalSetup.parseTimes("9") != nil && PersonalSetup.parseTimes("12am")!.first! == (0, 0))
precondition(PersonalSetup.parseTimes("25:00") == nil && PersonalSetup.parseTimes("soon") == nil && PersonalSetup.parseTimes("") == nil && PersonalSetup.parseTimes("10:61") == nil)
let plist = PersonalSetup.plistForCheckins(t, runtime: "/App/runtime")
precondition(plist.contains("<string>com.wavelength.checkin</string>") && plist.contains("<string>/App/runtime/voice/zuka-checkin</string>") && plist.contains("<string>/App/runtime/python/bin/python3</string>"))
precondition(plist.components(separatedBy: "<key>Weekday</key>").count - 1 == 18, "Monday to Saturday, three times")
precondition(!plist.contains("<integer>7</integer>") && !plist.contains("<integer>0</integer><key>Hour") && plist.contains("<key>Hour</key><integer>14</integer><key>Minute</key><integer>30</integer>"))
print("setup logic ok")
''')
        self.assertIn('setup logic ok', out)


if __name__ == '__main__':
    unittest.main()
