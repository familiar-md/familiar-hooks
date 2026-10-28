#!/usr/bin/env python3
"""guards.py - familiar's guard and check hooks, one cross-platform runtime.

Install steps per host: INSTALL-HOOKS.md (https://github.com/familiar-md/familiar-hooks/blob/main/INSTALL-HOOKS.md).

STATUS: WIRED IN. Each host's own hook configuration, written by install_hooks.py (.claude/settings.local.json's inline
"hooks" key, .codex/hooks.json) invokes this file for all seven guards. There is no single
shared hooks.json across hosts -- Claude Code and Gemini CLI only read hook definitions
written inline in a settings file, never a standalone hooks.json; Codex is the one host
that auto-loads a standalone <repo>/.codex/hooks.json.

WHY. The .ps1 guards invoke powershell.exe by name. On macOS and Linux that binary does not
exist under any name (the PowerShell binary there is `pwsh`), so it is a hard ENOENT rather
than a compatibility nuance - every rule bootstrap.md calls non-negotiable silently becomes
advisory. The same break happens on any host that is not Claude Code. Python is already a
hard dependency of this repo (extract_pdf.py, audit.py, build-release.py), so this costs no
new dependency.

SHAPE - three layers, deliberately separated:

    host adapter  ->  normalised event  ->  decision core  ->  host adapter
    (stdin JSON)      Event(tool, paths,    decide_*(), pure    (exit code or
                      command, ...)         apart from the      host JSON)
                                            marker probe

The decision functions are the only thing whose behaviour must be identical everywhere, and
they are what the test table exercises. Filesystem access is confined to Context.load().

USAGE
    python guards.py --guard writes|delete|reads|boundary|office|naming|citation
                      [--host claude|copilot|cursor|codex|gemini]
    ...with the PreToolUse (or, on Gemini CLI, BeforeTool) event JSON on stdin.

    Exit 0 = allow, exit 2 = deny with the reason on stderr (the Claude Code contract, which
    Codex and Gemini CLI's BeforeTool both accept verbatim). Other hosts get their own JSON
    shape on stdout.

PORTING NOTES - read before changing a regex:
  * Resolve-Lexical is reproduced exactly, including its quirk that '..' at depth 1 empties
    the path rather than popping one segment. Behaviour parity beats tidiness here.
  * guard-writes tests the RAW file_path against the scratch pattern, while
    guard-reads tests the RESOLVED path. That asymmetry is in the originals and is preserved.
  * The delete guard is an ALLOW-list: anything it cannot parse with confidence blocks.
    Keep it that way - the safe failure mode denies, it never destroys.

DESIGN A, 2026-09-07 - what left with the fleet/plugin/installer model:
  * There is no plugin cache and no ${CLAUDE_PLUGIN_ROOT}. A drop-in project's skills, agents,
    core protocol, and any extension package all live inside the one project tree the marker
    sits in - CLAUDE_PROJECT_DIR is the only root this file ever needs.
  * There is no fleet registry, no /familiar:update, and no cross-project write. Design A's
    update story (STATUS.md - Update story) is a person hand-replacing release-owned subtrees in
    ONE project; nothing recompiles a second project from this one's session, so the old
    _fleet_managed_write carve-out and its known-skill/known-agent lookups are gone outright, not
    just repathed. If a scripted cross-project updater is ever built (STATUS.md's deferred
    cross-project updater), it needs its own carve-out designed against whatever that tool
    actually does - reviving this one by rewiring its paths would authorize a write shape no
    current mechanism produces.
  * The project root IS the workspace (CORE-WORKSPACE-SILO) - there is no inner
    'agent-workspace' hop to resolve, so Context carries no separate workspace field.
"""
from __future__ import annotations

# familiar's floor is Python 3.10. On anything older, stop with a plain message instead of a traceback.
import sys
if sys.version_info < (3, 10):
    sys.exit("familiar needs Python 3.10 or newer, but this is Python %d.%d (%s). Install Python 3.10+ "
             "(.familiar/scripts/doctor.py says how), then run this again with it." % (*sys.version_info[:2], sys.executable))

import argparse
import json
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass

BOM = chr(0xFEFF)

# --- shared patterns (ported verbatim from the .ps1 guards) ---------------------------------
SCRATCH_ROOT = re.compile(r"(AppData[\\/]Local[\\/]Temp[\\/]|^/tmp/)", re.I)
# familiar's own machine-level files, outside any project, matched by exact name:
# user-preferences.md, the optional cross-project preferences fallback bootstrap.md and checkin
# both name (the familiar signature, a cross-project voice default), and fleet.md, the fleet hub's
# registry, whose own-project row /system-settings -> Fleet reads and writes. Home is host-neutral
# ~/.familiar/ - ~/.claude/ means nothing to Gemini. The legacy ~/.claude/familiar-fleet.md is not
# matched, and every other file under ~/.familiar/ stays blocked. One folder is allowed too:
# brief-profiles/, where /deliverable-brief keeps global profiles as <id>.md, one level deep.
FAMILIAR_HOME_FILES = ("user-preferences.md", "fleet.md")
FAMILIAR_HOME_DIR = "brief-profiles"
FAMILIAR_HOME_FILE = re.compile(
    r"[\\/]\.familiar[\\/](?:user-preferences\.md|fleet\.md|brief-profiles[\\/][^\\/]+\.md)$", re.I)
DELETE_VERB = re.compile(
    r"(^|[;&|(]\s*)(rm|rmdir|unlink|shred|del|erase|rd|ri|remove-item)\b\s", re.I | re.M)
DELETE_FLAG = re.compile(r"(\s-delete\b|\bgit\s+clean\b)", re.I)
GIT_CLEAN = re.compile(r"\bgit\s+clean\b", re.I)
CD_CMD = re.compile(r"^(?:cd|Set-Location|sl)\s+(.+)$", re.I)
RM_CMD = re.compile(r"^(?:rm|rmdir|unlink|shred|del|erase|rd|ri|Remove-Item)\b(.*)$", re.I)
FIND_CMD = re.compile(r"^find\b(.*)$", re.I)
FIND_DELETE = re.compile(r"(?:^|\s)-delete(?:\s|$)")
TOKENS = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")
VAR_ASSIGN = re.compile(
    r"(?:^|[\s;&|])([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|([^\s;&|]+))", re.M)
# PowerShell's assignment shape - $name = "value" - is a different syntax from POSIX's
# NAME=value and was not recognized by VAR_ASSIGN at all, which is how the writes guard was
# defeated live 2026-08-23: "$p = ...Desktop...; Set-Content -Path $p" left $p looking exactly
# as unresolvable as a genuinely dynamic value, and an unresolvable write destination was
# silently ALLOWED (see _shell_write_targets/_shell_read_targets below, before this fix).
PS_VAR_ASSIGN = re.compile(
    r"(?:^|[\s;&|])\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))", re.M)
# $env:NAME is PowerShell's environment-variable syntax. Resolved against THIS process's own
# os.environ, which is a faithful stand-in for what the real command would see - guards.py runs
# on the same machine, as the same user, in the same session as the tool call it is judging.
ENV_VAR_REF = re.compile(r"\$env:([A-Za-z_][A-Za-z0-9_]*)", re.I)
CMD_SPLIT = re.compile(r"(?:&&|\|\||;|\||&|\r?\n)")
# Matched on the concrete script file, not the skill directory - a bare 'skills[\\/]system-audit[\\/]'
# also matches 'git add plugins/.familiar/skills/system-audit/SKILL.md', 'cat .../SKILL.md', or a
# 'git log' over the folder, none of which run the tool. Item 72, found 2026-08-25 committing the
# project-setup rename: staging SKILL.md itself was denied as if it were an invocation.
AUDIT_SCRIPT = re.compile(r"system-audit[\\/]scripts[\\/]audit\.py\b", re.I)
# Requiring an interpreter token in the SAME command segment (not just the script path) is what
# turns "mentions the path" into "actually runs it" - SKILL.md's own invocation always names an
# interpreter ('PYTHONUTF8=1 python "<path>/audit.py" --only ...'). Full word 'python[3]' only -
# a bare 'py' alternative would match the '.py' extension inside 'audit.py' itself, making every
# command that merely names the file (cat, git add, ...) look like an invocation again.
AUDIT_INTERPRETER = re.compile(r"\bpython3?\b", re.I)
# POSIX cp/mv only take '-' flags; Windows copy/xcopy/robocopy/Copy-Item/Move-Item take '/' or
# '-' flags. Splitting the two groups lets the fallback "last non-flag token" heuristic below
# tell a switch from a destination without ever mistaking a leading '/' in a POSIX path for one
# - Windows destinations never start with '/' or '-', so filtering both is safe only there.
POSIX_COPY_VERB = re.compile(r"(^|[;&|(]\s*)(cp|mv)\b(.*)$", re.I)
WIN_COPY_VERB = re.compile(
    r"(^|[;&|(]\s*)(copy|xcopy|robocopy|Copy-Item|Move-Item)\b(.*)$", re.I)
CONTENT_WRITE_VERB = re.compile(
    r"(^|[;&|(]\s*)(Set-Content|Add-Content|Out-File|tee)\b(.*)$", re.I)
REDIRECT_DEST = re.compile(r">>?\s*(\"[^\"]*\"|'[^']*'|\S+)")
DEST_FLAG = re.compile(r"-Destination\s+(\"[^\"]*\"|'[^']*'|\S+)", re.I)
PATH_FLAG = re.compile(r"-(?:Path|FilePath)\s+(\"[^\"]*\"|'[^']*'|\S+)", re.I)
# Common content-read verbs only - NOT every way a shell one-liner can read a file (an
# interpreter one-liner like `python -c "print(open(x).read())"` or PowerShell's
# [IO.File]::ReadAllText(...) is invisible to this and always will be; a regex over shell verbs
# cannot enumerate every scripting language's file API). guard-reads.ps1 originally rejected any
# Bash coverage for exactly this "inherently leaky" reason - reinstated 2026-08-21 anyway after a
# live Gemini CLI run showed a plain `Get-Content` read past the guard entirely, because a partial
# guard against the COMMON case (cat/type/Get-Content) still beats zero coverage against it, the
# same tradeoff decide_writes/decide_delete already accept. The residual gap (deliberate scripting
# one-liners) is real and undocumented nowhere else the way this comment documents it here.
READ_VERB = re.compile(
    r"(^|[;&|(]\s*)(cat|type|more|less|head|tail|Get-Content|gc)\b(.*)$", re.I)

# A wrapper a real command Gemini CLI's run_shell_command issues on Windows, or an equivalent
# PowerShell/pwsh -Command invocation - none of the verb regexes above anchor past it, so an
# unwrapped "cmd.exe /c copy ..." never matches "copy ..." and every shell-based guard (writes,
# delete, reads) sees no recognizable verb at all, which every one of them treats as "cannot
# parse this, allow" (decide_delete is the one exception - see its own comment - but its gate
# check upstream of that logic has the same blind spot). Found live 2026-08-23 probing a
# compiled Gemini project: with GEMINI.md's own rule text removed, an adversarial run copied a
# workspace file to the Desktop via exactly this wrapper, and guards.py let it through.
SHELL_WRAPPER = re.compile(
    r"(^|[;&|(]\s*)(cmd(?:\.exe)?\s+/[ck]\s+|powershell(?:\.exe)?\s+(?:-\w+\s+)*-command\s+|"
    r"pwsh\s+(?:-\w+\s+)*-command\s+)", re.I)


def _unwrap_shell(cmd: str) -> str:
    """Strip a cmd.exe/powershell/pwsh wrapper wherever one starts the command or follows a
    shell separator, so the verb regexes above see 'copy ...', not 'cmd.exe /c copy ...'.
    Looped, not one pass: a chain can wrap more than once (e.g. powershell -Command "cmd /c
    ...")."""
    prev = None
    while prev != cmd:
        prev = cmd
        cmd = SHELL_WRAPPER.sub(r"\1", cmd)
    return cmd


def resolve_lexical(base: str, path: str) -> str:
    """Collapse a path without touching the filesystem - the target may not exist yet.

    Exact port of Resolve-Lexical in guard-delete.ps1 / guard-reads.ps1, quirk included:
    a '..' with only one segment on the stack clears the path instead of popping.
    """
    p = (path or "").replace("\\", "/")
    is_abs = bool(re.match(r"^[A-Za-z]:/", p)) or p.startswith("/")
    if is_abs:
        full = p
    elif base:
        # base must be slash-normalized too, or a Windows-native ctx.project_dir (backslashes)
        # concatenated with a slash-normalized relative fp produces a string under_root() can
        # never match against a freshly-normalized candidate_root - found live 2026-08-21 via
        # Gemini's read_file passing a relative path (Claude Code's Read always passes absolute,
        # so this was dormant). Same shape as the guard-writes bare-relative-path fix.
        base_norm = base.replace("\\", "/")
        full = f"{base_norm}/{p}"
    else:
        full = p
    out: list[str] = []
    for seg in full.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            out = out[:-1] if len(out) > 1 else []
            continue
        out.append(seg)
    if is_abs and full.startswith("/"):
        return "/" + "/".join(out)
    return "/".join(out)


def under_root(resolved: str, candidate_root: str) -> bool:
    if not candidate_root or not candidate_root.strip():
        return False
    cr = resolve_lexical("", candidate_root)
    return resolved.lower() == cr.lower() or resolved.lower().startswith(cr.lower() + "/")


# --- normalised event + context -------------------------------------------------------------
@dataclass
class Event:
    file_path: str = ""
    path: str = ""
    command: str = ""
    has_tool_input: bool = True


@dataclass
class Context:
    """Everything the decision functions need that came from outside the event.

    No workspace field: under CORE-WORKSPACE-SILO the marker's own directory (project_dir) IS the
    workspace, not a folder one level inside it. No plugin_root or fleet_roots: Design A has no
    plugin cache and no fleet registry - see the module docstring's Design A note."""
    project_dir: str = ""
    has_project_marker: bool = False
    is_maintainer: bool = False
    in_repo: bool = False          # path-matched .familiar-maintainer, for guard-boundary M1
    allow_scaffold: bool = False
    maintainer_env: bool = False
    home: str = ""

    @classmethod
    def load(cls, env: dict | None = None) -> "Context":
        env = env if env is not None else os.environ
        root = (env.get("CLAUDE_PROJECT_DIR") or os.getcwd()).rstrip("\\/")
        marker = os.path.join(root, ".familiar-project")
        has_marker = os.path.isfile(marker)

        maint_env = env.get("FAMILIAR_MAINTAINER") == "1"
        in_repo = _path_matched_maintainer(root)

        return cls(
            project_dir=root,
            has_project_marker=has_marker,
            is_maintainer=maint_env or in_repo,
            in_repo=in_repo,
            allow_scaffold=env.get("FAMILIAR_ALLOW_SCAFFOLD") == "1",
            maintainer_env=maint_env,
            home=env.get("USERPROFILE") or env.get("HOME") or "",
        )


def _path_matched_maintainer(root: str) -> bool:
    """'.familiar-maintainer' counts only when its content equals the folder's own path, so a
    copied or cloned checkout does not inherit maintainer status by accident."""
    marker = os.path.join(root, ".familiar-maintainer")
    if not os.path.isfile(marker):
        return False
    try:
        with open(marker, encoding="utf-8", errors="replace") as fh:
            declared = fh.read().lstrip(BOM).strip().rstrip("\\/")
    except OSError:
        return False
    return bool(declared) and declared.lower() == root.lower()


Decision = tuple[bool, str]
ALLOW: Decision = (True, "")


# --- guard: writes ---------------------------------------------------------------------------
def _write_target(rest: str, strip_slash_flags: bool) -> str | None:
    """Best-guess destination token from the tail of a copy/move/content-write command
    segment. -Destination wins over -Path/-FilePath (Copy-Item takes both, source in -Path,
    destination in -Destination); otherwise the last non-flag token, which is the destination
    position for cp/mv/copy/xcopy/robocopy/tee alike."""
    m = DEST_FLAG.search(rest)
    if m:
        return m.group(1).strip("\"'")
    m = PATH_FLAG.search(rest)
    if m:
        return m.group(1).strip("\"'")
    toks = [t.strip("\"'") for t in TOKENS.findall(rest)
            if not (t.startswith("-") or (strip_slash_flags and t.startswith("/")))]
    return toks[-1] if toks else None


def _shell_write_targets(cmd: str, project_dir: str) -> list[str]:
    """Destinations a shell command would write to, resolved against a tracked cwd - the same
    class of gap decide_delete already closes for rm-family verbs, now for copy/move/redirect
    verbs. Best-effort: a verb or shape this cannot recognize yields no target, which means
    ALLOW by default. A recognized verb whose destination still contains an unresolved '$' after
    _expand_vars (POSIX and PowerShell assignments, $env:NAME) is NOT dropped silently - it is
    passed through as-is, and _decide_write_target denies on the leftover '$' rather than
    guessing. Found live 2026-08-23: silently dropping an unresolved destination is how
    `$p = "$env:USERPROFILE\\Desktop\\x"; Set-Content -Path $p` defeated this guard entirely -
    the destination was never even wrong, it was just never checked.

    Substitutes into each extracted TOKEN (the cd target, the destination), never into the whole
    command string before re-splitting it - a resolved value containing a space (ordinary for a
    real path) would otherwise corrupt the very re-tokenizing this function does next. Found
    live 2026-08-23 writing this fix's own parity test case, one edit after the fix it tests."""
    cmd = _unwrap_shell(cmd)
    variables = _collect_vars(cmd)
    cwd = project_dir
    targets: list[str] = []
    for part in CMD_SPLIT.split(cmd):
        t = part.strip()
        m = CD_CMD.match(t)
        if m:
            cwd = resolve_lexical(cwd, _substitute(m.group(1).strip().strip("\"'"), variables))
            continue
        dest = None
        m = POSIX_COPY_VERB.match(t)
        if m:
            dest = _write_target(m.group(3), strip_slash_flags=False)
        else:
            m = WIN_COPY_VERB.match(t) or CONTENT_WRITE_VERB.match(t)
            if m:
                dest = _write_target(m.group(3), strip_slash_flags=True)
        if dest is None:
            m = REDIRECT_DEST.search(t)
            if m:
                dest = m.group(1).strip("\"'")
        if not dest:
            continue
        dest = _substitute(dest, variables)
        targets.append(dest if "$" in dest else resolve_lexical(cwd, dest))
    return targets


def decide_writes(ev: Event, ctx: Context) -> Decision:
    if not ctx.has_project_marker or ctx.is_maintainer:
        return ALLOW
    fp = ev.file_path
    if not fp or not fp.strip():
        if not ev.command or not ev.command.strip():
            return ALLOW
        for target in _shell_write_targets(ev.command, ctx.project_dir):
            decision = _decide_write_target(target, ctx)
            if not decision[0]:
                return decision
        return ALLOW
    return _decide_write_target(fp, ctx)


def _decide_write_target(fp: str, ctx: Context) -> Decision:
    if "$" in fp:
        # Still unresolved after _expand_vars - a genuinely dynamic destination (computed,
        # piped in, or referencing something this guard cannot see). Deny rather than guess:
        # the same posture decide_delete already takes on an unresolved token, now matched here.
        return (False,
                f"CORE-WORKSPACE-SILO: could not verify this write's destination - it still contains "
                f"an unresolved '$' reference after variable expansion: {fp}\nRefusing rather than "
                "assuming it resolves inside the workspace. (Maintainer override: "
                "FAMILIAR_MAINTAINER=1 or the .familiar-maintainer marker.)")
    # Anchored to the ACTUAL project root, not to wherever a literal folder-name segment happens
    # to appear in the path. Found live 2026-08-24, building this fix's own negative-control
    # tests: an unanchored regex - (?:^|[\\/])name[\\/] - matches that name anywhere in an
    # absolute string, so a completely unrelated tree containing a same-named folder was
    # wrongly ALLOWED. resolve_lexical(ctx.project_dir, fp) turns both Claude Code's
    # always-absolute file_path and Gemini's occasional bare-relative one ("notes.md" from cwd)
    # into the same normalised absolute form, so a single under_root() check - the same primitive
    # decide_reads() already uses correctly - covers both shapes without matching a same-named
    # folder anywhere else on disk. Under Design A the project root IS the workspace
    # (CORE-WORKSPACE-SILO) - there is no separate ctx.workspace to resolve against first.
    resolved = resolve_lexical(ctx.project_dir, fp)
    familiar_root = resolve_lexical(ctx.project_dir, ".familiar")
    if under_root(resolved, familiar_root):
        return (False,
                "CORE-INSTRUCTIONS-READONLY: '.familiar/' is read-only - never edit installed protocol, "
                "route, schema, skill, or adapter files. Behavioural feedback goes in the project's "
                "user-preferences.md; systemic changes need the system maintainer. (Maintainer "
                "override: FAMILIAR_MAINTAINER=1 or the .familiar-maintainer marker.)")
    inputs_root = resolve_lexical(ctx.project_dir, "1-Inputs")
    if under_root(resolved, inputs_root):
        return (False,
                "CORE-COPY-ON-EDIT: source input is read-only - never write into '1-Inputs/'. A changed "
                "source becomes a new dated copy elsewhere (copy-on-edit); compiled understanding "
                "goes to '3-Knowledge/' via ingest. (Maintainer override: FAMILIAR_MAINTAINER=1 or the "
                ".familiar-maintainer marker.)")

    if FAMILIAR_HOME_FILE.search(fp) and ".." not in fp:
        return ALLOW
    if SCRATCH_ROOT.search(fp) and ".." not in fp:
        return ALLOW

    if not under_root(resolved, ctx.project_dir):
        return (False,
                f"CORE-WORKSPACE-SILO: write only inside the project folder. Target is "
                f"outside it: {fp} (Writes under AppData\\Local\\Temp\\claude\\ are auto-allowed. "
                "Maintainer override: FAMILIAR_MAINTAINER=1 or the .familiar-maintainer marker.)")
    return ALLOW


# --- guard: delete ---------------------------------------------------------------------------
def _collect_vars(cmd: str) -> dict[str, str]:
    """Collect this command's own variable assignments into a name -> value map, without
    touching the command text itself. Covers POSIX `NAME=value` (VAR_ASSIGN) and PowerShell
    `$name = "value"` (PS_VAR_ASSIGN) - two different assignment syntaxes feeding the same
    $name-reference resolution, since both are just "$name" once assigned. $env:NAME is resolved
    against this process's own environment (see ENV_VAR_REF's comment) inside an assigned value.
    Values can reference each other (OUT="$SCRATCH/x" is the shape the docx skill emits), so
    resolve values against each other first. Longest names first, or $SCRATCHPAD gets clobbered
    by $SCRATCH."""
    variables: dict[str, str] = {}
    for m in VAR_ASSIGN.finditer(cmd):
        name = m.group(1)
        variables[name] = m.group(2) if m.group(2) is not None else \
            m.group(3) if m.group(3) is not None else m.group(4)
    for m in PS_VAR_ASSIGN.finditer(cmd):
        name = m.group(1)
        val = m.group(2) if m.group(2) is not None else \
            m.group(3) if m.group(3) is not None else m.group(4)
        variables[name] = ENV_VAR_REF.sub(lambda em: os.environ.get(em.group(1), em.group(0)), val)
    names = sorted(variables, key=len, reverse=True)
    for _ in range(3):
        for k in names:
            for j in names:
                if j == k:
                    continue
                variables[k] = variables[k].replace("${" + j + "}", variables[j]) \
                                           .replace("$" + j, variables[j])
    return variables


def _substitute(token: str, variables: dict[str, str]) -> str:
    """Resolve $name/${name}/$env:NAME references inside ONE already-extracted token (a cd
    target, or a write/read destination) - never inject a resolved value back into command TEXT
    that still needs re-tokenizing. Doing that (the original shape of this fix) corrupts as soon
    as a resolved value contains a space, which is ordinary for a real path
    ('Documents\\Claude Code\\...') - found live 2026-08-23 writing the parity test case for the
    exact live-discovered shape, one edit after the fix that motivated it."""
    if "$" not in token:
        return token
    names = sorted(variables, key=len, reverse=True)
    for _ in range(3):
        for k in names:
            token = token.replace("${" + k + "}", variables[k]).replace("$" + k, variables[k])
    return ENV_VAR_REF.sub(lambda em: os.environ.get(em.group(1), em.group(0)), token)


def _expand_vars(cmd: str) -> str:
    """Whole-command variable expansion for decide_delete, which re-splits and re-tokenizes the
    RESULT (unlike the writes/reads path below, which now substitutes only into an
    already-isolated destination token via _substitute - see its docstring for why)."""
    variables = _collect_vars(cmd)
    names = sorted(variables, key=len, reverse=True)
    expanded = cmd
    for k in names:
        expanded = expanded.replace("${" + k + "}", variables[k]).replace("$" + k, variables[k])
    # Bare $env:NAME references outside any assignment (e.g. `-Path $env:USERPROFILE\...`)
    # resolve the same way.
    expanded = ENV_VAR_REF.sub(lambda em: os.environ.get(em.group(1), em.group(0)), expanded)
    return expanded


def decide_delete(ev: Event, ctx: Context) -> Decision:
    if not ctx.has_project_marker or ctx.is_maintainer:
        return ALLOW
    cmd = ev.command
    if not cmd or not cmd.strip():
        return ALLOW
    unwrapped = _unwrap_shell(cmd)
    if not (DELETE_VERB.search(unwrapped) or DELETE_FLAG.search(unwrapped)):
        return ALLOW

    expanded = _expand_vars(unwrapped)
    cwd = ""
    saw_delete = False
    all_safe = True

    for part in CMD_SPLIT.split(expanded):
        t = part.strip()
        m = CD_CMD.match(t)
        if m:
            cwd = resolve_lexical(cwd, m.group(1).strip().strip("\"'"))
            continue

        m = RM_CMD.match(t)
        if m:
            saw_delete = True
            for tok in (x.strip("\"'") for x in TOKENS.findall(m.group(1))):
                if tok.startswith("-"):
                    continue                      # flag, not a path
                if "$" in tok:
                    all_safe = False              # unresolved variable - cannot verify
                    break
                # Globs are fine: the resolved directory portion still has to sit inside
                # scratch, so an expansion cannot escape it.
                if not SCRATCH_ROOT.search(resolve_lexical(cwd, tok)):
                    all_safe = False
                    break
            if not all_safe:
                break

        m = FIND_CMD.match(t)
        if m and FIND_DELETE.search(m.group(1)):
            saw_delete = True
            roots = []
            for tok in (x.strip("\"'") for x in TOKENS.findall(m.group(1))):
                if tok.startswith("-"):
                    break                         # options start; roots are done
                if "$" in tok:
                    all_safe = False
                    break
                roots.append(tok)
            if not roots:
                all_safe = False
            for r in roots:
                if not SCRATCH_ROOT.search(resolve_lexical(cwd, r)):
                    all_safe = False
                    break
            if not all_safe:
                break

    # git clean is never auto-allowed - too broad to scope-check.
    if GIT_CLEAN.search(unwrapped):
        all_safe = False

    if saw_delete and all_safe:
        return ALLOW
    return (False,
            f"CORE-NO-DELETE: never delete files. Blocked command: {cmd}\nIf something is obsolete, "
            "say so and let the user decide. (Deletes resolving inside AppData\\Local\\Temp\\claude\\ "
            "are auto-allowed; this one does not. Maintainer override: FAMILIAR_MAINTAINER=1 or the "
            ".familiar-maintainer marker.)")


# --- guard: reads -----------------------------------------------------------------------------
def _shell_read_targets(cmd: str, project_dir: str) -> list[str]:
    """Destinations a shell command would read from, resolved against a tracked cwd - same shape
    and same per-token substitution posture as _shell_write_targets (see its docstring)."""
    cmd = _unwrap_shell(cmd)
    variables = _collect_vars(cmd)
    cwd = project_dir
    targets: list[str] = []
    for part in CMD_SPLIT.split(cmd):
        t = part.strip()
        m = CD_CMD.match(t)
        if m:
            cwd = resolve_lexical(cwd, _substitute(m.group(1).strip().strip("\"'"), variables))
            continue
        m = READ_VERB.match(t)
        if m:
            dest = _write_target(m.group(3), strip_slash_flags=False)
            if dest:
                dest = _substitute(dest, variables)
                targets.append(dest if "$" in dest else resolve_lexical(cwd, dest))
    return targets


def decide_reads(ev: Event, ctx: Context) -> Decision:
    if not ctx.has_project_marker or ctx.is_maintainer:
        return ALLOW
    if not ev.has_tool_input:
        return ALLOW
    # Read uses file_path; Grep and Glob use path. Neither present means "search from cwd",
    # which is already the project root, so there is nothing to check.
    fp = ev.file_path or ev.path
    if not fp or not fp.strip():
        if not ev.command or not ev.command.strip():
            return ALLOW
        for target in _shell_read_targets(ev.command, ctx.project_dir):
            decision = _decide_read_target(target, ctx)
            if not decision[0]:
                return decision
        return ALLOW
    return _decide_read_target(fp, ctx)


def _decide_read_target(fp: str, ctx: Context) -> Decision:
    if "$" in fp:
        # Same posture as _decide_write_target: unresolved after _expand_vars means deny, not
        # guess-and-allow.
        return (False,
                f"familiar: could not verify this read's target - it still contains an unresolved "
                f"'$' reference after variable expansion: {fp}\nRefusing rather than assuming it "
                "resolves inside the project. (Maintainer override: FAMILIAR_MAINTAINER=1 or the "
                ".familiar-maintainer marker.)")
    resolved = resolve_lexical(ctx.project_dir, fp)
    if under_root(resolved, ctx.project_dir):
        return ALLOW
    if SCRATCH_ROOT.search(resolved):
        return ALLOW
    if ctx.home:
        # checkin reads the user's optional cross-project preferences fallback (the familiar
        # signature default), /system-settings -> Fleet reads the hub's registry, and
        # /deliverable-brief lists and reads global profiles - the only legitimate home reads.
        for name in FAMILIAR_HOME_FILES:
            known = resolve_lexical("", os.path.join(ctx.home, ".familiar", name))
            if resolved.lower() == known.lower():
                return ALLOW
        profiles = resolve_lexical("", os.path.join(ctx.home, ".familiar", FAMILIAR_HOME_DIR))
        parent, _, leaf = resolved.rpartition("/")
        if resolved.lower() == profiles.lower() or (
                parent.lower() == profiles.lower() and leaf.lower().endswith(".md")):
            return ALLOW

    return (False,
            f"familiar: read only within the project folder. Target is outside it: {fp}\nIf this file is "
            "needed, ask the user for it or have them copy it into the project's 1-Inputs folder "
            "rather than reading it directly. (Reads under AppData\\Local\\Temp\\claude\\, "
            "~/.familiar/user-preferences.md, ~/.familiar/fleet.md and ~/.familiar/brief-profiles/*.md "
            "are auto-allowed. Maintainer override: "
            "FAMILIAR_MAINTAINER=1 or the .familiar-maintainer marker.)")


# --- guard: boundary ---------------------------------------------------------------------------
def decide_boundary(ev: Event, ctx: Context) -> Decision:
    """Two rules gated on OPPOSITE conditions - this is the whole design.

    M1 fires inside the maintainer checkout and blocks project scaffolding there.
    M2 fires everywhere else and keeps maintainer-only tooling out of project folders.
    Deliberately NOT self-limiting: a containment rule that only runs inside the thing it
    contains is not a containment rule.
    """
    if not ev.has_tool_input:
        return ALLOW

    if ctx.in_repo:
        if ctx.allow_scaffold:
            return ALLOW
        fp = ev.file_path
        if not fp or not fp.strip():
            return ALLOW
        if re.search(r"[\\/]\.familiar-project$", fp):
            return (False,
                    "familiar boundary: refusing to write a '.familiar-project' marker inside the "
                    "maintainer repo. This checkout is the system source, not a bound project - a "
                    "marker here would activate the guards against the maintainer and make the repo "
                    "look like project work (CLAUDE.md: do not scaffold a project or create this "
                    "marker at the repository root). Download or copy familiar-workspace/ to a "
                    "project folder outside this repo instead - Design A has no setup command; the "
                    "folder is bound the moment it is opened. (Override: FAMILIAR_ALLOW_SCAFFOLD=1.)")
        # Design A's own familiar-workspace/ sits at this repo's root as tracked maintainer
        # content, meant to be edited directly (CLAUDE.md: "Edit runtime files as maintained
        # artifacts") - unlike the retired scaffold model, there is no separate template copy to
        # protect it from, so M1 no longer polices a second, scaffolded workspace folder name.
        return ALLOW

    # M2
    if ctx.maintainer_env:
        return ALLOW
    cmd = ev.command
    if not cmd or not cmd.strip():
        return ALLOW
    for part in CMD_SPLIT.split(cmd):
        if AUDIT_SCRIPT.search(part) and AUDIT_INTERPRETER.search(part):
            return (False,
                    "familiar boundary: 'system-audit' is maintainer-only and this folder is not the "
                    "maintainer checkout (no path-matched '.familiar-maintainer'). It audits the familiar repo "
                    "as a distributed plugin; run from a project folder it reports on the wrong tree. "
                    "Open the familiar repo and run it there. (Override: FAMILIAR_MAINTAINER=1.)")
    return ALLOW


# --- PostToolUse advisory checks ------------------------------------------------------------
# Ported from check-office.ps1 / check-naming.ps1 on 2026-08-30. Those two ran through
# powershell.exe, which exists under that name on Windows only - on macOS or Linux the hook was a
# hard ENOENT, not a degraded check, the same portability break that moved the four PreToolUse
# guards into this file in Phase 2. Folding them in leaves hooks.json with exactly one runtime.
#
# BEHAVIOUR CHANGE, deliberate: the .ps1 originals ran with no project-marker gate. Here they sit
# behind main()'s existing self-limiting fast path like every guard but boundary, so they are
# dormant outside a familiar project. Both conventions they enforce are familiar's own, and every
# deliverable they judge is written inside a marked workspace, so this costs no real coverage.
OOXML_EXT = re.compile(r"\.(docx|pptx|xlsx)$", re.I)
DELIVERABLE_EXT = re.compile(r"\.(docx|pptx|xlsx|pdf)$", re.I)
# 'Drafts for Review/' renamed to 'Drafts/' in the Design A migration (STATUS.md - Audit B3),
# then to '2-Drafts/' in the content-folder sort-order rename (STATUS.md, 2026-09-12).
# Matches at the start of a project-relative path too (no leading separator), unlike the old
# folder name check - under Design A the project root IS the workspace, so '2-Drafts/x.pptx' is a
# normal relative path with nothing before it, not just an interior segment of a longer one.
DRAFTS_SEGMENT = re.compile(r"(^|[\\/])2-Drafts[\\/]")
# YYYY-MM-DD_<label>_<STATUS>_v<N>[_AI].ext - label lowercase-hyphen, STATUS an uppercase enum.
# Case-SENSITIVE by design (the .ps1 used -cmatch): 'Draft' is a convention breach, not a pass.
DELIVERABLE_NAME = re.compile(
    r"^\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*_(?:DRAFT|REVIEW|FINAL)_v\d+(?:_AI)?\.[A-Za-z0-9]+$")
# Added 2026-09-20, not ported from a .ps1 original - familiar's first PostToolUse check with no
# PowerShell ancestor, following the office/naming shape rather than translating one. A by-source
# knowledge page under '3-Knowledge/' (basename not leading with '_' - that excludes
# _page-template.md, _knowledge-index.md, _abbreviations.md, and a source's own _extract-*.md
# cache, none of which carry ref_carry_through) must stamp ingest.md step 5's ref_carry_through
# front-matter field. This check is purely structural: present, and shaped like either "n/a - ..."
# or "<N> claims tagged, <M> carried ...". It CANNOT verify the count is honest - that requires
# re-reading the source against the page, which stays ingest.md step 4's own responsibility
# whether or not this guard is installed. See ingest.md step 5's own note on this division.
KNOWLEDGE_SEGMENT = re.compile(r"(^|[\\/])3-Knowledge[\\/]")
KNOWLEDGE_SPECIAL_FILE = re.compile(r"[\\/]_[^\\/]*$")
REF_CARRY_THROUGH_FIELD = re.compile(r"(?m)^ref_carry_through:\s*(.+?)\s*$")
REF_CARRY_THROUGH_NA = re.compile(r"^n/a\b", re.I)
REF_CARRY_THROUGH_COUNT = re.compile(r"^(\d+)\s+claims?\s+tagged,\s*(\d+)\s+carried", re.I)


def _is_complete_ooxml(path: str) -> bool:
    """A .docx/.pptx/.xlsx is valid only once its central directory is written (file-handling.md).
    Catches the silent-truncation failure mode a partial write leaves behind."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except (OSError, ValueError, zipfile.BadZipFile):
        return False
    return bool(names) and "[Content_Types].xml" in names


def decide_office(ev: Event, ctx: Context) -> Decision:
    """PostToolUse: the file is already written, so this cannot block. Exit 2 feeds the reason
    back to the agent so it regenerates instead of reporting a corrupt file as done."""
    fp = ev.file_path or ev.path
    if not fp.strip() or not OOXML_EXT.search(fp):
        return ALLOW
    path = fp if os.path.isabs(fp) else os.path.join(ctx.project_dir, fp)
    if not os.path.isfile(path):
        return ALLOW
    if _is_complete_ooxml(path):
        return ALLOW
    time.sleep(0.4)   # a bridge may still be serving a partial copy; retry once, as the .ps1 did
    if _is_complete_ooxml(path):
        return ALLOW
    return (False,
            "Integrity check FAILED for '%s': not a complete OOXML archive (missing central "
            "directory or [Content_Types].xml) - likely truncated/corrupt. Do NOT report it as "
            "done; regenerate and re-verify (file-handling.md)." % fp)


def decide_naming(ev: Event, ctx: Context) -> Decision:
    """PostToolUse, advisory: flags a dated deliverable in '2-Drafts/' whose filename breaks the
    file-handling.md convention."""
    fp = ev.file_path or ev.path
    if not fp.strip() or not DRAFTS_SEGMENT.search(fp) or not DELIVERABLE_EXT.search(fp):
        return ALLOW
    name = re.split(r"[\\/]", fp)[-1]
    if DELIVERABLE_NAME.match(name):
        return ALLOW
    return (False,
            "Filename '%s' breaks the familiar convention: YYYY-MM-DD_<label>_<STATUS>_v<N>"
            "[_AI].ext (STATUS in DRAFT/REVIEW/FINAL; label lowercase, e.g. kickoff-deck; version "
            "always present). Rename before delivering (file-handling.md)." % name)


def decide_citation(ev: Event, ctx: Context) -> Decision:
    """PostToolUse, advisory: a by-source knowledge page under '3-Knowledge/' must stamp
    ingest.md step 5's 'ref_carry_through' front-matter field. Structural only - see the
    KNOWLEDGE_SEGMENT block comment above for exactly what this can and cannot verify."""
    fp = ev.file_path or ev.path
    if not fp.strip() or not KNOWLEDGE_SEGMENT.search(fp) or KNOWLEDGE_SPECIAL_FILE.search(fp):
        return ALLOW
    path = fp if os.path.isabs(fp) else os.path.join(ctx.project_dir, fp)
    if not os.path.isfile(path):
        return ALLOW
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ALLOW
    m = REF_CARRY_THROUGH_FIELD.search(text)
    if not m:
        return (False,
                "ingest.md step 5: this knowledge page has no 'ref_carry_through' front-matter "
                "field. Every by-source page must stamp it - '<N> claims tagged, <M> carried a "
                "source-native marker' for a source that cites its own claims, or 'n/a - source "
                "carries no citation markers of its own' otherwise. Add it before calling this "
                "page done.")
    value = m.group(1).strip()
    if REF_CARRY_THROUGH_NA.match(value):
        return ALLOW
    cm = REF_CARRY_THROUGH_COUNT.match(value)
    if not cm:
        return (False,
                f"ingest.md step 5: 'ref_carry_through: {value}' does not match either expected "
                "shape - '<N> claims tagged, <M> carried a source-native marker' or 'n/a - source "
                "carries no citation markers of its own'. Fix the field rather than leaving a "
                "value nothing downstream can parse.")
    tagged, carried = int(cm.group(1)), int(cm.group(2))
    if carried > tagged:
        return (False,
                f"ingest.md step 5: 'ref_carry_through' reports {carried} carried out of "
                f"{tagged} tagged - carried cannot exceed tagged. Recount before calling this "
                "page done.")
    return ALLOW


GUARDS = {
    "writes": decide_writes,
    "delete": decide_delete,
    "reads": decide_reads,
    "boundary": decide_boundary,
    # PostToolUse advisory checks - see the block above.
    "office": decide_office,
    "naming": decide_naming,
    "citation": decide_citation,
}


# --- host adapters ------------------------------------------------------------------------------
def parse_event(raw: str, host: str) -> Event | None:
    """Normalise a host's PreToolUse payload. None means 'nothing to judge - allow'."""
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    # Claude Code, Codex and Gemini CLI's BeforeTool: tool_input. Copilot: toolArgs. Cursor:
    # tool_input on preToolUse. Gemini's write_file/read_file/replace all name their path
    # argument file_path and grep_search/glob name theirs path - same keys Claude Code uses,
    # so no host-specific field mapping is needed here. (geminicli.com/docs/hooks/reference
    # and docs/tools/file-system.md, confirmed 2026-08-21.)
    ti = data.get("tool_input")
    if ti is None:
        ti = data.get("toolArgs")
    if ti is None:
        ti = data.get("tool_args")
    if not isinstance(ti, dict):
        return Event(has_tool_input=False)
    return Event(
        file_path=str(ti.get("file_path") or ti.get("filePath") or ""),
        path=str(ti.get("path") or ""),
        command=str(ti.get("command") or ""),
    )


def _gemini_cwd(raw: str) -> str:
    """Pull the "cwd" field Gemini CLI's BeforeTool payload carries alongside tool_input."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("cwd") or "")


def emit_deny(reason: str, host: str) -> int:
    if host in ("claude", "codex", "gemini"):
        # Codex and Gemini CLI's BeforeTool both accept Claude Code's exit-2-with-stderr
        # contract verbatim: exit 2 = "System Block", stderr becomes the reason text the
        # agent sees. (geminicli.com/docs/hooks/reference, confirmed 2026-08-21.)
        print(reason, file=sys.stderr)
        return 2
    if host == "copilot":
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
        return 0
    if host == "cursor":
        print(json.dumps({"permission": "deny", "user_message": reason, "agent_message": reason}))
        return 0
    print(reason, file=sys.stderr)
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--guard", required=True, choices=sorted(GUARDS))
    ap.add_argument("--host", default="claude",
                    choices=["claude", "codex", "copilot", "cursor", "gemini"])
    args = ap.parse_args(argv)

    # lstrip a leading BOM: some hook runners (observed piping through PowerShell 5.1) prepend
    # one, and a BOM in front of '{' fails json.loads, which parse_event silently reads as
    # "nothing to judge, allow" - exactly the wrong direction for a guard to fail open.
    raw = sys.stdin.read().lstrip(BOM)

    env = os.environ
    if args.host == "gemini" and not os.environ.get("CLAUDE_PROJECT_DIR"):
        # Gemini CLI has no CLAUDE_PROJECT_DIR analogue exposed to the hook process; its
        # BeforeTool payload carries the project cwd directly (stdin field "cwd"), which is
        # more reliable than trusting the hook's own process cwd.
        cwd = _gemini_cwd(raw)
        if cwd:
            env = dict(os.environ)
            env["CLAUDE_PROJECT_DIR"] = cwd

    ctx = Context.load(env)
    # Self-limiting fast path, matching the .ps1 guards: without a project marker the three
    # project guards do nothing at all. guard-boundary is the deliberate exception - its M2
    # rule has to fire where the marker is absent, which is everywhere.
    if args.guard != "boundary" and not ctx.has_project_marker:
        return 0

    ev = parse_event(raw, args.host)
    if ev is None:
        return 0

    allowed, reason = GUARDS[args.guard](ev, ctx)
    if allowed:
        return 0
    return emit_deny(reason, args.host)


if __name__ == "__main__":
    sys.exit(main())
