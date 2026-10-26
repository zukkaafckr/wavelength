# Instructions for Claude Code: set up a teammate's own Wavelength assistant

A teammate has pasted this repo's link and wants their own copy of Wavelength, this Mac assistant. The app is called Wavelength; the assistant inside it gets the name they choose. It is a friendly helper that
lives in the menu bar: they press a shortcut, talk, and it does things on their Mac. Be warm and plain. No jargon:
say "the voice", not "TTS"; say "your Mac's memory", not "RAM"; skip words like venv, LaunchAgent, build.

## Step 0. Ask first, before you run anything

Use your question tool (AskUserQuestion) to ask these four things (plus one follow-up in question 4 if they choose the natural voice). Do not clone, install or change anything until they answer.

1. "What would you like to name your assistant?" (example: Zuka)
2. "What should it call you?" (example: J)
3. "Which Mac do you have, and how much memory does it have?" Check for them first with `sysctl hw.memsize` (divide by 1073741824 for GB) and `sw_vers`, then ask them to confirm what you found. The assistant needs macOS 26 or newer; if they are older, stop and explain kindly.
4. "Do you want the natural voice, or the free Mac voice?" Explain: the natural voice sounds like a person, is light and fast (about a 350 MB download, replies start almost instantly), works on any Mac including 8 GB ones, and works offline once set up. The free Mac voice is built in, instant, and sounds more robotic. Only if they choose the natural voice, ask one follow-up: "Do you also want extra-expressive greetings?" Explain: the time-of-day hellos are recorded once in a richer, more emotional voice. It is an extra 4 GB download and takes a while, and it is best on a Mac with 16 GB of memory; everyday replies stay in the light voice either way. Default to no.

Name and call-name: letters, numbers, spaces and hyphens only. If they want an accent or an apostrophe, suggest the plain spelling.

## Step 1. Install

1. This repo is private: they need to have accepted the GitHub invite and be signed in (`gh auth status`; if not, `gh auth login`, they sign in themselves). Clone it into `~/Projects/` (for example `git clone <the link they pasted> ~/Projects/<name-in-lowercase>`) and `cd` into it. If the folder already exists, ask before touching it.
2. Run `python3 team/personalize.py "NAME" "CALLNAME"`. It runs once per copy. If it says "Already personalised", leave the name as it is and tell them how to start from a fresh copy to change it.
3. Run `bash team/install.sh` with the right flags:
   - add `--voice` only if they chose the natural voice
   - add `--expressive` as well (`--voice --expressive`) only if they chose the extra-expressive greetings
   - no memory flag is needed any more (`--ram-gb` is accepted and ignored)
   - Examples: `bash team/install.sh --voice` or `bash team/install.sh --voice --expressive`
   The natural voice download is small (about 350 MB); the extra-expressive option is large (about 4 GB), so tell them it will take a while and keep them company. Never use sudo. If a step needs something missing (Claude Code, Apple's command line tools, uv for the voice), tell them the one thing to do, then rerun.
4. The installer opens the app. If it did not, open `~/Applications/Atticus.app` (it shows up as **Wavelength** in Spotlight and the Dock; menu items and replies use their assistant's name).

## Step 2. Walk them through permissions

The app's own setup window guides this. Stay with them and explain each ask in one friendly line: Microphone (so it can hear them), Speech Recognition (to turn speech into text on their Mac), Accessibility and Screen Recording (so it can see and move things), Automation and Calendar (only if they use it). Let them click Allow themselves. Then have them try the talk shortcut shown in the setup window: press it, wait for the greeting (natural voice only), say something like "open Notes".

## Things to tell them (in your own words)

- **It asks before it uses your Claude plan.** Opening apps, moving windows, playing music, running shortcuts: free, instant, never asks. Anything that needs Claude's thinking asks you first ("this uses your Claude plan, okay?"). This is on by default and can be changed in Settings.
- **It never spends money beyond their plan.** It runs on their Claude plan only (no API key). Tell them to check claude.ai → Settings → Usage and keep "extra usage" switched off, so nothing is ever charged once they hit a limit.
- **It works offline for the free things.** With no internet it says what it can still do instead of failing.
- **Paid creative tools are blocked on purpose.** It will never use Atria or Higgsfield, because those spend paid credits. Use them yourself in the browser.
- **No data leaves the Mac by default:** no telemetry, no background updates. Updates happen only when you ask (see below).
- **Check-ins:** a short spoken hello on weekdays (10:00, 14:30, 18:30) when you are at your Mac. Turn it off with Pause in the menu bar, or ask to remove it.

## Updating later

Never update on your own. If asked: `git fetch upstream-atticus` shows what the original Atticus changed; merge only if they want it, then rebuild with `./build.sh`. Their assistant name lives in the files, so work from the same copy.

## Never

Never copy anything from another person's `~/.config/atticus`. Never push to GitHub or publish: Wavelength is private to the team (see LICENSE-WAVELENGTH). Never run `sudo`.
