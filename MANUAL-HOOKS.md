# familiar-hooks manual

What each hook does, how the guards decide, what you see when one fires, and where they stop. For
installing, choosing hooks and removing them, see `INSTALL-HOOKS.md`.

## What the package is

familiar's rules (stay inside the project, never delete, never edit a source, never edit familiar's
own files) are instructions the assistant follows by judgment. This package adds an optional second
line: small scripts the coding host runs around a tool call. A guard runs before the call and can
deny it. A check runs after a file is written and tells the assistant what is wrong with it. A
title hook names the session.

It is a deterrent against the common mistake, not a security boundary. An assistant that sets out
to get around a guard can (see Limits). Every hook launches a Python interpreter around ordinary
activity, which can trigger corporate endpoint protection or script-execution policy on managed
hardware. Check before installing on work equipment. familiar works fully without any of it.

## The hooks

| Hook | Runs | Decides |
|---|---|---|
| `guard-writes` | before Write, Edit, shell | Denies a write outside the project folder, into `1-Inputs/`, or into `.familiar/`. |
| `guard-delete` | before shell | Denies any shell delete unless every target is in the host's scratch folder. |
| `guard-reads` | before Read, Grep, Glob, shell | Denies a read outside the project folder. |
| `guard-boundary` | before Write, Edit, shell | Maintainer safety: no project marker inside familiar's own source checkout, no maintainer audit tool run from a project. |
| `check-office` | after Write, Edit | Flags a `.docx`, `.pptx` or `.xlsx` that is not a complete file (a truncated write). |
| `check-naming` | after Write, Edit | Flags a deliverable in `2-Drafts/` whose name breaks `YYYY-MM-DD_<label>_<STATUS>_vN[_AI].ext`. |
| `check-citation` | after Write, Edit | Flags a source page in `3-Knowledge/` with a missing or malformed `ref_carry_through` field. |
| `session-title` | session start | Titles a Claude Code session `(<signature>) <project name>`. |
| `session-title-hub` | session start | Titles a hub session `familiar hub` or `familiar hub: <category>`. |

Install any subset. The four guards are usually taken together (`--group guards`).

## How the guards decide

**Only inside a familiar project.** Every guard except `guard-boundary` first looks for the
`.familiar-project` marker in the project folder. Without it the guard allows everything, so a hook
left behind in an unrelated folder does nothing.

**The project folder is the boundary.** Reads and writes resolve the target path, relative paths
included, and allow it when it sits under the project folder. Outside it, three things are allowed:

- the host's scratch folder (`AppData\Local\Temp\` on Windows, `/tmp/` elsewhere);
- the home-folder files familiar's own skills declare: `~/.familiar/user-preferences.md`,
  `~/.familiar/fleet.md` (the hub's registry, used by `/system-settings` → Fleet) and
  `~/.familiar/brief-profiles/<id>.md` (global profiles from `/deliverable-brief`, one level deep,
  `.md` only);
- nothing else. Any other file under `~/.familiar/` is denied like any outside path.

**Inside the project, two places are read-only.** `1-Inputs/` holds sources; a changed source
becomes a new dated copy elsewhere. `.familiar/` holds familiar's own protocol, routes and skills;
behaviour feedback goes in `5-System/user-preferences.md` instead.

**Shell commands are read for their targets.** For a shell call, the guards look for the common
verbs: `cp`, `mv`, `copy`, `Copy-Item`, `Move-Item`, `Set-Content`, `Out-File`, `tee` and `>`
redirection for writes; `cat`, `type`, `head`, `tail`, `Get-Content` for reads; `rm`, `del`,
`Remove-Item`, `find -delete` and `git clean` for deletes. A `cmd /c` or `powershell -Command`
wrapper is unwrapped first, and `cd` earlier in the same command is followed. A path that still
holds an unresolved `$variable` is denied rather than guessed at.

**Deletes are allow-listed.** `guard-delete` allows a delete only when it can show every target is
in scratch. Anything it cannot parse with confidence is denied. `git clean` is always denied. To
retire a file, say so and let the user remove it.

## What you see

When a guard denies a call, the call does not run and the assistant gets the reason, which starts
with the rule it protects. For example:

```text
CORE-WORKSPACE-SILO: write only inside the project folder. Target is outside it: C:\Users\you\Desktop\out.txt
CORE-NO-DELETE: never delete files. Blocked command: rm 2-Drafts/old.md
CORE-COPY-ON-EDIT: source input is read-only - never write into '1-Inputs/'.
familiar: read only within the project folder. Target is outside it: D:\other\notes.txt
```

A well-behaved assistant reports the denial and asks you how to proceed. It should not try another
route to the same result.

A check cannot undo a write; the file already exists. It hands the assistant a note such as "this
name breaks the drafts convention" so the assistant can fix the file in the same turn.

A title hook shows only in the session list: `claude --resume`, or Remote Control on a phone or the
web.

## Overrides

For the person maintaining familiar itself, not for project work:

| Setting | Effect |
|---|---|
| `FAMILIAR_MAINTAINER=1` in the environment | All project guards allow everything. |
| A `.familiar-maintainer` file whose content is its own folder's path | Same, for that folder. The content check stops a copied marker from working elsewhere. |
| `FAMILIAR_ALLOW_SCAFFOLD=1` | Lets `guard-boundary` allow a project marker inside the source checkout. |

If a guard blocks something a project really needs, the fix belongs in familiar (a skill that
declares the file, and a guard allowance to match), not an override.

## Hosts

| Host | Guards and checks | Titles |
|---|---|---|
| Claude Code | Installed by the tool into `.claude/settings.local.json`. Tested. | Yes. |
| Codex CLI | Installed into `.codex/hooks.json`. Hooks see shell commands only, so Codex's own file tools may pass unchecked. | No. |
| Gemini CLI | Added by hand (see `INSTALL-HOOKS.md`). | No. |

Hooks belong to the agent harness, not the model: they fire on any model the harness runs, and a
harness not listed here may have no hooks at all. `.familiar/installed.json` keeps
`mechanical-enforcement` at `available`. Nothing in familiar
assumes a guard is present.

## Limits

- **Scripts get past them.** The guards read command text. A file written or read by a script
  (`python make.py`, `python -c "..."`, `[IO.File]::WriteAllText(...)`) shows no verb the guards
  recognise, and it passes. This cannot be closed by matching more patterns.
- **Uncommon verbs pass.** Shell commands outside the lists above are not inspected. Deletes are
  the exception: those are allow-listed.
- **Checks are structural.** `check-citation` confirms the field is present and shaped right, not
  that its count is honest. `check-office` confirms the file is a complete archive, not that its
  content is right.
- **One project at a time.** The guards know one project root per session, the folder the host
  was opened in.

## Troubleshooting

**Every tool call fails with a hook error naming `python3` or `py`.** The interpreter written at
install time is gone or not on this machine. Run `python .familiar/hooks/install_hooks.py apply
<ids> --yes` again on this machine; it finds a working Python 3.10+ and rewrites the entries.

**A guard blocks something familiar itself asked to do.** Note the reason text and the path. Either
a skill touches a file it never declared, or the guard has not caught up with a skill. Both are
familiar bugs worth reporting. Meanwhile, `remove` the one guard involved.

**Nothing is ever blocked.** Confirm `.familiar-project` exists in the folder the host was opened
in, that you restarted the session after applying, and that `FAMILIAR_MAINTAINER` is not set. Then
ask the assistant to write a file to your Desktop: it should come back denied.
