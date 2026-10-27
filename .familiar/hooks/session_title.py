#!/usr/bin/env python3
"""session_title.py - SessionStart hook: title each Claude Code session "(<signature>) <project name>".

Remote Control lists sessions by title, and an untitled one gets a generic machine-and-word name. This
sets the title from the project itself, with the same effect as /rename:

    (o-o) Northgate Depot Study

The signature is read the way the bind line reads it (the project's `5-System/user-preferences.md`,
then `~/.familiar/user-preferences.md`). The brackets are copied from the bind-line template in the
project's own AGENTS.md, so they follow if that template changes. The name is the project config's
title, or the folder name while that is unset. A session that already has a title (--name, /rename,
another hook) is left alone, and a folder with no `.familiar-project` marker above it is ignored.

Reads the SessionStart event JSON on stdin; prints one JSON line on stdout. Never fails loudly: any
problem means no title, not an error. Standard library only.
"""

# familiar's floor is Python 3.10. On anything older, stop with a plain message instead of a traceback.
import sys
if sys.version_info < (3, 10):
    sys.exit("familiar needs Python 3.10 or newer, but this is Python %d.%d (%s). Install Python 3.10+ "
             "(.familiar/scripts/doctor.py says how), then run this again with it." % (*sys.version_info[:2], sys.executable))

import json
import os
import re

SIGNATURE = re.compile(r"^\s*-\s*\*\*familiar signature:\*\*\s*(\S+)", re.I | re.M)
CONFIG_TITLE = re.compile(r"^#\s*Project Config\s*[—-]\s*(.+?)\s*$", re.M)
BIND_TEMPLATE = re.compile(r"\*(\W{0,2})<signature>(\W{0,2}) familiar bound\*")


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def project_root(start):
    root = os.path.abspath(start)
    while not os.path.exists(os.path.join(root, ".familiar-project")):
        parent = os.path.dirname(root)
        if parent == root:
            return None
        root = parent
    return root


def build_title(root):
    signature = ""
    for path in (os.path.join(root, "5-System", "user-preferences.md"),
                 os.path.join(os.path.expanduser("~"), ".familiar", "user-preferences.md")):
        match = SIGNATURE.search(read(path))
        if match:
            signature = match.group(1).strip("`")
            break

    name = ""
    match = CONFIG_TITLE.search(read(os.path.join(root, "5-System", "project-config.md")))
    if match and not re.search(r"NOT YET WRITTEN|INTERVIEW NOT RUN", match.group(1).upper()):  # setup placeholders
        name = match.group(1)
    name = name or os.path.basename(root)

    opening, closing = "(", ")"
    match = BIND_TEMPLATE.search(read(os.path.join(root, "AGENTS.md")))
    if match:
        opening, closing = match.group(1), match.group(2)
    return f"{opening}{signature}{closing} {name}" if signature else name


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(event, dict) or event.get("session_title"):
        return
    root = project_root(event.get("cwd") or os.getcwd())
    if root is None:
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "sessionTitle": build_title(root)}}))


if __name__ == "__main__":
    main()
