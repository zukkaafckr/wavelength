"""Atticus voice server: Chatterbox Turbo on CPU, one sentence at a time, emotion picked per sentence.

Started on demand by atticus-say; listens on voice.sock; exits after IDLE_MIN minutes without a request
so the model's memory is given back. A client that disconnects (Atticus stopped speaking) cancels playback.
"""
import fcntl, hashlib, json, os, queue, re, signal, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
SOCK = os.path.join(HERE, "voice.sock")
def _idle_min():
    """Minutes of silence before the model unloads (0: stay loaded). The env var wins (the login agent sets it), then the
    install's idle-min file next to this script (set for small-memory Macs), then 480."""
    try:
        return float(os.environ.get("ATTICUS_VOICE_IDLE_MIN") or open(os.path.join(HERE, "idle-min")).read().strip())
    except (OSError, ValueError):
        return 480.0


IDLE_MIN = _idle_min()
VOICES = {e: os.path.join(HERE, "voices", f"{e}.wav") for e in ("excited", "friendly", "calm")}

CALM = re.compile(r"\b(fail|failed|error|errors|can't|cannot|couldn't|can not|sorry|problem|wrong|not found|denied|blocked|"
                  r"unable|missing|crash|crashed|warning|issue|unfortunately|no luck|isn't working|didn't work|too low|almost full)\b", re.I)
EXCITED = re.compile(r"\b(done|ready|finished|found|saved|exported|nice|great|awesome|yay|perfect|opened|playing|all set|"
                     r"success|here you go|got it|love|amazing|congrats|woohoo|yes|ta-da|sent|booked|added)\b", re.I)


def emotion(sentence):
    if CALM.search(sentence):
        return "calm"
    if EXCITED.search(sentence) or sentence.rstrip().endswith("!"):
        return "excited"
    return "friendly"


def sentences(text):
    parts, out = re.split(r"(?<=[.!?])\s+", " ".join(text.split())), []
    for p in parts:
        while len(p) > 220:   # Turbo drifts on long input: break at a comma near the limit
            cut = p.rfind(",", 0, 220)
            cut = cut if cut > 60 else 220
            out.append(p[:cut + 1].strip()); p = p[cut + 1:].strip()
        if p:
            if out and len(out[-1]) < 25 and emotion(out[-1]) == emotion(p):   # tiny fragments ("Done!") ride with a same-mood sentence
                out[-1] = out[-1] + " " + p
            else:
                out.append(p)
    return out


FREE_MIN = 20   # % of RAM free below which the model gives its memory back
BUSY = threading.Event()   # set while a request is being spoken or rendered


def memory_guard():
    """8 GB Mac: when free memory stays under FREE_MIN for ~30 s and nothing is being spoken, give the model's memory back.
    atticus-say starts the server again on the next reply."""
    strikes = 0
    while True:
        time.sleep(15)
        try:   # the kernel's pressure flag stays raised long after pressure ends; free percentage is the honest number
            out = subprocess.run(["/usr/bin/memory_pressure"], capture_output=True, text=True, timeout=5).stdout
            free = int(re.search(r"free percentage: (\d+)%", out)[1])
        except (OSError, TypeError, ValueError, subprocess.TimeoutExpired): continue
        strikes = strikes + 1 if free < FREE_MIN and not BUSY.is_set() else 0
        if strikes >= 2:
            log(f"only {free}% memory free: unloading")
            try: os.unlink(SOCK)
            except OSError: pass
            os._exit(0)


CACHE, CACHE_MAX = os.path.join(HERE, "cache"), 300   # Zuka voice memory: ~200 KB a clip, oldest dropped first


def clip_for(model, conds, ta, s, e):
    """A sentence she has said before in the same mood plays from disk instead of ~6 s of generation."""
    os.makedirs(CACHE, exist_ok=True)
    try: ref = int(os.path.getmtime(VOICES[e]))   # a re-recorded mood sample retires its old clips
    except OSError: ref = 0
    path = os.path.join(CACHE, hashlib.sha1(f"{e}|{ref}|{' '.join(s.split()).lower()}".encode()).hexdigest()[:20] + ".wav")
    if os.path.exists(path):
        os.utime(path); return path, True
    model.conds = conds[e]
    ta.save(path + ".part.wav", model.generate(s), model.sr); os.replace(path + ".part.wav", path)
    old = sorted((os.path.join(CACHE, f) for f in os.listdir(CACHE) if f.endswith(".wav") and not f.endswith(".part.wav")), key=os.path.getmtime)
    for f in old[:-CACHE_MAX]:
        try: os.unlink(f)
        except OSError: pass
    return path, False


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def main():
    lock = open(os.path.join(HERE, "voice.lock"), "w")   # one engine at a time: a second start (login + on-demand) just leaves
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: log("another voice engine is running; exiting"); return
    os.nice(5)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    log_file = os.path.expanduser("~/.config/atticus/voice.log")   # capped: keep the newest ~200 KB of a log over 2 MB
    try:
        if os.path.getsize(log_file) > 2_000_000:
            with open(log_file, "rb") as f: f.seek(-200_000, 2); tail = f.read()
            with open(log_file, "wb") as f: f.write(tail)
    except OSError: pass   # the model is cached: never wait on the internet, so the voice works offline
    import torch, torchaudio as ta
    _load = torch.load
    torch.load = lambda *a, **k: _load(*a, **{**k, "map_location": torch.device("cpu")})
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    t = time.time()
    model = ChatterboxTurboTTS.from_pretrained(device="cpu")
    conds = {}
    for e, path in VOICES.items():
        model.prepare_conditionals(path)
        conds[e] = model.conds
    log(f"loaded in {time.time() - t:.0f}s")

    if os.path.exists(SOCK):
        os.unlink(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK); os.chmod(SOCK, 0o600); srv.listen(4)
    srv.settimeout(IDLE_MIN * 60 if IDLE_MIN > 0 else None)   # 0: stay loaded (the login agent runs it that way)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    tmp = tempfile.mkdtemp(prefix="atticus-voice-")
    threading.Thread(target=memory_guard, daemon=True).start()

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                log("idle, exiting"); return
            with conn:
                BUSY.set()
                try: serve(conn, model, conds, ta, tmp)
                except OSError: pass   # a client that vanished must not take the server down
                except Exception as e: log("serve failed:", repr(e))   # one bad sentence must not cost a 25 s reload
                finally: BUSY.clear()
    finally:
        try: os.unlink(SOCK)
        except OSError: pass


def serve(conn, model, conds, ta, tmp):
    f = conn.makefile("rb")
    try:
        req = json.loads(f.readline() or b"{}")
    except ValueError:
        return
    if req.get("ping"):
        conn.sendall(b"ok\n"); return
    text = (req.get("text") or "").strip()
    if not text:
        conn.sendall(b"ok\n"); return

    out = req.get("out")
    if out:   # render-to-file mode (phone bridge): no playback, one concatenated wav
        import torch
        parts = []
        for i, s in enumerate(sentences(text)):
            e = req.get("emotion") if req.get("emotion") in conds else emotion(s)
            t = time.time()
            path, hit = clip_for(model, conds, ta, s, e)
            wav, sr = ta.load(path)
            parts.append(wav.reshape(1, -1) if sr == model.sr else ta.functional.resample(wav, sr, model.sr).reshape(1, -1))
            parts.append(torch.zeros(1, int(model.sr * 0.18)))
            log(f"{e:8} {time.time() - t:4.1f}s  [file]{' [memory]' if hit else ''} {s[:60]}")
        if parts:
            ta.save(out, torch.cat(parts, dim=1), model.sr)
        try: conn.sendall(b"ok\n")
        except OSError: pass
        return

    cancel = threading.Event()
    def watch():   # the client closing early means Atticus said stop
        try: f.read()
        except OSError: pass
        cancel.set()
    threading.Thread(target=watch, daemon=True).start()

    clips, player = queue.Queue(), {"p": None}
    def play():
        while True:
            path = clips.get()
            if path is None or cancel.is_set():
                return
            p = player["p"] = subprocess.Popen(["/usr/bin/afplay", path])
            while p.poll() is None:
                if cancel.is_set():
                    p.terminate(); return
                time.sleep(0.05)
    th = threading.Thread(target=play, daemon=True); th.start()

    for i, s in enumerate(sentences(text)):
        if cancel.is_set():
            break
        e = req.get("emotion") if req.get("emotion") in conds else emotion(s)
        t = time.time()
        path, hit = clip_for(model, conds, ta, s, e)   # cached clips are kept; only tmp/ is emptied after playback
        log(f"{e:8} {time.time() - t:4.1f}s {'[memory] ' if hit else ''} {s[:60]}")
        clips.put(path)
    clips.put(None)
    th.join()
    for name in os.listdir(tmp):
        try: os.unlink(os.path.join(tmp, name))
        except OSError: pass
    if not cancel.is_set():
        try: conn.sendall(b"ok\n")
        except OSError: pass


if __name__ == "__main__":
    main()
