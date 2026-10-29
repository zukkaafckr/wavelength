"""What each installed Mac app lets Zuka do, fastest way first: scripting, page bridge (Electron), accessibility, URL scheme.

`python3 zuka_caps.py` rewrites ~/.config/atticus/app-capabilities.json and prints a summary. Read-only: only looks inside app bundles.
"""
import glob
import json
import os
import plistlib
import sys

OUT = os.path.expanduser('~/.config/atticus/app-capabilities.json')
ROOTS = ('/Applications', '/Applications/Utilities', '/System/Applications', os.path.expanduser('~/Applications'))


def _plist(app):
    try:
        with open(os.path.join(app, 'Contents/Info.plist'), 'rb') as f:
            return plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        return {}


def classify(app):
    info = _plist(app)
    res = os.path.join(app, 'Contents/Resources')
    fw = os.path.join(app, 'Contents/Frameworks')
    schemes = sorted({s for u in info.get('CFBundleURLTypes', []) for s in u.get('CFBundleURLSchemes', [])})
    return {'bundle': info.get('CFBundleIdentifier', ''),
            'scriptable': bool(glob.glob(os.path.join(res, '*.sdef'))) or bool(info.get('OSAScriptingDefinition')) or bool(info.get('NSAppleScriptEnabled')),
            'electron': os.path.isdir(os.path.join(fw, 'Electron Framework.framework')),
            'chromium_embedded': os.path.isdir(os.path.join(fw, 'Chromium Embedded Framework.framework')),
            'schemes': schemes[:6]}


def scan():
    apps = {}
    for root in ROOTS:
        for app in sorted(glob.glob(os.path.join(root, '*.app')) + glob.glob(os.path.join(root, '*', '*.app'))):
            apps[os.path.basename(app)[:-4]] = classify(app)
    return apps


def best_route(c):
    return 'scripting' if c['scriptable'] else 'page-bridge' if c['electron'] else 'accessibility'


if __name__ == '__main__':
    apps = scan()
    for c in apps.values():
        c['route'] = best_route(c)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(apps, f, indent=1, sort_keys=True)
    by = {}
    for n, c in apps.items():
        by.setdefault(c['route'], []).append(n)
    print(len(apps), 'apps')
    for r, ns in by.items():
        print(f'{r}: {len(ns)}')
    if '-v' in sys.argv:
        for r, ns in by.items():
            print(r, '->', ', '.join(ns))
