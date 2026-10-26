#!/usr/bin/env python3
"""Give your assistant its own name.

    python3 team/personalize.py NAME CALLNAME

NAME      what you will see and say: the app name, menu, window titles, persona line ("Nova", "Echo"...)
CALLNAME  what it calls you ("Sam")

Rewrites the visible name "Zuka" to NAME and the call-name "J" in the offline message to CALLNAME. Internal names
(Atticus.swift, the com.atticus.app bundle id, ~/.atticus, environment variables) are left alone so updates still work.
Runs once per copy: it leaves team/.personalized behind and refuses to run again.
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = ROOT / "team" / ".personalized"
FILES = [*sorted((ROOT / "ui").glob("*.html")), ROOT / "Atticus.swift", ROOT / "atticus.py", ROOT / "build.sh", ROOT / "tests" / "test_zuka.py"]
OFFLINE = ", J. I can still open and arrange apps"
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 \-]{0,30}")


def main(argv):
    if len(argv) != 3 or not (SAFE.fullmatch(argv[1]) and SAFE.fullmatch(argv[2])):
        print(__doc__); print("Use letters, numbers, spaces and hyphens only (no quotes or accents), up to 31 characters."); return 2
    name, call = argv[1].strip(), argv[2].strip()
    if MARK.exists():
        print(f"Already personalised ({MARK.read_text().strip()}). Start from a fresh copy of the repo to change the name."); return 1
    counts = {}
    for path in FILES:
        text = path.read_text()
        new, n = re.subn(r"\bZuka\b", name, text)
        if path.name == "atticus.py":
            if OFFLINE not in new:
                print("The offline message was not found; is this the team edition?"); return 1
            new, c = new.replace(OFFLINE, f", {call}. I can still open and arrange apps"), 1
            n += c
        if n:
            path.write_text(new); counts[str(path.relative_to(ROOT))] = n
    MARK.write_text(f"name={name} call={call}\n")
    for f, n in counts.items():
        print(f"{n:4}  {f}")
    print(f"{sum(counts.values()):4}  total. Your assistant is {name}; it calls you {call}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
