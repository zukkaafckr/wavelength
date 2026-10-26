#!/usr/bin/env python3
"""Give your assistant its own name.

    python3 team/personalize.py NAME CALLNAME

NAME      what you will see and say: the app menu, window titles, persona line ("Nova", "Echo"...)
CALLNAME  what it calls you ("Sam")

Source files are NOT modified. The app reads the name (assistantName) and the call-name (userCallName) from its settings
at runtime, so one prebuilt app serves everyone; install.sh writes them into ~/.config/atticus/settings.json.
This script only validates the two words and records them in team/.personalized (read by install.sh and update.sh).
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = ROOT / "team" / ".personalized"
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 \-]{0,30}")


def main(argv):
    if len(argv) != 3 or not (SAFE.fullmatch(argv[1]) and SAFE.fullmatch(argv[2])):
        print(__doc__); print("Use letters, numbers, spaces and hyphens only (no quotes or accents), up to 31 characters."); return 2
    name, call = argv[1].strip(), argv[2].strip()
    MARK.write_text(f"name={name} call={call}\n")
    print(f"Your assistant is {name}; it calls you {call}. (Read from settings at runtime: no files were changed.)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
