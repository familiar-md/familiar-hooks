#!/usr/bin/env python3
"""install_hooks.py - choose which familiar hooks to install into this folder's host settings.

    python .familiar/hooks/install_hooks.py list    [--host claude|codex]
    python .familiar/hooks/install_hooks.py show    <id>   [--host ...]   # the JSON, for pasting by hand
    python .familiar/hooks/install_hooks.py preview <id...> | --group <g> | --all   [--host ...]
    python .familiar/hooks/install_hooks.py apply   <id...> | --group <g> | --all   [--host ...] --yes
    python .familiar/hooks/install_hooks.py remove  <id...> | --group <g> | --all   [--host ...] --yes

Run from the project (or hub) folder the package was copied into. `list` and `preview` change nothing;
`apply` and `remove` need `--yes`, so show the preview and get a yes first. The hooks come from
`catalog.json` beside this file. Each host's hook file is edited by merging into it: only entries this
tool recognises are added or removed, everything else in the file is kept (the file is rewritten
indented by two spaces, and the original is copied to `<file>.pre-familiar-hooks-<time>.bak` first).

Hosts: `claude` writes `.claude/settings.local.json` (per-machine, additive to settings.json);
`codex` writes `.codex/hooks.json`. Gemini CLI has no project-level hook file confirmed, so nothing is
written for it; see INSTALL-HOOKS.md
(https://github.com/familiar-md/familiar-hooks/blob/main/INSTALL-HOOKS.md).

The interpreter written into each hook is the first of `python3`, `python`, `py -3` that actually runs
Python 3.10+ here, found when you apply, not guessed. Standard library only.
"""

# familiar's floor is Python 3.10. On anything older, stop with a plain message instead of a traceback.
import sys
if sys.version_info < (3, 10):
    sys.exit("familiar needs Python 3.10 or newer, but this is Python %d.%d (%s). Install Python 3.10+ "
             "(.familiar/scripts/doctor.py says how), then run this again with it." % (*sys.version_info[:2], sys.executable))

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
HOOK_FILES = {"claude": Path(".claude") / "settings.local.json", "codex": Path(".codex") / "hooks.json"}
HOOKS_DIR = ".familiar/hooks/"


def die(message):
    sys.exit("ERROR: " + message)


def load_catalog():
    try:
        return json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))["hooks"]
    except (OSError, ValueError, KeyError) as exc:
        die(f"cannot read catalog.json beside this script ({exc})")


def context():
    if (ROOT / ".familiar-project").is_file():
        return "project"
    if (ROOT / "hub-settings.md").is_file():
        return "hub"
    die(f"{ROOT} is neither a familiar project (no .familiar-project) nor a fleet hub (no hub-settings.md). "
        "Copy this package into one, then run this from there.")


def interpreter():
    """(command, leading args) of the first interpreter that really runs Python 3.10+."""
    probe = "import sys; print(sys.version_info >= (3, 10))"
    for name, lead in (("python3", []), ("python", []), ("py", ["-3"])):
        if not shutil.which(name):
            continue
        try:
            run = subprocess.run([name, *lead, "-c", probe], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if run.returncode == 0 and run.stdout.strip() == "True":
            return name, lead
    return sys.executable, []


def render(host, entry, interp):
    name, lead = interp
    if host == "claude":
        script = "${CLAUDE_PROJECT_DIR}/" + HOOKS_DIR + entry["script"]
        return {"type": "command", "command": name, "args": [*lead, script, *entry["args"]]}
    command = " ".join([name, *lead, HOOKS_DIR + entry["script"], *entry["args"]])
    return {"type": "command", "command": command}


def handler_text(handler):
    return " ".join([handler.get("command", ""), *map(str, handler.get("args", []))])


def matches(handler, entry):
    text = handler_text(handler).replace("\\", "/")
    return HOOKS_DIR + entry["script"] in text and " ".join(entry["args"]) in text


def read_settings(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        die(f"{path} is not valid JSON ({exc}); fix it first, nothing was changed.")
    if not isinstance(data, dict):
        die(f"{path} is not a JSON object; nothing was changed.")
    return data


def is_installed(settings, entry):
    for block in settings.get("hooks", {}).get(entry["event"], []):
        if any(matches(h, entry) for h in block.get("hooks", [])):
            return True
    return False


def add(settings, entry, handler):
    blocks = settings.setdefault("hooks", {}).setdefault(entry["event"], [])
    for block in blocks:
        if block.get("matcher") == entry["matcher"]:
            block.setdefault("hooks", []).append(handler)
            return
    blocks.append({"matcher": entry["matcher"], "hooks": [handler]})


def remove(settings, entry):
    if "hooks" not in settings:
        return
    event = settings["hooks"].get(entry["event"], [])
    for block in event:
        block["hooks"] = [h for h in block.get("hooks", []) if not matches(h, entry)]
    settings["hooks"][entry["event"]] = [b for b in event if b.get("hooks")]
    if not settings["hooks"][entry["event"]]:
        del settings["hooks"][entry["event"]]
    if not settings["hooks"]:
        del settings["hooks"]


def select(catalog, args, ctx):
    here = [h for h in catalog if h["applies_to"] == ctx]
    if args.all:
        return here
    wanted = set(args.ids)
    picked = [h for h in here if h["id"] in wanted or (args.group and h["group"] == args.group)]
    unknown = wanted - {h["id"] for h in catalog}
    if unknown:
        die("no such hook: " + ", ".join(sorted(unknown)))
    outside = wanted - {h["id"] for h in here}
    if outside:
        die(f"{', '.join(sorted(outside))} applies to a {'hub' if ctx == 'project' else 'project'}, not this {ctx}.")
    if not picked:
        die("name at least one hook id, --group <group> or --all (see: list).")
    return picked


def plan(catalog, args, ctx, writing):
    host = args.host
    if host == "gemini":
        die("Gemini CLI has no project-level hook file confirmed, so nothing can be written for it. "
            "See INSTALL-HOOKS.md for the by-hand route: https://github.com/familiar-md/familiar-hooks/blob/main/INSTALL-HOOKS.md")
    path = ROOT / HOOK_FILES[host]
    settings = read_settings(path)
    picked = select(catalog, args, ctx)
    interp = interpreter() if writing else ("<python>", [])
    changes = []
    for hook in picked:
        for entry in hook["hosts"].get(host, []):
            changes.append((hook, {**entry, "event": entry["event"]}, is_installed(settings, entry)))
        if host not in hook["hosts"]:
            print(f"  skip {hook['id']}: not available for {host}")
    return path, settings, interp, changes


def cmd_list(catalog, args, ctx):
    path = ROOT / HOOK_FILES[args.host]
    settings = read_settings(path)
    print(f"{ctx} at {ROOT}\nhost {args.host}: {path.relative_to(ROOT)}\n")
    for hook in catalog:
        if hook["applies_to"] != ctx:
            continue
        entries = hook["hosts"].get(args.host)
        if not entries:
            state = "not available for " + args.host
        else:
            done = [is_installed(settings, e) for e in entries]
            state = "installed" if all(done) else "partly installed" if any(done) else "not installed"
        print(f"{hook['id']:<18} [{hook['group']}] {state}\n    {hook['title']}: {hook['summary']}\n    status: {hook['status']}")


def cmd_show(catalog, args, ctx):
    hook = next((h for h in catalog if h["id"] == args.ids[0]), None) if args.ids else None
    if not hook:
        die("show needs one hook id (see: list).")
    interp = interpreter()
    out = {}
    for entry in hook["hosts"].get(args.host, []):
        add(out, entry, render(args.host, entry, interp))
    if not out:
        die(f"{hook['id']} is not available for {args.host}.")
    print(json.dumps(out, indent=2))


def cmd_change(catalog, args, ctx, removing):
    writing = args.yes
    path, settings, interp, changes = plan(catalog, args, ctx, writing)
    rel = path.relative_to(ROOT)
    todo = [(h, e) for h, e, present in changes if present == removing]
    for hook, entry in todo:
        verb = "remove" if removing else "add"
        print(f"  {verb} {hook['id']}: {entry['event']} / {entry['matcher']} -> {entry['script']} {' '.join(entry['args'])}".rstrip())
    for hook, entry, present in changes:
        if present != removing:
            print(f"  skip {hook['id']}: already {'absent' if removing else 'installed'}")
    if not todo:
        print("nothing to change.")
        return
    if any("untested" in h["status"] for h, _ in todo):
        print("note: at least one of these has not been confirmed against a live host session.")
    if not args.yes:
        print(f"\npreview only; nothing written. File: {rel}" + ("" if removing else f". Interpreter: resolved on apply."))
        return
    if path.exists():
        backup = path.with_name(f"{path.name}.pre-familiar-hooks-{time.strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(path, backup)
        print(f"backed up {rel} to {backup.name}")
    for hook, entry in todo:
        if removing:
            remove(settings, entry)
        else:
            add(settings, entry, render(args.host, entry, interp))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    print(f"wrote {rel}. Restart the session for the change to take effect.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["list", "show", "preview", "apply", "remove"])
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--group")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--host", default="claude", choices=["claude", "codex", "gemini"])
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.command in ("preview", "list", "show") and args.yes:
        die(f"{args.command} changes nothing; --yes belongs to apply and remove.")
    if args.command in ("apply", "remove") and not args.yes:
        args.command = "preview-" + args.command
    catalog, ctx = load_catalog(), context()
    if args.command == "list":
        cmd_list(catalog, args, ctx)
    elif args.command == "show":
        cmd_show(catalog, args, ctx)
    else:
        cmd_change(catalog, args, ctx, removing=args.command.endswith("remove"))


if __name__ == "__main__":
    main()
