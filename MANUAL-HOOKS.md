# familiar-hooks manual

This manual covers what each hook does, how the guards decide, what you see when one acts, and what
the guards cannot stop. `INSTALL-HOOKS.md` covers installing, choosing and removing hooks.

## What the package is

familiar has rules: stay inside the project, never delete, never edit a source, never edit
familiar's own files. Without hooks, these rules are instructions that the agent follows. This
package adds an optional mechanical check. It is a set of small scripts that the agent runs around a
tool call:

- A **guard** runs before the call and can deny it.
- A **check** runs after a file is written and tells the agent what is wrong with the file.
- A **title hook** names the session.

The guards catch the common mistakes. They are not a guarantee or a security boundary. An agent that
tries to get around a guard can do so (see [Limits](#limits)).

Every hook starts a Python interpreter around ordinary work. On a work computer that your employer
manages, this can set off endpoint protection or break a script policy. Check the rules before you
install hooks on work equipment. familiar works fully without them.

## The hooks

| Hook | Runs | Decides |
|---|---|---|
| `guard-writes` | before Write, Edit, shell | Denies a write outside the project folder, into `1-Inputs/`, or into `.familiar/`. |
| `guard-delete` | before shell | Denies any shell delete unless every target is in the agent's scratch folder. |
| `guard-reads` | before Read, Grep, Glob, shell | Denies a read outside the project folder. |
| `guard-boundary` | before Write, Edit, shell | For people who develop familiar: no project marker inside familiar's own source folder, and no maintainer audit tool run from a project. |
| `check-office` | after Write, Edit | Flags a `.docx`, `.pptx` or `.xlsx` that is not a complete file (a cut-off write). |
| `check-naming` | after Write, Edit | Flags a deliverable in `2-Drafts/` whose name does not match `YYYY-MM-DD_<label>_<STATUS>_vN[_AI].ext`. |
| `check-citation` | after Write, Edit | Flags a source page in `3-Knowledge/` whose `ref_carry_through` field is missing or in the wrong form. |
| `session-title` | session start | Names a Claude Code session `(<signature>) <project name>`. |
| `session-title-hub` | session start | Names a hub session `familiar hub` or `familiar hub: <category>`. |

Install any set of hooks. Most people install the four guards together (`--group guards`).

## How the guards decide

**Only inside a familiar project.** Every guard except `guard-boundary` first looks for the
`.familiar-project` marker in the project folder. If there is no marker, the guard allows everything.
A hook left behind in an unrelated folder therefore does nothing.

**The project folder is the boundary.** For each read or write, the guard resolves the target path,
relative paths included. It allows the target if it is under the project folder. Outside the project
folder, it allows only:

- the agent's scratch folder (`AppData\Local\Temp\` on Windows, `/tmp/` elsewhere)
- the files in your home folder that familiar's own skills declare: `~/.familiar/user-preferences.md`
  and `~/.familiar/brief-profiles/<id>.md` (global profiles from `/ili-deliverable-brief`, one level
  deep, `.md` only)

It denies every other file under `~/.familiar/`, the same as any other path outside the project.

**Inside the project, two places are read-only.** `1-Inputs/` holds sources. A changed source
becomes a new dated copy in another folder. `.familiar/` holds familiar's own rules, routes and
skills. Feedback on how familiar behaves goes in `5-System/user-preferences.md` instead.

**Shell commands are read for their targets.** For a shell call, the guards look for these common
commands:

- writes: `cp`, `mv`, `copy`, `Copy-Item`, `Move-Item`, `Set-Content`, `Out-File`, `tee` and `>`
  redirection
- reads: `cat`, `type`, `head`, `tail`, `Get-Content`
- deletes: `rm`, `del`, `Remove-Item`, `find -delete` and `git clean`

The guards unwrap a `cmd /c` or `powershell -Command` wrapper first. They follow a `cd` earlier in the
same command. If a path still holds an unresolved `$variable`, the guard denies it. It does not
guess.

**Deletes are allowed only by list.** `guard-delete` allows a delete only when it can show that every
target is in the scratch folder. It denies anything it cannot read with confidence. It always denies
`git clean`. To retire a file, the agent says so and lets you remove it.

## What you see

When a guard denies a call, the call does not run. The agent gets the reason, which starts with the
rule that the guard protects. For example:

```text
CORE-WORKSPACE-SILO: write only inside the project folder. Target is outside it: C:\Users\you\Desktop\out.txt
CORE-NO-DELETE: never delete files. Blocked command: rm 2-Drafts/old.md
CORE-COPY-ON-EDIT: source input is read-only - never write into '1-Inputs/'.
familiar: read only within the project folder. Target is outside it: D:\other\notes.txt
```

The agent is expected to report the denial and ask you what to do. It is not expected to try another
way to get the same result.

A check cannot undo a write, because the file already exists. It gives the agent a note such as
"this name breaks the drafts convention", so that the agent can fix the file in the same turn.

A session title shows only in the session list: `claude --resume`, or Remote Control on a phone or
the web.

## Overrides

These settings are for people who develop familiar or an extension, not for project work:

| Setting | Effect |
|---|---|
| `FAMILIAR_MAINTAINER=1` in the environment | All project guards allow everything. |
| A `.familiar-maintainer` file that contains its own folder's path | The same, for that folder only. Because of the path check, a copied file does not work in another folder. |
| `FAMILIAR_ALLOW_SCAFFOLD=1` | `guard-boundary` allows a project marker inside the source folder. |

If a guard blocks something that a project really needs, do not use an override. The fix belongs in
familiar: a skill that declares the file, and a guard allowance to match.

## Hosts

| Agent | Guards and checks | Titles |
|---|---|---|
| Claude Code | The installer writes them into `.claude/settings.local.json`. Tested. | Yes |
| Codex CLI | The installer writes them into `.codex/hooks.json`. Hooks see shell commands only, so Codex's own file tools can pass without a check. | No |
| Gemini CLI | You add them by hand (see `INSTALL-HOOKS.md`). | No |

Hooks belong to the agent program, not to the model. They run on any model that the program runs. An
agent program that is not in this table can have no hooks at all. `.familiar/installed.json` keeps
`mechanical-enforcement` at `available`. Nothing in familiar depends on a guard being present.

## Limits

- **Scripts get past the guards.** The guards read the command text. A script can read or write a
  file (`python make.py`, `python -c "..."`, `[IO.File]::WriteAllText(...)`). The command text then
  shows no command that the guards recognize, so the call passes. More patterns cannot close this gap.
- **Uncommon commands pass.** The guards do not inspect shell commands outside the lists above.
  Deletes are the exception, because a delete must be on the allow list.
- **Checks look at structure only.** `check-citation` confirms that the field is present and in the
  right form, not that its count is true. `check-office` confirms that the file is a complete
  archive, not that its content is right.
- **One project at a time.** The guards know one project folder per session: the folder that the
  agent opened in.

## Troubleshooting

**Every tool call fails with a hook error that names `python3` or `py`.** The interpreter that the
installer recorded is gone or not on this computer. Run
`python .familiar/hooks/install_hooks.py apply <ids> --yes` again on this computer. It finds a working
Python 3.10 or newer and writes the entries again.

**A guard blocks something that familiar itself asked to do.** Note the reason text and the path.
Either a skill uses a file that it never declared, or the guard is behind a skill. Both are familiar
bugs, so please report them. Until there is a fix, `remove` the one guard involved.

**Nothing is ever blocked.** Check these three things:

1. `.familiar-project` exists in the folder that the agent opened in.
2. You started a new session after you turned the hooks on.
3. `FAMILIAR_MAINTAINER` is not set.

Then ask the agent to write a file to your Desktop. The guard denies it if it works.
