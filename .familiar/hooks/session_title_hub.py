#!/usr/bin/env python3
"""session_title_hub.py - SessionStart hook: title a fleet hub session "familiar hub" or "familiar hub: <categories>".

The hub is not a project and has no signature, so it is told apart by its own `hub-settings.md`. A hub
scoped to one category (`categories: work`) is titled with it, so two hubs on one phone list read
differently. A session that already has a title is left alone, and a folder with no `hub-settings.md`
above it is ignored.

Reads the SessionStart event JSON on stdin; prints one JSON line on stdout. Never fails loudly.
Standard library only.
"""

# familiar's floor is Python 3.10. On anything older, stop with a plain message instead of a traceback.
import sys
if sys.version_info < (3, 10):
    sys.exit("familiar needs Python 3.10 or newer, but this is Python %d.%d (%s). Install Python 3.10+ "
             "(.familiar/scripts/doctor.py says how), then run this again with it." % (*sys.version_info[:2], sys.executable))

import json
import os
import re

CATEGORIES = re.compile(r"^\s*-\s*categories:\s*(.+?)\s*$", re.I | re.M)


def hub_root(start):
    root = os.path.abspath(start)
    while not os.path.isfile(os.path.join(root, "hub-settings.md")):
        parent = os.path.dirname(root)
        if parent == root:
            return None
        root = parent
    return root


def build_title(root):
    try:
        with open(os.path.join(root, "hub-settings.md"), encoding="utf-8") as f:
            match = CATEGORIES.search(f.read())
    except OSError:
        match = None
    scope = match.group(1) if match else "all"
    return "familiar hub" if scope.lower() == "all" else f"familiar hub: {scope}"


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(event, dict) or event.get("session_title"):
        return
    root = hub_root(event.get("cwd") or os.getcwd())
    if root is None:
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "sessionTitle": build_title(root)}}))


if __name__ == "__main__":
    main()
