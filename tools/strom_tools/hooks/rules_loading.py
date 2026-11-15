"""Loads the `.claude/rules` that a Bash command touched.

Claude Code loads a rule when Read, Edit or Write touch a file matching its `paths`, and after a Bash command
that only views one file (`cat`, `head`, `sed -n`, `grep`: since 2.1.293, checked 2026-11-14), but after no other
Bash command (a pipe, a redirect, a `cd` first, a directory, a script): half of the reads in past sessions were
Bash commands, and the rules loaded in few sessions. After a Bash command, `after_bash` takes each word of it
that names a file or directory of the repository (a directory stands for the files in it), and adds each rule
whose `paths` match one to the context the command ran in: once per context, not after a command that only views
one file (Claude Code loads the rule once this hook has run, so it would arrive twice), not when its transcript
shows Claude Code loaded it already, and only as many as fit into one hook output (`CONTEXT_LIMIT`); it names the
others, and a later command adds them. A session has a context of its own conversation and one per subagent (a
subagent's calls run the same hooks, and what a hook adds goes to the subagent): what the hook added to each it
keeps in a memo, that of the conversation until a summary of the context drops it (`at_start`), all of them until the
session ends (`at_end`); a summary of a subagent's context is not seen here, so its memo stays.
"""

import re
import shlex
from collections.abc import Sequence
from pathlib import PurePosixPath

from strom_tools.docs_check.rule_notes import RuleNote, rule_notes
from strom_tools.hooks.hook_events import Session, SessionEnded, SessionStarted, ToolUsed
from strom_tools.hooks.hook_results import CONTEXT_LIMIT, HookResult, Note
from strom_tools.hooks.memos import Memo, forget, forget_all, memo, recalled, remember
from strom_tools.sessions.transcripts import loaded_natively, subagent_transcript
from strom_tools.workspace.repository import Repository

_SAMPLES = ("x.py", "x.md")
"""What a directory named in a command stands for: files of these kinds in it."""
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
_VIEW = re.compile(r"(cat|head|tail|sed|grep)(?= [^|&;<>$`\n]*$)")
"""The beginning of a command that views files and has no pipe, redirect, second command or expansion."""


def _memos(session: Session) -> str:
    """The directory of a session's memos."""
    return f"rules-loaded/{session.id}"


def _loaded(repository: Repository, session: Session, agent_id: str | None = None) -> Memo:
    """The names of the rules this hook added to a context of a session: that of its own conversation, or of its
    subagent `agent_id`."""
    return memo(repository, f"{_memos(session)}/{agent_id or 'main'}.txt")


def after_bash(repository: Repository, event: ToolUsed) -> HookResult:
    if event.command is None or _only_views(repository, event.command):
        return None
    kept = _loaded(repository, event.session, event.agent_id)
    loaded = recalled(kept)
    new = _to_add(_touched(repository, event.command), rule_notes(repository), loaded)
    transcript = event.session.transcript
    if transcript is not None and event.agent_id is not None:
        transcript = subagent_transcript(transcript, event.agent_id)
    if transcript is not None:
        new = [rule for rule in new if not loaded_natively(transcript, rule.path)]
    if not new:
        return None
    added, note = _packed(repository, new)
    remember(kept, sorted({*loaded, *(rule.path.name for rule in added)}))
    return note


def _to_add(touched: Sequence[PurePosixPath], rules: Sequence[RuleNote], loaded: Sequence[str]) -> list[RuleNote]:
    """The rules whose `paths` match a path the command touched, except those added to the context before."""
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


def at_start(repository: Repository, event: SessionStarted) -> HookResult:
    """After a summary of the conversation's context, which drops what was added to it before (as Claude Code's own
    loads, see `loaded_natively`): forgets what was added to it."""
    if event.source == "compact":
        forget(_loaded(repository, event.session))
    return None


def at_end(repository: Repository, event: SessionEnded) -> HookResult:
    forget_all(repository, _memos(event.session))
    return None


def _touched(repository: Repository, command: str) -> list[PurePosixPath]:
    """The repository paths that words of `command` name (from the root, after a `cd` from where it went;
    directories as sample files in them, but the root itself, which names no area: `git diff .`). The quoted value
    of an assignment counts as its words (`M="python bin/mutant.py"; $M`), any other quoted text as one."""
    try:
        words = shlex.split(command, comments=True)
    except ValueError:  # unbalanced quotes: a rough split is good enough
        words = command.split()
    found: list[PurePosixPath] = []
    directory = repository.root
    after_cd = False
    for word in words:
        separators = r"[=:,;|&<>()\s]" if _ASSIGNMENT.match(word) else r"[=:,;|&<>()]"
        parts: list[str] = re.split(separators, word)
        for part in parts:
            path = (directory / part).resolve() if part and not part.startswith("-") else None
            if after_cd and path is not None:
                directory = path
            after_cd = part == "cd"
            if path is None or path == repository.root or not path.is_relative_to(repository.root) or not path.exists():
                continue
            relative = PurePosixPath(path.relative_to(repository.root).as_posix())
            found.extend([relative / sample for sample in _SAMPLES] if path.is_dir() else [relative])
    return found


def _only_views(repository: Repository, command: str) -> bool:
    """Whether `command` is one after which Claude Code loads the rules itself: a `cat`, `head`, `tail`, `sed -n`
    or `grep` of one file of the repository, and nothing else."""
    viewer = _VIEW.match(command)
    if viewer is None or (viewer.group() == "sed" and " -n " not in command):
        return False
    touched = _touched(repository, command)
    return len(touched) == 1 and (repository.root / touched[0]).is_file()


def _matches(paths: Sequence[PurePosixPath], globs: Sequence[str]) -> bool:
    return any(path.full_match(glob) for path in paths for glob in globs)
