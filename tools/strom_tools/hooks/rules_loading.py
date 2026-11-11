"""Loads the `.claude/rules` that a Bash command touched.

Claude Code loads a rule when Read, Edit or Write touch a file matching its `paths`, but not when a Bash
command reads the file (`cat`, `sed -n`, `grep`): half of the reads in past sessions were such commands, and
the rules loaded in few sessions. After a Bash command, `after_bash` takes each word of it that names a file or
directory of the repository (a directory stands for the files in it), and adds each rule whose `paths` match
one to Claude's context: once per session, and not when the transcript shows Claude Code loaded it already.
What it added in a session it keeps in a memo, until the session ends (`at_end`)."""

import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from strom_tools.hooks.hook_events import Session, SessionEnded, ToolUsed
from strom_tools.hooks.hook_results import HookResult, Note
from strom_tools.hooks.memos import Memo, forget, memo, recalled, remember
from strom_tools.sessions.transcripts import loaded_natively
from strom_tools.workspace.repository import Repository

_SAMPLES = ("x.py", "x.md")
"""What a directory named in a command stands for: files of these kinds in it."""


def _rules_dir(repository: Repository) -> Path:
    return repository.root / ".claude" / "rules"


def _loaded(repository: Repository, session: Session) -> Memo:
    """The names of the rules this hook added in a session."""
    return memo(repository, f"rules-loaded/{session.id}.txt")


@dataclass(frozen=True)
class _Rule:
    path: Path
    globs: list[str]
    """Of its `paths` frontmatter."""
    body: str
    """Without the frontmatter."""


def after_bash(repository: Repository, event: ToolUsed) -> HookResult:
    if event.command is None:
        return None
    kept = _loaded(repository, event.session)
    loaded = recalled(kept)
    new = _to_add(_touched(repository, event.command), _rules(repository), loaded)
    transcript = event.session.transcript
    if transcript is not None:
        new = [rule for rule in new if not loaded_natively(transcript, rule.path)]
    if not new:
        return None
    remember(kept, sorted({*loaded, *(rule.path.name for rule in new)}))
    return _note(repository, new)


def _to_add(touched: Sequence[PurePosixPath], rules: Sequence[_Rule], loaded: Sequence[str]) -> list[_Rule]:
    """The rules whose `paths` match a path the command touched, except those added in the session before."""
    return [rule for rule in rules if rule.path.name not in loaded and _matches(touched, rule.globs)]


def _note(repository: Repository, rules: Sequence[_Rule]) -> Note:
    added = (f"Contents of {rule.path.relative_to(repository.root)}:\n\n{rule.body}" for rule in rules)
    return Note(for_claude="\n\n".join(added))


def at_end(repository: Repository, event: SessionEnded) -> HookResult:
    forget(_loaded(repository, event.session))
    return None


def _touched(repository: Repository, command: str) -> list[PurePosixPath]:
    """The repository paths that words of `command` name (from the root; directories as sample files in them)."""
    try:
        words = shlex.split(command, comments=True)
    except ValueError:  # unbalanced quotes: a rough split is good enough
        words = command.split()
    found: list[PurePosixPath] = []
    for word in words:
        parts: list[str] = re.split(r"[=:,;|&<>()]", word)
        for part in parts:
            path = (repository.root / part).resolve() if part and not part.startswith("-") else None
            if path is None or not path.is_relative_to(repository.root) or not path.exists():
                continue
            relative = PurePosixPath(path.relative_to(repository.root).as_posix())
            found.extend([relative / sample for sample in _SAMPLES] if path.is_dir() else [relative])
    return found


def _rules(repository: Repository) -> list[_Rule]:
    """The rule files that have a frontmatter."""
    found: list[_Rule] = []
    for path in sorted(_rules_dir(repository).glob("*.md")):
        parts = path.read_text().split("---", 2)
        if len(parts) == 3:
            globs = re.finditer(r'^\s*-\s*"?([^"\n]+?)"?\s*$', parts[1], re.MULTILINE)
            found.append(_Rule(path, [glob.expand(r"\1") for glob in globs], parts[2].strip()))
    return found


def _matches(paths: Sequence[PurePosixPath], globs: Sequence[str]) -> bool:
    return any(path.full_match(glob) for path in paths for glob in globs)
