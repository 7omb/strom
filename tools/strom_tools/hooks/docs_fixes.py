"""Formats and checks the docs after Claude's changes.

At the end of a turn, if the working tree has changes:
  - `make fix` on the Markdown files among them that changed since it last ran here (the Makefile: mdformat as
    the commit hook has it), so that a commit reformats nothing and a line that passes the limit only then
    shows now;
  - `make lint-docs` (the docs check on every doc): a change to the code may have taken a path or a name that a
    doc cites.
What they report goes back to Claude, once per turn like ruff's errors (`python_fixes`). Not so the citations of
files that are only untracked: staging is the user's (`docs/decisions.md`, Index), so Claude could not make the
check pass. If nothing else is wrong, they go to the user as a note, once per set of them, and block nothing;
`make lint` keeps failing for them until they are staged."""

import re
from pathlib import Path

from strom_tools.docs_check import UNTRACKED
from strom_tools.hooks.hook_events import Block, HookResult, Note, TurnEnded
from strom_tools.workspace import git_files
from strom_tools.workspace.make_targets import problems, run_make
from strom_tools.workspace.repository import Repository, state_dir

_MARKDOWN = ".md"
_MAKES_OWN_LINE = re.compile(r"make(\[\d+\])?: \*\*\* ")
"""What make says of a target that failed, after the target's own output."""


def _formatted_mark(repository: Repository) -> Path:
    """Touched after mdformat ran: the next stop formats the files changed since (the commit hook formats them
    all)."""
    return state_dir(repository) / "docs-formatted"


def _told_untracked(repository: Repository) -> Path:
    """The untracked citations the user was last told of."""
    return state_dir(repository) / "docs-untracked"


def at_stop(repository: Repository, event: TurnEnded) -> HookResult:
    if event.again:
        return None
    changed = git_files.changed(repository)
    if not changed:
        return None
    mark = _formatted_mark(repository)
    formatted_at = mark.stat().st_mtime if mark.exists() else 0.0
    markdown = [
        name for name in changed if name.endswith(_MARKDOWN) and (repository.root / name).stat().st_mtime > formatted_at
    ]
    unformatted = problems(run_make(repository, "fix", f"FILES={' '.join(markdown)}")) if markdown else ""
    if markdown and not unformatted:
        mark.parent.mkdir(exist_ok=True)
        mark.touch()
    checked = problems(run_make(repository, "lint-docs"))
    untracked = [line for line in checked.splitlines() if line.endswith(UNTRACKED)]
    others = [line for line in checked.splitlines() if line not in untracked and not _MAKES_OWN_LINE.match(line)]
    if unformatted or others:
        return Block(f"the docs after this turn's changes:\n{unformatted}{checked}")
    return _untracked_note(repository, untracked)


def _untracked_note(repository: Repository, untracked: list[str]) -> HookResult:
    """A note for the user about the citations that only lack a `git add`, unless it is the one of the last time;
    none of them: nothing to say, and the next ones are new."""
    told = _told_untracked(repository)
    report = "\n".join(untracked)
    if report == (told.read_text() if told.exists() else ""):
        return None
    if not untracked:
        told.unlink()
        return None
    told.parent.mkdir(exist_ok=True)
    told.write_text(report)
    return Note(
        for_user=f"The docs cite files that git does not track yet; staging them is yours (`git add`):\n{report}"
    )
