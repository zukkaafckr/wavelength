"""Wavelength's offline installer: build.sh --package, the bundled-runtime PATH, and the voice scripts' path logic."""
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

import atticus

ROOT = Path(__file__).resolve().parents[1]
VOICE = Path.home() / 'Projects/zuka-team/team/voice'
BUILD = (ROOT / 'build.sh').read_text()
SWIFT = (ROOT / 'Atticus.swift').read_text()


def load(path, name):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        return m
    finally:
        sys.path.remove(str(path.parent))


class BuildScriptTests(unittest.TestCase):
    def test_package_flag_builds_only_the_wavelength_app(self):
        self.assertIn('--package', BUILD)
        self.assertIn('BUNDLE_ID=com.wavelength.app', BUILD)
        self.assertIn('make-runtime.sh "$APP/Contents/Resources/runtime"', BUILD)
        self.assertIn('codesign --force --deep -s - "$APP"', BUILD)
        pkg_block = BUILD[BUILD.index('if [ -n "$PACKAGE" ]; then\n  # Self-contained'):]
        pkg_block = pkg_block[:pkg_block.index('\nfi\n')]
        self.assertIn('exit 0', pkg_block)   # leaves before the LaunchAgent, lsregister and launch
        for live in ('LaunchAgents', 'lsregister', 'launchctl', 'open "$APP"'): self.assertNotIn(live, pkg_block)

    def test_dev_build_keeps_its_id_and_usage_strings_say_wavelength(self):
        self.assertIn('BUNDLE_ID=com.atticus.app', BUILD)
        self.assertIn('wavelength</string>', BUILD)   # URL scheme kept
        for line in BUILD.splitlines():
            if 'UsageDescription' in line: self.assertNotIn('Atticus', line); self.assertIn('Wavelength', line)

    def test_swift_only_uses_the_runtime_when_it_exists(self):
        self.assertIn('/python/bin/python3") ? $0 : nil', SWIFT)
        self.assertIn('env["WAVELENGTH_RUNTIME"] = rt', SWIFT)
        self.assertIn('com.wavelength.voice.plist', SWIFT)


class RuntimePathTests(unittest.TestCase):
    def test_runtime_python_goes_first_when_set(self):
        p = atticus.runtime_path({'WAVELENGTH_RUNTIME': '/App/runtime', 'PATH': '/x'})
        self.assertTrue(p.startswith('/App/runtime/python/bin:/opt/homebrew/bin'))
        self.assertTrue(p.endswith(':/x'))

    def test_without_it_the_path_is_unchanged(self):
        p = atticus.runtime_path({'PATH': '/x'})
        self.assertTrue(p.startswith('/opt/homebrew/bin')); self.assertNotIn('runtime', p)


class VoicePathTests(unittest.TestCase):
    def test_state_dir_is_local_when_writable_else_cache(self):
        v = load(VOICE / 'atticus_voice_server.py', 'avs_test')
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            with patch.object(v, 'HERE', home + '/writable'):
                os.makedirs(home + '/writable')
                self.assertEqual(v.state_dir(), home + '/writable')
            with patch.object(v, 'HERE', home + '/Wavelength.app/Contents/Resources/runtime/voice'):
                os.makedirs(v.HERE)
                self.assertEqual(v.state_dir(), home + '/Library/Caches/Wavelength/voice')   # inside an .app, even if writable
                self.assertTrue(os.path.isdir(v.state_dir()))
            with patch.object(v, 'HERE', home + '/ro'):
                os.makedirs(home + '/ro'); os.chmod(home + '/ro', stat.S_IRUSR | stat.S_IXUSR)
                try:
                    if not os.access(home + '/ro', os.W_OK): self.assertEqual(v.state_dir(), home + '/Library/Caches/Wavelength/voice')
                finally: os.chmod(home + '/ro', 0o700)

    def test_kokoro_dir_prefers_env_then_bundled_then_dev_install(self):
        v = load(VOICE / 'zuka_voice_light.py', 'zvl_test')
        with tempfile.TemporaryDirectory() as t:
            rt = Path(t) / 'runtime'; (rt / 'voice').mkdir(parents=True); (rt / 'kokoro').mkdir()
            with patch.object(v, 'HERE', str(rt / 'voice')), patch.dict(os.environ, {}, clear=False):
                os.environ.pop('WAVELENGTH_KOKORO', None)
                self.assertEqual(v.kokoro_dir(), os.path.expanduser('~/.local/share/kokoro'))   # no model file yet
                (rt / 'kokoro' / 'kokoro-v1.0.int8.onnx').write_bytes(b'x')
                self.assertEqual(v.kokoro_dir(), str(rt / 'kokoro'))
                with patch.dict(os.environ, {'WAVELENGTH_KOKORO': '/elsewhere'}): self.assertEqual(v.kokoro_dir(), '/elsewhere')

    def test_atticus_say_finds_the_bundled_python_and_server(self):
        src = (VOICE / 'atticus-say').read_text()
        self.assertTrue(src.startswith('#!/bin/sh\n"exec" "sh" "-c"'))   # no /usr/bin/python3 stub on a fresh Mac
        self.assertIn('RUNTIME_PY = os.path.join(os.path.dirname(HERE), "python", "bin", "python3")', src)
        self.assertIn('Library/Caches/Wavelength/voice', src)
        self.assertIn('else os.path.expanduser("~/.local/share/kokoro/.venv/bin/python")', src)   # dev behaviour kept

    def test_greetings_keep_untrimmed_clips_without_ffmpeg(self):
        src = (ROOT.parent / 'Projects/zuka-team/team/greetings/make-greetings.py').read_text()
        self.assertIn('keeping the untrimmed clips', src)
        self.assertNotIn('skipping greetings."); return 0\n    if not os.path', src)


if __name__ == '__main__':
    unittest.main()
