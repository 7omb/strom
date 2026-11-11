"""Loads the `.claude/rules` that a Bash command touched.

Claude Code loads a rule when Read, Edit or Write touch a file matching its `paths`, but not when a Bash
command reads the file (`cat`, `sed -n`, `grep`): half of the reads in past sessions were such commands, and
the rules loaded in few sessions. After a Bash command, `after_bash` takes each word of it that names a file or
directory of the repository (a directory stands for the files in it), and adds each rule whose `paths` match
one to Claude's context: once per session, and not when the transcript shows Claude Code loaded it already, and
only as many as fit into one hook output (`CONTEXT_LIMIT`); it names the others, and a later command adds them.
What it added in a session it keeps in a memo, until the session ends (`at_end`)."""

import re
import shlex
from collections.abc import Sequence
from pathlib import PurePosixPath

from strom_tools.docs_check import RuleNote, rule_notes
from strom_tools.hooks.hook_events import Session, SessionEnded, ToolUsed
from strom_tools.hooks.hook_results import CONTEXT_LIMIT, HookResult, Note
from strom_tools.hooks.memos import Memo, forget, memo, recalled, remember
from strom_tools.sessions.transcripts import loaded_natively
from strom_tools.workspace.repository import Repository

_SAMPLES = ("x.py", "x.md")
"""What a directory named in a command stands for: files of these kinds in it."""


def _loaded(repository: Repository, session: Session) -> Memo:
    """The names of the rules this hook added in a session."""
    return memo(repository, f"rules-loaded/{session.id}.txt")


def after_bash(repository: Repository, event: ToolUsed) -> HookResult:
    if event.command is None:
        return None
    kept = _loaded(repository, event.session)
    loaded = recalled(kept)
    new = _to_add(_touched(repository, event.command), rule_notes(repository), loaded)
    transcript = event.session.transcript
    if transcript is not None:
        new = [rule for rule in new if not loaded_natively(transcript, rule.path)]
    if not new:
        return None
    added, note = _packed(repository, new)
    remember(kept, sorted({*loaded, *(rule.path.name for rule in added)}))
    return note


def _to_add(touched: Sequence[PurePosixPath], rules: Sequence[RuleNote], loaded: Sequence[str]) -> list[RuleNote]:
    """The rules whose `paths` match a path the command touched, except those added in the session before."""
    return [rule for rule in rules if rule.path.name not in loaded and _matches(touched, rule.globs)]


def _packed(repository: Repository, rules: Sequence[RuleNote]) -> tuple[list[RuleNote], Note]:
    """The rules that fit into one hook output (`CONTEXT_LIMIT`), in their order, each one that still fits, and the
    note that adds them and names the others: those are not remembered, so a later command adds them."""

    def named(rule: RuleNote) -> str:
        return f"`{rule.path.relative_to(repository.root)}`"

    def left_out(rules: Sequence[RuleNote]) -> str:
        return f"Matched, not added at Claude Code's limit for a hook output: {', '.join(map(named, rules))}"

    budget = CONTEXT_LIMIT - len(left_out(rules)) - 2  # room for naming them all, after a blank line
    added: list[RuleNote] = []
    sections: list[str] = []
    for rule in rules:
        section = f"Contents of {rule.path.relative_to(repository.root)}:\n\n{rule.body}"
        if len("\n\n".join([*sections, section])) <= budget:
            added.append(rule)
            sections.append(section)
    others = [rule for rule in rules if rule not in added]
    return added, Note(for_claude="\n\n".join([*sections, left_out(others)] if others else sections))


def at_end(repository: Repository, event: SessionEnded) -> HookResult:
    forget(_loaded(repository, event.session))
    return None


def _touched(repository: Repository, command: str) -> list[PurePosixPath]:
    """The repository paths that words of `command` name (from the root; directories as sample files in them, but
    the root itself, which names no area: `git diff .`)."""
    try:
        words = shlex.split(command, comments=True)
    except ValueError:  # unbalanced quotes: a rough split is good enough
        words = command.split()
    found: list[PurePosixPath] = []
    for word in words:
        parts: list[str] = re.split(r"[=:,;|&<>()]", word)
        for part in parts:
            path = (repository.root / part).resolve() if part and not part.startswith("-") else None
            if path is None or path == repository.root or not path.is_relative_to(repository.root) or not path.exists():
                continue
            relative = PurePosixPath(path.relative_to(repository.root).as_posix())
            found.extend([relative / sample for sample in _SAMPLES] if path.is_dir() else [relative])
    return found


def _matches(paths: Sequence[PurePosixPath], globs: Sequence[str]) -> bool:
    return any(path.full_match(glob) for path in paths for glob in globs)
