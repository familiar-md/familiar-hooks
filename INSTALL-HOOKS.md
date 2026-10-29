# Installing familiar-hooks

Optional hooks for a familiar project or fleet hub. Read this first on managed work hardware: a hook
launches a Python interpreter around ordinary activity, which can trigger corporate EDR or local
script-execution policy, and the enforcement guards are a common-case deterrent, not a security
boundary. familiar core is fully functional without any of this.

## What you can choose

Nine hooks, installed one at a time. Nothing is on by default.

| Hook | Applies to | What it does |
|---|---|---|
| `session-title` | project | Titles each Claude Code session `(<signature>) <project name>` so Remote Control lists it by project, not a generic machine-and-word name. |
| `session-title-hub` | hub | Titles a hub session `familiar hub`, or `familiar hub: <category>` for a scoped hub. |
| `guard-writes`, `guard-delete`, `guard-reads`, `guard-boundary` | project | Deny a tool call that would break `CORE-WORKSPACE-SILO`, `CORE-NO-DELETE`, `CORE-COPY-ON-EDIT` or `CORE-INSTRUCTIONS-READONLY` before it runs. |
| `check-office`, `check-naming`, `check-citation` | project | Advisory only: flag a truncated Office file, a misnamed draft, or a malformed citation field after the fact. |

Outside the project, the reads and writes guards let through only the files familiar's own skills
declare in your home folder: `~/.familiar/user-preferences.md` and `~/.familiar/brief-profiles/<id>.md` (for
`/deliverable-brief`). Anything else under `~/.familiar/` is denied like any other outside path.

`.familiar/hooks/catalog.json` is the full list with each hook's events and matchers.
`MANUAL-HOOKS.md` explains how each hook decides, what you see when one fires, and where they stop.

Hooks are installed per project (and once in a hub, for its session title). Repeat the steps below in
each project that should have them.

## Install

1. **Copy the package in.** Download `familiar-hooks-<version>.zip` from the
   [Releases page](https://github.com/familiar-md/familiar-hooks/releases), unzip it, and copy the
   `.familiar` folder inside it onto the project (or hub) folder. That adds `.familiar/hooks/` and
   changes nothing else.
2. **Choose and apply.** Either let your assistant do it, or run the tool yourself; they are the same tool.
   - **Assistant-led, in a project:** run `/system-settings` and choose **Hooks**. It lists the hooks,
     asks which you want, shows exactly what will change, and applies only after your yes. In a hub,
     ask your assistant to follow this file with `session-title-hub`.
   - **By hand**, from the project or hub folder (`python3` or `py -3` where `python` is not found):

     ```text
     python .familiar/hooks/install_hooks.py list
     python .familiar/hooks/install_hooks.py preview session-title
     python .familiar/hooks/install_hooks.py apply session-title --yes
     ```

     `preview` and `list` change nothing. `apply` and `remove` do nothing without `--yes`. You can pass
     several ids, `--group guards`, or `--all`. `show <id>` prints the JSON for pasting in yourself.
3. **Restart the session.** Hooks load once, at startup.

The tool merges into the host's hook file and touches only the entries it recognises. It copies the
existing file to `<file>.pre-familiar-hooks-<time>.bak` first, and rewrites it indented by two spaces. It
writes the interpreter (`python3`, `python` or `py -3`) that really runs Python 3.10+ on this machine, found
when you apply: a hook whose interpreter cannot launch is not a quiet degradation, Claude Code errors
on it every time. If you move the project to another machine, apply again there.

## Why it is not one copy-in step

Hook configuration is not uniform across hosts:

| Host | Where hooks live | What the tool does |
|---|---|---|
| Claude Code | Inline `"hooks"` key in `.claude/settings.json`, `.claude/settings.local.json` or `~/.claude/settings.json`. No standalone `hooks.json` is auto-loaded outside a plugin. | Merges into `.claude/settings.local.json` (per-machine, adds to the project's own settings.json). Default host. |
| Codex CLI | Auto-loads a standalone `<repo>/.codex/hooks.json`. The hooks match shell commands only, so they may not catch Codex's own file tools. Guards only. | `--host codex` merges into `.codex/hooks.json`. |
| Gemini CLI | Inline `"hooks"` key in Gemini's own settings (`~/.config/gemini-cli/settings.json`). | Nothing written. Add a `"hooks"` block by hand, one `BeforeTool` entry per guard with `--host gemini` on each; `guards.py` reads the project `cwd` from Gemini's payload itself. |

Session-title hooks are Claude Code only: `sessionTitle` is a Claude Code `SessionStart` output.

## Verify it fires

Per hook, before trusting it. For `session-title`: start a new session in the project; `claude --resume`
(or the Remote Control list on your phone) shows `(<signature>) <project name>`. For a guard: try a write
outside the project and confirm it is denied with a `CORE-WORKSPACE-SILO` reason, not silently allowed.

## Removing it again

```text
python .familiar/hooks/install_hooks.py remove <id...> --yes
```

removes just those entries and leaves the rest of the hook file alone. To remove the package, delete
`.familiar/hooks/` after removing the hooks it installed, and any `.bak` files you no longer want.
