"""Loads the `.claude/rules` that a Bash command touched.

Claude Code loads a rule when Read, Edit or Write touch a file matching its `paths`, but not when a Bash
command reads the file (`cat`, `sed -n`, `grep`): half of the reads in past sessions were such commands, and
the rules loaded in few sessions. After a Bash command, `after_bash` takes each word of it that names a file or
directory of the repository (a directory stands for the files in it), and adds each rule whose `paths` match
one to Claude's context: once per session, and not when the transcript shows Claude Code loaded it already.
What it added in a session it keeps in the state directory, until the session ends (`at_end`)."""

import re
import shlex
from pathlib import Path, PurePosixPath

from strom_tools.hooks.hook_events import HookResult, Note, Session, SessionEnded, ToolUsed
from strom_tools.sessions.transcripts import loaded_natively
from strom_tools.workspace.repository import Repository, state_dir

_SAMPLES = ("x.py", "x.md")
"""What a directory named in a command stands for: files of these kinds in it."""


def _rules_dir(repository: Repository) -> Path:
    return repository.root / ".claude" / "rules"


def _loaded_file(repository: Repository, session: Session) -> Path:
    """The names of the rules this hook added in a session."""
    return state_dir(repository) / "rules-loaded" / f"{session.id}.txt"


def after_bash(repository: Repository, event: ToolUsed) -> HookResult:
    if event.command is None:
        return None
    kept = _loaded_file(repository, event.session)
    loaded: set[str] = set(kept.read_text().split()) if kept.exists() else set()
    named = _touched(repository, event.command)
    new = [rule for rule, globs in _rules(repository) if rule.name not in loaded and _matches(named, globs)]
    transcript = event.session.transcript
    if transcript is not None:
        new = [rule for rule in new if not loaded_natively(transcript, rule)]
    if not new:
        return None
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(" ".join(sorted(loaded | {rule.name for rule in new})))
    return Note(
        for_claude="\n\n".join(f"Contents of {rule.relative_to(repository.root)}:\n\n{_body(rule)}" for rule in new)
    )


def at_end(repository: Repository, event: SessionEnded) -> HookResult:
    _loaded_file(repository, event.session).unlink(missing_ok=True)
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


def _rules(repository: Repository) -> list[tuple[Path, list[str]]]:
    """Each rule file with the globs of its `paths` frontmatter."""
    found: list[tuple[Path, list[str]]] = []
    for rule in sorted(_rules_dir(repository).glob("*.md")):
        header = rule.read_text().split("---")
        if len(header) >= 3:
            globs = re.finditer(r'^\s*-\s*"?([^"\n]+?)"?\s*$', header[1], re.MULTILINE)
            found.append((rule, [glob.expand(r"\1") for glob in globs]))
    return found


def _matches(paths: list[PurePosixPath], globs: list[str]) -> bool:
    return any(path.full_match(glob) for path in paths for glob in globs)


def _body(rule: Path) -> str:
    """A rule file without its frontmatter."""
    return rule.read_text().split("---", 2)[2].strip()
