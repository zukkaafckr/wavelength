"""Whisper dictation: engine choice, vocabulary prompt, local cleanup, Apple fallback, recording, and the settings row."""
from pathlib import Path
import sys
import unittest

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'Atticus.swift').read_text()
BEGIN, END = '// MARK: whisper dictation begin', '// MARK: whisper dictation end'
BLOCK = SOURCE[SOURCE.index(BEGIN):SOURCE.index(END)]


class WhisperWiringTests(unittest.TestCase):
    def test_engine_default_and_settings_row(self):
        self.assertIn('"dictateEngine": "whisper"', SOURCE)
        self.assertIn('"dictateLang": "auto"', SOURCE)
        page = (ROOT / 'ui' / 'settings.html').read_text()
        self.assertIn('data-k="dictateEngine"', page)
        self.assertIn('Whisper — most accurate', page)
        self.assertIn('Apple — fastest', page)
        self.assertIn('Free, unlimited, runs on this Mac.', page)
        sys.path.insert(0, str(ROOT))
        import atticus
        self.assertEqual(atticus.picks()['dictateEngine'][1], {'Whisper — most accurate': 'whisper', 'Apple — fastest': 'apple'})

    def test_whisper_dictation_never_uses_claude_cleanup(self):
        start = SOURCE[SOURCE.index('dictateWhisper = WhisperDictation.active('):SOURCE.index('captureDictationSelection(); replacement = nil')]
        self.assertIn('dictateCleanup = !dictateWhisper &&', start)
        self.assertNotIn('sendDictationCleanup', BLOCK)
        self.assertNotIn('--dictate-cleanup', BLOCK)

    def test_release_flow_shows_transcribing_and_falls_back_to_apple(self):
        self.assertIn('dictateWhisper ? "Transcribing…"', SOURCE)
        flow = SOURCE[SOURCE.index('func whisperTranscribe('):SOURCE.index('func recordDictationEvent(')]
        self.assertIn('WhisperDictation.timeout(audioSeconds: audio.seconds)', flow)
        self.assertIn('WhisperDictation.resolve(result, apple: source)', flow)
        self.assertIn('removeItem(atPath: audio.path)', flow)   # the temp WAV is always deleted
        self.assertIn('insertDictation(r.text)', flow)   # the existing insertion path (it applies dictateFixes)
        self.assertIn('DictationData.fixed(heard)', SOURCE[SOURCE.index('func insertDictation('):][:200])
        self.assertIn('rec?.append(out)', SOURCE)
        self.assertIn('rec?.append(buf)', SOURCE)

    def test_server_is_local_lazy_and_idle_stopped(self):
        self.assertIn('"--host", "127.0.0.1"', BLOCK)
        self.assertIn('idleSeconds = 600.0', BLOCK)
        self.assertIn('WhisperRunner.shared.warm(', SOURCE)
        self.assertIn('NSApplicationWillTerminateNotification', BLOCK)   # app quit stops the server

    def test_short_and_full_servers_and_long_take_chunking(self):
        self.assertIn('audioSeconds: audio.seconds', SOURCE)   # the runner is told the take length to pick the server
        self.assertIn('short: false', SOURCE)   # the full-window server is warmed when a take runs long
        self.assertIn('field("no_timestamps", short ? "true" : "false")', BLOCK)   # long takes step windows at pauses, not mid-word
        self.assertNotIn('"-mc", "0"', BLOCK)

    def test_packaging_notes_exist(self):
        notes = (ROOT / 'packaging' / 'whisper-bundling.md').read_text()
        for word in ('whisper-cli', 'whisper-server', 'ggml-large-v3-turbo-q5_0.bin', 'notariz'):
            self.assertIn(word, notes)


@unittest.skipUnless(sys.platform == 'darwin', 'macOS Swift regression')
class WhisperNativeTests(unittest.TestCase):
    def test_engine_prompt_cleanup_and_fallback(self):
        swift = 'import Foundation\nimport AVFoundation\n' + BLOCK + r'''
func check(_ ok: Bool, _ msg: String) { if !ok { print("FAIL: " + msg); exit(1) } }
// engine choice
check(WhisperDictation.engine(pref: "whisper", cli: true, model: true) == "whisper", "whisper when installed")
check(WhisperDictation.engine(pref: "", cli: true, model: true) == "whisper", "default is whisper")
check(WhisperDictation.engine(pref: "whisper", cli: false, model: true) == "apple", "no whisper-cli -> apple")
check(WhisperDictation.engine(pref: "whisper", cli: true, model: false) == "apple", "no model -> apple")
check(WhisperDictation.engine(pref: "apple", cli: true, model: true) == "apple", "apple chosen")
check(WhisperDictation.tool("nope", exists: { _ in false }) == nil, "tool missing")
check(WhisperDictation.tool("whisper-cli", exists: { $0 == "/usr/local/bin/whisper-cli" }) == "/usr/local/bin/whisper-cli", "tool found")
// prompt
check(WhisperDictation.prompt(words: [], brand: []) == "", "empty prompt")
check(WhisperDictation.prompt(words: ["Saarth", " Alex "], brand: ["Zuka"]) == "Zuka, Saarth, Alex.", "prompt order")
check(WhisperDictation.prompt(words: ["zuka", "Saarth"], brand: ["Zuka"]) == "Zuka, Saarth.", "prompt dedupes")
let many = (0..<80).map { "word\($0)" }
let p = WhisperDictation.prompt(words: many, brand: ["OldBrand"])
check(p.count <= 200, "prompt is capped, got \(p.count)")
check(p.hasSuffix("word79."), "the newest words are kept")
check(!p.contains("OldBrand") && !p.contains("word0,"), "the oldest terms drop first")
check(WhisperDictation.prompt(words: [String(repeating: "x", count: 300)], brand: []) == "", "one huge term never breaks the cap")
// language + timeout
check(WhisperDictation.language("") == "auto" && WhisperDictation.language("EN") == "en" && WhisperDictation.language("../x") == "auto", "language")
check(WhisperDictation.timeout(audioSeconds: 5) == WhisperDictation.timeoutFloor && WhisperDictation.timeoutFloor == 4, "timeout floor is 4 s")
check(WhisperDictation.timeout(audioSeconds: 8) == 4 && WhisperDictation.timeout(audioSeconds: 9) == 4.5, "0.5 x audio for short takes")
check(abs(WhisperDictation.timeout(audioSeconds: 100) - 54) < 0.001, "0.5 x audio + 4 s for long takes (full window)")
check(WhisperDictation.timeout(audioSeconds: 12) > WhisperDictation.timeout(audioSeconds: 10), "long takes get more room than short ones")
// speed: short takes use the 12 s encoder window, long ones the full one; the vocabulary prompt needs the text context (-mc 0 dropped it)
check(WhisperDictation.isShort(audioSeconds: 8.4) && !WhisperDictation.isShort(audioSeconds: 11) && WhisperDictation.shortLimit * 50 < Double(WhisperDictation.shortContext), "short window covers the short limit")
let sa = WhisperDictation.serverArguments(model: "m.bin", port: 99, short: true), fa = WhisperDictation.serverArguments(model: "m.bin", port: 99, short: false)
check(sa.contains("-ac") && sa[sa.firstIndex(of: "-ac")! + 1] == "600" && !fa.contains("-ac"), "-ac only on the short server")
check(sa[sa.firstIndex(of: "-mc")! + 1] == "224" && fa[fa.firstIndex(of: "-mc")! + 1] == "224", "text context stays on so the prompt works")
check(sa.contains("127.0.0.1") && sa.contains("99"), "local only")
check(WhisperDictation.stripStamp("[00:00:00.000 --> 00:00:04.560]   Hello there.") == "Hello there." && WhisperDictation.stripStamp("Hello") == "Hello", "timestamp stripped")
// cleanup
func c(_ s: String) -> String { WhisperDictation.clean(s) }
check(c("Um, so we ship today.") == "So we ship today.", "leading filler: " + c("Um, so we ship today."))
check(c("uh... um I think so.") == "I think so.", "stacked fillers: " + c("uh... um I think so."))
check(c("We ship today, um.") == "We ship today.", "trailing filler: " + c("We ship today, um."))
check(c("Done. Um, uh.") == "Done.", "trailing fillers after a sentence: " + c("Done. Um, uh."))
check(c("I went to the the store and and bought milk.") == "I went to the store and bought milk.", "repeats: " + c("I went to the the store and and bought milk."))
check(c("No, no, no.") == "No, no, no.", "punctuated repeats are kept")
check(c("Premiere Pro, Submagic, and Higgsfield.") == "Premiere Pro, Submagic, and Higgsfield.", "punctuation and case untouched")
check(c("The yum and hummus.") == "The yum and hummus.", "fillers inside words untouched")
check(c("The user was errant.") == "The user was errant.", "er prefix untouched")
check(c("[BLANK_AUDIO]") == "", "non-speech tag")
check(c("  Hello\n there  ") == "Hello there", "whitespace")
check(c("Um.") == "", "only a filler")
// fallback
check(WhisperDictation.resolve(.success("Hello there."), apple: "hello").text == "Hello there.", "whisper wins")
let bad = WhisperDictation.resolve(.failure(WhisperError(errorDescription: "boom")), apple: "hello there")
check(bad.text == "hello there" && bad.fellBack && bad.why == "boom", "error -> apple")
let slow = WhisperDictation.resolve(nil, apple: "hello there")
check(slow.text == "hello there" && slow.fellBack && slow.why == "timed out", "timeout -> apple")
let empty = WhisperDictation.resolve(.success(" [BLANK_AUDIO] "), apple: "hello there")
check(empty.text == "hello there" && empty.fellBack, "empty whisper -> apple")
print("whisper pure ok")
'''
        self.assertIn('whisper pure ok', run_swift(self, swift, timeout=30))

    def test_recorder_writes_valid_wav_in_chunks(self):
        swift = 'import Foundation\nimport AVFoundation\n' + BLOCK + r'''
func check(_ ok: Bool, _ msg: String) { if !ok { print("FAIL: " + msg); exit(1) } }
let path = NSTemporaryDirectory() + "wavelength-dictation-test-\(UUID().uuidString).wav"
let rec = WhisperRecorder(path: path)!
let fmt = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 1)!   // not 16 kHz: converted on the way in
for _ in 0..<300 {   // 300 x 20 ms = 6 s, a long take is just more chunks
    let b = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: 960)!; b.frameLength = 960
    for i in 0..<960 { b.floatChannelData![0][i] = Float(sin(Double(i) / 10)) * 0.3 }
    rec.append(b)
}
let done = rec.finish()!
check(abs(done.seconds - 6) < 0.1, "length \(done.seconds)")
let data = try! Data(contentsOf: URL(fileURLWithPath: path))
check(data.prefix(4) == "RIFF".data(using: .ascii)! && data[8..<12] == "WAVE".data(using: .ascii)!, "wav header")
let size = data.count - 44
check(size == Int(done.seconds * 32000), "size \(size)")
check(data[24..<28] == Data([0x80, 0x3e, 0, 0]) && data[22] == 1, "16 kHz mono")
check(((try! FileManager.default.attributesOfItem(atPath: path))[.posixPermissions] as! Int) == 0o600, "private file")
let f = try! AVAudioFile(forReading: URL(fileURLWithPath: path))
check(f.processingFormat.sampleRate == 16000 && f.length > 90000, "AVAudioFile reads it back")
let r2 = WhisperRecorder(path: path + "2")!
check(r2.finish() == nil, "no audio -> nil")
r2.discard(); rec.discard()
check(!FileManager.default.fileExists(atPath: path), "discard deletes the file")
print("whisper recorder ok")
'''
        self.assertIn('whisper recorder ok', run_swift(self, swift, timeout=30))

    def test_runner_cli_fallback_timeout_and_server(self):
        swift = 'import Foundation\nimport AVFoundation\n' + BLOCK + r'''
func check(_ ok: Bool, _ msg: String) { if !ok { print("FAIL: " + msg); exit(1) } }
let root = NSTemporaryDirectory() + "wl-runner-\(UUID().uuidString)/"
try! FileManager.default.createDirectory(atPath: root, withIntermediateDirectories: true)
func script(_ name: String, _ body: String) -> String {
    let p = root + name; try! ("#!/bin/sh\n" + body + "\n").write(toFile: p, atomically: true, encoding: .utf8)
    chmod(p, 0o755); return p
}
let wav = root + "a.wav"; try! WhisperRecorder.header(dataBytes: 0).write(to: URL(fileURLWithPath: wav))
func run(cli: String, server: String? = nil, within: Double = 5) -> Result<String, Error> {
    var out: Result<String, Error>?
    WhisperRunner.shared.transcribe(wav: wav, lang: "en", prompt: "Zuka.", serverPath: server, cliPath: cli, model: "m.bin", within: within) { out = $0 }
    let end = Date().addingTimeInterval(within + 5)
    while out == nil && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
    return out ?? .failure(WhisperError(errorDescription: "never answered"))
}
// whisper-cli: the text comes back joined, and the vocabulary prompt and language reach it
let echo = script("cli-ok", "echo \"  Hello \"; echo \"there. $*\"")
if case .success(let t) = run(cli: echo) { check(t.hasPrefix("Hello there.") && t.contains("--prompt Zuka.") && t.contains("-l en") && t.contains("-mc 224") && t.contains("-ac 600") && !t.contains("-nt"), "cli text: \(t)") } else { check(false, "cli should succeed") }
check({ if case .failure = run(cli: script("cli-fail", "exit 3")) { return true }; return false }(), "cli failure is a failure")
let t0 = Date()
let slow = run(cli: script("cli-slow", "sleep 20"), within: 0.6)
check({ if case .failure(let e) = slow { return e.localizedDescription.contains("timed out") }; return false }() && Date().timeIntervalSince(t0) < 4, "cli timeout is enforced")
// whisper-server: warm, answer through HTTP, and a server that dies falls through to the cli
let server = script("fake-server", """
exec python3 - "$@" <<'PY'
import sys, http.server, re
a = sys.argv[1:]; port = int(a[a.index('--port') + 1])
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length'])).decode('latin1')
        f = lambda k: (re.search('name="%s"\\r\\n\\r\\n([^\\r]*)' % k, body) or [0, ''])[1]
        out = ('server heard lang=%s prompt=%s wav=%d' % (f('language'), f('prompt'), 'RIFF' in body)).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *x): pass
import time; time.sleep(0.8)
http.server.HTTPServer(('127.0.0.1', port), H).serve_forever()
PY
""")
let viaServer = run(cli: echo, server: server, within: 20)
if case .success(let t) = viaServer { check(t == "server heard lang=en prompt=Zuka. wav=1", "server answer: \(t)") } else { check(false, "server path failed: \(viaServer)") }
check(WhisperRunner.shared.serverRunning, "server stays warm after use")
let longAnswer = { () -> String in   // a long take goes to the full-window server (its own process), same answer path
    var out: Result<String, Error>?
    WhisperRunner.shared.transcribe(wav: wav, lang: "en", prompt: "Zuka.", serverPath: server, cliPath: echo, model: "m.bin", within: 20, audioSeconds: 40) { out = $0 }
    let end = Date().addingTimeInterval(25)
    while out == nil && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
    if case .success(let t)? = out { return t }; return "failed"
}()
check(longAnswer == "server heard lang=en prompt=Zuka. wav=1", "long take via the full server: \(longAnswer)")
WhisperRunner.shared.shutdown()
RunLoop.main.run(until: Date().addingTimeInterval(0.3))
check(!WhisperRunner.shared.serverRunning, "stop ends the server")
let dead = script("dead-server", "exit 1")
if case .success(let t) = run(cli: echo, server: dead, within: 10) { check(t.hasPrefix("Hello there."), "dead server -> cli: \(t)") } else { check(false, "dead server should fall back to the cli") }
WhisperRunner.shared.shutdown()
try? FileManager.default.removeItem(atPath: root)
print("whisper runner ok")
'''
        self.assertIn('whisper runner ok', run_swift(self, swift, timeout=60))


if __name__ == '__main__':
    unittest.main()
