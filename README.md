# familiar-hooks

Optional hooks for a [familiar](https://github.com/familiar-md/familiar) project or
[familiar-hub](https://github.com/familiar-md/familiar-hub), chosen one at a time. Nothing is on by default.

- **Session titles.** Claude Code names each session after its project, `(<signature>) <project name>`,
  so the session list on your phone or the web shows which project is which.
- **Guards.** familiar keeps the assistant to the project by instruction. The guards check each file and
  shell tool call before it runs, and deny a write outside the project, into `1-Inputs/` or into
  `.familiar/`, a read outside the project, or a delete.
- **Checks.** After a file is written, they flag a truncated Office file, a misnamed draft or a missing
  citation field, so the assistant can fix it in the same turn.

The guards are a deterrent, not a security boundary: they read the tool call's text, so a script run
through an interpreter can get past them. Every hook starts Python around ordinary activity, which can
trip endpoint protection or script policy on managed work hardware, so check before installing there.
familiar works fully without any of this.

## Start

1. Copy this package's `.familiar/hooks/` folder into your project's `.familiar/` folder.
2. In the project, run `/ili-system-settings` → Hooks (Claude Code), or by hand:
   `python .familiar/hooks/install_hooks.py list`, then `preview <id>`, then `apply <id> --yes`.
3. Restart the session.

## Read next

- [`INSTALL-HOOKS.md`](INSTALL-HOOKS.md): installing per host, verifying, removing.
- [`MANUAL-HOOKS.md`](MANUAL-HOOKS.md): what each hook decides, what a denial looks like, the limits.

Claude Code is the host the hooks have been seen working on. Codex is supported by the installer but
not live-tested; Gemini CLI needs the hooks added by hand.

Apache 2.0, like familiar core. See [`LICENSE`](LICENSE).
