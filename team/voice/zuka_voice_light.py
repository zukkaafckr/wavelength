"""Zuka's light voice for live replies: Kokoro with the same Heart+Bella blend her expressive voice was cloned from.

~300 MB and about a second per sentence on an 8 GB M1, so it can stay loaded while Premiere works. Same unix-socket
protocol as atticus_voice_server.py (play, "out" file, "warm", "ping"), same per-sentence moods (by pace and blend),
same voice memory and single-engine lock. Greetings and quick acks stay pre-recorded in her expressive voice.
"""
import fcntl, hashlib, json, os, queue, signal, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from atticus_voice_server import emotion, sentences, log, SOCK   # one place for mood rules and sentence splitting

KOKORO = os.path.expanduser("~/.local/share/kokoro")
CACHE, CACHE_MAX = os.path.join(HERE, "cache-light"), 400
MOODS = {   # Heart+Bella blend weight and pace: upbeat for good news, warm for normal lines, steady for problems
    "excited": (0.70, 1.12), "friendly": (0.80, 1.06), "calm": (0.90, 0.98),
}


def main():
    lock = open(os.path.join(HERE, "voice.lock"), "w")   # one engine at a time, shared with the expressive server
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: log("another voice engine is running; exiting"); return
    # normal priority on purpose: it works ~1 s per sentence, and a low-priority engine starves when the Mac is busy (39 s for two words)
    import soundfile as sf
    from kokoro_onnx import Kokoro
    t = time.time()
    k = Kokoro(f"{KOKORO}/kokoro-v1.0.int8.onnx", f"{KOKORO}/voices-v1.0.bin")
    heart, bella = k.get_voice_style("af_heart"), k.get_voice_style("af_bella")
    styles = {m: (heart * w + bella * (1 - w), speed) for m, (w, speed) in MOODS.items()}
    k.create("Ready.", voice=styles["friendly"][0], speed=1.0, lang="en-us")   # warm-up: the first real line is fast too
    log(f"light voice loaded in {time.time() - t:.1f}s")

    def clip_for(s, e):
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, hashlib.sha1(f"light|{e}|{' '.join(s.split()).lower()}".encode()).hexdigest()[:20] + ".wav")
        if os.path.exists(path):
            os.utime(path); return path, True
        style, speed = styles[e]
        audio, sr = k.create(s, voice=style, speed=speed, lang="en-us")
        sf.write(path + ".part.wav", audio, sr); os.replace(path + ".part.wav", path)
        old = sorted((os.path.join(CACHE, f) for f in os.listdir(CACHE) if f.endswith(".wav") and not f.endswith(".part.wav")), key=os.path.getmtime)
        for f in old[:-CACHE_MAX]:
            try: os.unlink(f)
            except OSError: pass
        return path, False

    if os.path.exists(SOCK): os.unlink(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK); os.chmod(SOCK, 0o600); srv.listen(8)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            conn, _ = srv.accept()
            with conn:
                try: serve(conn, clip_for)
                except OSError: pass
                except Exception as e: log("serve failed:", repr(e))
    finally:
        try: os.unlink(SOCK)
        except OSError: pass


def serve(conn, clip_for):
    f = conn.makefile("rb")
    try: req = json.loads(f.readline() or b"{}")
    except ValueError: return
    if req.get("ping"): conn.sendall(b"ok\n"); return
    text = (req.get("text") or "").strip()
    if not text: conn.sendall(b"ok\n"); return
    mood = lambda s: req.get("emotion") if req.get("emotion") in MOODS else emotion(s)
    if req.get("warm"):   # the answer is still streaming: record its finished first phrase into voice memory
        parts = sentences(text)
        if len(parts) >= 2: clip_for(parts[0], mood(parts[0]))
        conn.sendall(b"ok\n"); return
    if req.get("out"):   # render to one file, no playback
        import soundfile as sf, numpy as np
        chunks = []
        for s in sentences(text):
            path, _ = clip_for(s, mood(s)); a, sr = sf.read(path); chunks += [a, np.zeros(int(sr * 0.16))]
        if chunks: sf.write(req["out"], np.concatenate(chunks), sr)
        conn.sendall(b"ok\n"); return

    cancel = threading.Event()
    def watch():   # the client closing early means Zuka said stop
        try: f.read()
        except OSError: pass
        cancel.set()
    threading.Thread(target=watch, daemon=True).start()
    clips = queue.Queue()
    def play():
        while True:
            path = clips.get()
            if path is None or cancel.is_set(): return
            p = subprocess.Popen(["/usr/bin/afplay", path])
            while p.poll() is None:
                if cancel.is_set(): p.terminate(); return
                time.sleep(0.04)
    th = threading.Thread(target=play, daemon=True); th.start()
    for i, s in enumerate(sentences(text)):
        if cancel.is_set(): break
        e, t = mood(s), time.time()
        path, hit = clip_for(s, e)
        log(f"{e:8} {time.time() - t:4.1f}s {'[memory] ' if hit else ''}[light] {s[:60]}")
        if i == 0:
            try: conn.sendall(b"start\n")
            except OSError: pass
        clips.put(path)
    clips.put(None); th.join()
    if not cancel.is_set():
        try: conn.sendall(b"ok\n")
        except OSError: pass


if __name__ == "__main__":
    main()
