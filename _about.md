# familiar-hooks

Optional hooks for familiar, chosen one at a time. Two kinds today:

- **Session titles.** A Claude Code `SessionStart` hook titles each session after its project, so
  Remote Control on a phone or the web lists `(o-o) My Project` instead of a generic machine-and-word
  name. A second one does the same for a fleet hub.
- **Guards and checks.** Everything familiar tells an agent (`CORE-WORKSPACE-SILO`, `CORE-NO-DELETE`,
  `CORE-COPY-ON-EDIT`, `CORE-INSTRUCTIONS-READONLY`) is a model instruction, followed by judgment. The
  guards inspect a tool call before it runs and deny the ones that would break those rules outright; three
  advisory checks flag a corrupted or misnamed deliverable after the fact.

**Status:** the session-title hook is confirmed on Claude Code, and the write, read and delete guards
and the naming check were seen working in a live Claude Code session on 2026-10-27. Nothing is
live-tested on Codex or Gemini, so `.familiar/installed.json`'s `mechanical-enforcement` capability
stays `available`. INSTALL-HOOKS.md says what is confirmed host by host; MANUAL-HOOKS.md explains
how each hook decides and where it stops.

**A deterrent, not a security boundary.** Hooks launch a Python interpreter around ordinary tool
activity, which can trigger corporate EDR or local script-execution policy on managed hardware; say so
to anyone installing this on work equipment. familiar core is fully functional without it.

## Installing this into a project

A drop-in package, not an installer, and not a uniform copy across hosts: each host loads hooks
differently, so a small tool merges the hooks you choose into the right file. Read INSTALL-HOOKS.md; the
short version:

1. Copy `.familiar/hooks/` into the project's (or hub's) `.familiar/` folder. Do not copy `_about.md`,
   `VERSION`, `INSTALL-HOOKS.md` or `MANUAL-HOOKS.md`.
2. Choose hooks: `/system-settings` -> **Hooks** in a project, or by hand,
   `python .familiar/hooks/install_hooks.py list` then `apply <id> --yes` (`preview` first).
3. Restart the session.

## What is in `.familiar/hooks/`

- `catalog.json` - the hooks, their events, matchers and live-test status. The tool reads it.
- `install_hooks.py` - list, preview, apply and remove, host by host.
- `session_title.py`, `session_title_hub.py` - the two title hooks.
- `guards.py` - one runtime for the seven guards and checks: `writes`, `delete`, `reads`, `boundary`
  (deny) and `office`, `naming`, `citation` (advisory). Each is self-limiting: without a
  `.familiar-project` marker the project-scoped guards do nothing (`boundary`'s maintainer-checkout rule is
  the deliberate exception, since it has to fire where the marker is absent).

## History

Shipped as `familiar-guards` until 2026-10-27, when the session-title hooks and a choose-what-to-install
tool joined it and it was renamed. Before that: recovered 2026-09-03 from a commit that had deleted the
only tracked copies of `guards.py` and `hooks.json` (`_dev/guards/README.md` in the familiar-dev repo
carries that record), ported to Design A's folder-first model 2026-09-07, and moved into this standalone
drop-in shape the same day. Not yet split into its own git repository: guard parity is hard to maintain
solo, and scripts on disk carry IT-scanning risk on managed hardware, both arguments for eventually
splitting this out.
