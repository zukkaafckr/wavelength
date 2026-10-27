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
        self.assertIn('"dictateEngine": "best"', SOURCE)
        self.assertIn('"dictateLang": "auto"', SOURCE)
        page = (ROOT / 'ui' / 'settings.html').read_text()
        self.assertIn('data-k="dictateEngine"', page)
        self.assertIn('Best — Apple live + Whisper', page)
        self.assertIn('Apple only', page)
        self.assertIn('Whisper only', page)
        self.assertIn('Free, runs on this Mac.', page)
        sys.path.insert(0, str(ROOT))
        import atticus
        self.assertEqual(atticus.picks()['dictateEngine'][1], {'Best — Apple live + Whisper': 'best', 'Apple only': 'apple', 'Whisper only': 'whisper'})

    def test_whisper_dictation_never_uses_claude_cleanup(self):
        start = SOURCE[SOURCE.index('dictateWhisper = WhisperDictation.active('):SOURCE.index('captureDictationSelection(); replacement = nil')]
        self.assertIn('dictateCleanup = false', start)   # dictation never calls Claude: the free DictationTidy cleanup replaced it
        self.assertIn('dictateTidy = Prefs.str("dictateMode") != "verbatim"', start)
        self.assertNotIn('sendDictationCleanup', BLOCK)
        self.assertNotIn('--dictate-cleanup', BLOCK)

    def test_release_flow_shows_transcribing_and_falls_back_to_apple(self):
        self.assertIn('dictateWhisper ? "Transcribing…"', SOURCE)
        flow = SOURCE[SOURCE.index('func whisperTranscribe('):SOURCE.index('func recordDictationEvent(')]
        self.assertIn('take.remaining', flow)   # key-up waits only for the pieces still in flight
        self.assertIn('WhisperDictation.resolve(result, apple: source)', flow)
        self.assertIn('WhisperDictation.garbled(r.text, apple: source)', flow)   # an empty or garbled Whisper answer falls back to Apple
        self.assertIn('removeItem(atPath: audio.path)', flow)   # the temp WAV is always deleted
        self.assertIn('finalizeDictation(r.text', flow)   # cleanup, then the existing insertion path (it applies dictateFixes)
        self.assertIn('DictationData.fixed(heard)', SOURCE[SOURCE.index('func insertDictation('):][:300])
        self.assertIn('lastDictation = value', SOURCE[SOURCE.index('func insertDictation('):][:400])   # the paste-last shortcut always has the words
        self.assertNotIn('sendDictationCleanup', SOURCE[SOURCE.index('func finalizeDictation('):SOURCE.index('func beginSpeechSegment(')])
        self.assertIn('rec?.append(out)', SOURCE)
        self.assertIn('rec?.append(buf)', SOURCE)

    def test_server_is_local_lazy_and_idle_stopped(self):
        self.assertIn('"--host", "127.0.0.1"', BLOCK)
        self.assertIn('idleSeconds = 2700.0', BLOCK)   # warm for 45 minutes
        self.assertIn('WhisperRunner.shared.warm(', SOURCE)
        self.assertIn('NSApplicationWillTerminateNotification', BLOCK)   # app quit stops the server

    def test_short_and_full_servers_and_long_take_chunking(self):
        self.assertIn('audioSeconds: j.seconds', BLOCK)   # the runner is told each piece's length to pick the server
        self.assertIn('rec.onChunk = {', SOURCE)   # finished stretches go to the server while the user is still talking
        self.assertNotIn('short: false)', SOURCE[SOURCE.index('func start(dictate'):SOURCE.index('func heard(')])   # no second 1 GB server for every long take
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
check(WhisperDictation.timeout(audioSeconds: 2) == WhisperDictation.timeoutFloor && WhisperDictation.timeoutFloor == 8, "timeout floor is 8 s")
check(WhisperDictation.timeout(audioSeconds: 8) == 10 && WhisperDictation.timeout(audioSeconds: 10) == 11, "0.5 x audio + 6 s for short pieces")
check(abs(WhisperDictation.timeout(audioSeconds: 100) - 74) < 0.001, "0.6 x audio + 14 s for long ones (full window)")
check(WhisperDictation.merges(pref: "best") && WhisperDictation.merges(pref: "") && !WhisperDictation.merges(pref: "whisper") && !WhisperDictation.merges(pref: "apple"), "only Best merges")
check(WhisperDictation.garbled("Hello", apple: "this is a much longer sentence that apple heard") && !WhisperDictation.garbled("Hello there my friend how are you", apple: "hello there my friend how are you"), "truncated whisper text is garbled")
check(WhisperDictation.garbled(Array(repeating: "thank you so much", count: 6).joined(separator: " "), apple: "thank you"), "a looping answer is garbled")
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

    def test_recorder_cuts_long_takes_at_pauses(self):
        swift = 'import Foundation\nimport AVFoundation\n' + BLOCK + r'''
func check(_ ok: Bool, _ msg: String) { if !ok { print("FAIL: " + msg); exit(1) } }
let fmt = AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)!
func record(_ plan: [(Double, Double)]) -> (chunks: [(String, Double, Bool)], tail: (path: String, seconds: Double, voiced: Bool)?, total: Double) {
    let path = NSTemporaryDirectory() + "wavelength-dictation-test-\(UUID().uuidString).wav"
    let rec = WhisperRecorder(path: path)!
    var chunks: [(String, Double, Bool)] = [], phase = 0.0
    rec.onChunk = { chunks.append(($0, $1, $2)) }
    for (seconds, amp) in plan {   // (length, loudness): 0 = a pause
        for _ in 0..<Int(seconds * 10) {   // 100 ms buffers
            let b = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: 1600)!; b.frameLength = 1600
            for i in 0..<1600 { phase += 0.07; b.floatChannelData![0][i] = Float(sin(phase)) * Float(amp) + Float.random(in: -0.0005...0.0005) }
            rec.append(b)
        }
    }
    let done = rec.finish()!
    let result = (chunks, rec.tail, done.seconds)
    return result
}
// speech, a short pause, speech, a pause, speech: cut at the pauses, nothing lost or doubled
let a = record([(6, 0.3), (0.6, 0), (7, 0.3), (0.5, 0), (4, 0.3)])
check(a.chunks.count == 2 && a.chunks.allSatisfy { $0.2 }, "two pieces and a tail: \(a.chunks.count)")
check(abs(a.chunks.map { $0.1 }.reduce(0, +) + a.tail!.seconds - a.total) < 0.01, "pieces + tail = the whole take")
check(a.chunks[0].1 > 5.5 && a.chunks[0].1 < 7.2, "first cut at the first pause: \(a.chunks[0].1)")
check(a.tail!.voiced && a.tail!.seconds < 6, "the tail is the last words: \(a.tail!.seconds)")
// no pause at all: still cut, no piece beyond the fast server's window
let b = record([(31, 0.3)])
check(b.chunks.count >= 2 && b.chunks.allSatisfy { $0.1 <= 10.5 } && b.tail!.seconds <= 10.5, "continuous speech is cut every <= 10.2 s: \(b.chunks.map { $0.1 })")
check(abs(b.chunks.map { $0.1 }.reduce(0, +) + b.tail!.seconds - b.total) < 0.01, "continuous: nothing lost")
// a short take is one piece (the tail is the file itself); a silent one is not voiced
let c = record([(3, 0.3)])
check(c.chunks.isEmpty && c.tail!.voiced && abs(c.tail!.seconds - 3) < 0.01, "short take: no cut")
let d = record([(4, 0)])
check(!d.tail!.voiced, "silence is not voiced")
// each piece is a valid WAV of its own
let f = try! AVAudioFile(forReading: URL(fileURLWithPath: a.chunks[0].0))
check(f.processingFormat.sampleRate == 16000 && abs(Double(f.length) / 16000 - a.chunks[0].1) < 0.01, "piece is a readable 16 kHz WAV")
print("whisper cut ok")
'''
        self.assertIn('whisper cut ok', run_swift(self, swift, timeout=90))

    def test_take_sends_pieces_in_order_with_context_and_joins_them(self):
        swift = 'import Foundation\nimport AVFoundation\n' + BLOCK + r'''
func check(_ ok: Bool, _ msg: String) { if !ok { print("FAIL: " + msg); exit(1) } }
check(WhisperTake.join(["We went to the store and.", "Bought some milk.", "Then we left."]) == "We went to the store and Bought some milk. Then we left.", "dangling full stop goes: " + WhisperTake.join(["We went to the store and.", "Bought some milk."]))
check(WhisperTake.join(["We went to the store and.", "The milk was cold."]) == "We went to the store and the milk was cold.", "next piece carries on in lower case")
check(WhisperTake.join(["First sentence.", "", "Second sentence."]) == "First sentence. Second sentence.", "whole sentences stay")
check(WhisperTake.context("Zuka.", ["", "Hello there."]) == "Zuka. Hello there." && WhisperTake.context("Zuka.", []) == "Zuka.", "context is the vocabulary plus the last words")
check(WhisperTake.context("", [String(repeating: "word ", count: 80)]).count <= 140, "context is capped")
let root = NSTemporaryDirectory() + "wl-take-\(UUID().uuidString)/"
try! FileManager.default.createDirectory(atPath: root, withIntermediateDirectories: true)
func script(_ name: String, _ body: String) -> String { let p = root + name; try! ("#!/bin/sh\n" + body + "\n").write(toFile: p, atomically: true, encoding: .utf8); chmod(p, 0o755); return p }
let server = script("fake-server", """
exec python3 - "$@" <<'PY'
import sys, http.server, re
a = sys.argv[1:]; port = int(a[a.index('--port') + 1]); n = [0]
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length'])).decode('latin1')
        n[0] += 1
        prompt = (re.search('name="prompt"\\\\r\\\\n\\\\r\\\\n([^\\\\r]*)', body) or [0, ''])[1]
        out = ('Piece %d heard %s.' % (n[0], 'after piece ' + prompt.split('Piece ')[-1][:1] if 'Piece' in prompt else 'first')).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *x): pass
import time; time.sleep(0.5)
http.server.HTTPServer(('127.0.0.1', port), H).serve_forever()
PY
""")
func wav(_ name: String) -> String { let p = root + name; try! WhisperRecorder.header(dataBytes: 32000).write(to: URL(fileURLWithPath: p)); return p }
let take = WhisperTake(lang: "en", prompt: "Zuka.", serverPath: server, cliPath: "/usr/bin/false", model: "m.bin")
take.add(wav: wav("a.wav"), seconds: 1, voiced: true, own: false)    // sent while the user is still talking
take.add(wav: wav("silence.wav"), seconds: 1, voiced: false, own: false)   // silence is never sent
check(take.remaining > 0 && take.pieces == 2, "pieces in flight: \(take.pieces)")
take.add(wav: wav("b.wav"), seconds: 1, voiced: true, own: false)    // the tail
var result: Result<String, Error>?
take.finish { result = $0 }
let end = Date().addingTimeInterval(30)
while result == nil && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
if case .success(let t)? = result { check(t == "Piece 1 heard first. Piece 2 heard after piece 1.", "ordered, with context: \(t)") } else { check(false, "take should succeed: \(String(describing: result))") }
// a failing server path (and no working cli) fails the take so the caller uses Apple's text
let bad = WhisperTake(lang: "en", prompt: "", serverPath: nil, cliPath: script("cli-fail", "exit 3"), model: "m.bin")
bad.add(wav: wav("c.wav"), seconds: 1, voiced: true, own: false)
var failed: Result<String, Error>?
bad.finish { failed = $0 }
while failed == nil && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
check({ if case .failure? = failed { return true }; return false }(), "a failed piece fails the take")
// aborting removes queued pieces and never calls back
let gone = WhisperTake(lang: "en", prompt: "", serverPath: nil, cliPath: script("cli-slow", "sleep 5"), model: "m.bin")
var called = false
gone.add(wav: wav("d.wav"), seconds: 1, voiced: true, own: false); gone.finish { _ in called = true }; gone.abort()
RunLoop.main.run(until: Date().addingTimeInterval(0.5))
check(!called, "aborted takes stay quiet")
WhisperRunner.shared.shutdown()
RunLoop.main.run(until: Date().addingTimeInterval(0.3))
try? FileManager.default.removeItem(atPath: root)
print("whisper take ok")
'''
        self.assertIn('whisper take ok', run_swift(self, swift, timeout=90))

    def test_cleanup_like_wispr_flow(self):
        swift = 'import Foundation\nimport AVFoundation\n' + BLOCK + r'''
func check(_ ok: Bool, _ msg: String) { if !ok { print("FAIL: " + msg); exit(1) } }
let real: Set<String> = ["field", "hicks", "start", "premier", "clod", "cache", "cash"]
func t(_ s: String, _ style: DictationTidy.Style = .formal, terms: [String] = [], soft: [String] = [], apple: String? = nil) -> String {
    DictationTidy.tidy(s, style: style, terms: terms, soft: soft, isWord: { real.contains($0.lowercased()) }, apple: apple)
}
var misses: [String] = []
func eq(_ got: String, _ want: String, _ why: String) { if got != want { misses.append(why + ": got [\(got.replacingOccurrences(of: "\n", with: "\\n"))] want [\(want.replacingOccurrences(of: "\n", with: "\\n"))]") } }
// fillers and stutters
eq(t("Um, so we should ship it, uh, today."), "So we should ship it today.", "fillers")
eq(t("you know we ship today and like, it works"), "We ship today and it works.", "you know / like")
eq(t("I like pizza and I like, you know, pasta"), "I like pizza and I like pasta.", "real 'like' stays")
eq(t("I went to the the store and and bought milk"), "I went to the store and bought milk.", "stutters")
// self-corrections
eq(t("Let's meet at 5, no wait, 6 tomorrow."), "Let's meet at 6 tomorrow.", "number fix")
eq(t("Let's meet at five pm, no wait, six pm."), "Let's meet at 6 pm.", "time fix")
eq(t("The red one, no wait, the blue one."), "The blue one.", "phrase fix")
eq(t("Send it to John, I mean Jack, tomorrow."), "Send it to Jack, tomorrow.", "I mean")
eq(t("I mean it, thanks."), "I mean it, thanks.", "I mean without a pause is kept")
eq(t("Send the report. Scratch that. Send the invoice to Priya."), "Send the invoice to Priya.", "scratch that after a sentence")
eq(t("Send the report, scratch that, send the invoice"), "Send the invoice", "scratch that mid sentence")
eq(t("Scratch that"), "", "scratch that alone")
// spoken punctuation
eq(t("Hello comma how are you question mark"), "Hello, how are you?", "comma and question mark")
eq(t("Thanks for the update full stop new line talk soon exclamation point"), "Thanks for the update.\nTalk soon!", "full stop, new line, exclamation point")
eq(t("Dear Sam new paragraph thanks for the note"), "Dear Sam\n\nThanks for the note.", "new paragraph")
eq(t("The quarterly numbers are fine period"), "The quarterly numbers are fine.", "period at the end")
eq(t("A comma is a punctuation mark in this period of time"), "A comma is a punctuation mark in this period of time.", "real words stay")
// numbers and times
eq(t("See you at five thirty pm"), "See you at 5:30 pm.", "time")
eq(t("It costs twenty five dollars and takes ten minutes"), "It costs $25 and takes 10 minutes.", "money and units")
eq(t("About forty percent more people finished"), "About 40% more people finished.", "percent")
eq(t("I have one day and two dogs"), "I have one day and two dogs.", "small numbers stay words")
// lists
eq(t("First, fix the build. Second, update the docs. Third, ship it."), "1. Fix the build\n2. Update the docs\n3. Ship it.", "first second third")
eq(t("Here is the plan. First we fix the build and second we update the docs"), "Here is the plan:\n1. We fix the build\n2. We update the docs", "list with a lead-in")
eq(t("One, apples. Two, bananas. Three, milk."), "1. Apples\n2. Bananas\n3. Milk.", "one two three")
eq(t("The second time I tried it worked"), "The second time I tried it worked.", "a lone ordinal is not a list")
// vocabulary (fuzzy) and Apple's evidence
eq(t("We use hicks field and sub magic with premiere pro daily", terms: ["Higgsfield", "Submagic", "Premiere Pro"]), "We use Higgsfield and Submagic with Premiere Pro daily.", "brand words")
eq(t("ask clod about it", terms: ["Claude"], apple: "ask Claude about it"), "Ask Claude about it.", "Apple heard the term")
eq(t("ask the cash about it", terms: ["Claude"]), "Ask the cash about it.", "real words are never swapped")
eq(t("I met sarth yesterday", terms: ["Saarth"]), "I met Saarth yesterday.", "a personal name")
eq(t("open the premier pro app", soft: ["Premiere Pro"]), "Open the Premiere Pro app.", "app names fix non-words only: premier is a real word here")
eq(t("Bhai kya hai yaar, the plan is fine", terms: ["Kyaa"]), "Bhai kya hai yaar, the plan is fine.", "Hinglish is left as spoken")
// capitals, sentence ends, tone
eq(t("i think i know"), "I think I know.", "capital I")
eq(t("Sounds good.", .casual), "Sounds good", "chat: no full stop on a short message")
eq(t("Sounds good. Send it over.", .casual), "Sounds good. Send it over.", "chat keeps two sentences")
eq(t("git commit um dash m", .verbatim), "git commit um dash m", "code editors stay verbatim")
eq(t("see you e.g. tomorrow. okay"), "See you e.g. tomorrow. Okay.", "abbreviations keep their case")
eq(t("Um."), "", "only a filler")
// continuing what is in the field
eq(DictationTidy.continuing("Then we left.", after: "We went out and"), " then we left.", "mid-sentence: space, no capital")
eq(DictationTidy.continuing("Then we left.", after: "We went out.\n"), "Then we left.", "new line: untouched")
eq(DictationTidy.continuing("I agree.", after: "Yes,"), " I agree.", "I stays capital")
// styles
check(DictationTidy.style(bundle: "com.tinyspeck.slackmacgap") == .casual && DictationTidy.style(bundle: "com.apple.Terminal") == .verbatim && DictationTidy.style(bundle: "com.apple.mail") == .formal, "app tone")
check(DictationTidy.style(bundle: "com.google.Chrome", title: "general | Acme | Slack") == .casual && DictationTidy.style(bundle: "com.google.Chrome", title: "Inbox - Gmail") == .formal, "browser tab tone")
check(misses.isEmpty, misses.joined(separator: " | "))
print("whisper tidy ok")
'''
        self.assertIn('whisper tidy ok', run_swift(self, swift, timeout=60))

    def test_local_model_polish_must_keep_the_meaning(self):
        swift = 'import Foundation\nimport AVFoundation\n' + BLOCK + r'''
func check(_ ok: Bool, _ msg: String) { if !ok { print("FAIL: " + msg); exit(1) } }
let a = "we should meet at 5 tomorrow to discuss the plan for the launch"
check(LocalPolish.keepsMeaning(a, "We should meet at 5 tomorrow to discuss the plan for the launch."), "capital and full stop are fine")
check(!LocalPolish.keepsMeaning(a, "We should meet at 6 tomorrow to discuss the plan for the launch."), "a changed number is rejected")
check(!LocalPolish.keepsMeaning(a, "Let us gather tomorrow afternoon to talk through everything about the launch plan."), "rewording is rejected")
check(!LocalPolish.keepsMeaning(a, "We should meet at 5 tomorrow."), "dropped words are rejected")
check(!LocalPolish.keepsMeaning(a, a + " and then we should also review the budget and the hiring plan for the quarter"), "added content is rejected")
check(LocalPolish.eligible(a) && !LocalPolish.eligible("too short to bother") && !LocalPolish.eligible(a + "\nnew line") && !LocalPolish.eligible("bhai kya hai yaar we should meet tomorrow to discuss the plan for the launch"), "eligibility: 12+ words, one line, no Hinglish")
setenv("ZUKA_CHAT_URL", "http://127.0.0.1:9", 1)   // nothing listens there: Ollama is down
// Ollama down: the answer is nil at once and the deterministic text stays
var out: String?? = nil
LocalPolish.polish(a, budget: 1.2) { out = .some($0) }
let end = Date().addingTimeInterval(3)
while out == nil && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
check(out != nil && out! == nil, "no model server -> nil")
print("whisper polish ok")
'''
        self.assertIn('whisper polish ok', run_swift(self, swift, timeout=60))


if __name__ == '__main__':
    unittest.main()
