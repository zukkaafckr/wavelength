#!/bin/bash
# Wavelength installs through Claude Code, which first asks your assistant's name, what it calls you, your Mac and your voice choice.
# Open Claude Code and paste:  Set up my own copy of this Mac assistant from <this repo's link>. Read its CLAUDE.md first and follow it.
# By hand: python3 team/personalize.py "NAME" "CALLNAME" && bash team/install.sh [--voice] --ram-gb <8|16|...>
echo "Wavelength installs through Claude Code. See README.md, or run: python3 team/personalize.py NAME CALLNAME && bash team/install.sh --ram-gb 8"
exit 1
