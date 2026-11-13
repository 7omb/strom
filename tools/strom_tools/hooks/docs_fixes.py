"""Formats and checks the docs after Claude's changes.

At the end of a turn, if the working tree has changes:
  - `make fix` on the Markdown files among them that changed since it last ran here (the Makefile: mdformat as
    the commit hook has it), so that a commit reformats nothing and a line that passes the limit only then
    shows now;
  - `make lint-docs` (the docs check on every doc): a change to the code may have taken a path or a name that a
    doc cites.
What they report goes back to Claude, once per turn like ruff's errors (`python_fixes`). Not so the citations of
files that are only untracked: staging is the user's (`docs/decisions/git-index.md`), so Claude could not make the
check pass. If nothing else is wrong, they go to the user as a note, once per set of them, and block nothing;
`make lint` keeps failing for them until they are staged."""

import re
from collections.abc import Sequence

from strom_tools.docs_check.doc_problems import UNTRACKED
from strom_tools.hooks.hook_events import TurnEnded
from strom_tools.hooks.hook_results import Block, HookResult, Note
from strom_tools.hooks.memos import Memo, forget, memo, recalled, remember, remembered_at
from strom_tools.workspace import git_files
from strom_tools.workspace.make_runs import problems, run_make
from strom_tools.workspace.repository import Repository

_MARKDOWN = ".md"
_MAKES_OWN_LINE = re.compile(r"make(\[\d+\])?: \*\*\* ")
"""What make says of a target that failed, after the target's own output."""


def _formatted(repository: Repository) -> Memo:
    """Written, without lines, after mdformat ran: the next stop formats the files changed since (the commit hook
    formats them all)."""
    return memo(repository, "docs-formatted")


def _told_untracked(repository: Repository) -> Memo:
    """The untracked citations the user was last told of."""
    return memo(repository, "docs-untracked")


def at_stop(repository: Repository, event: TurnEnded) -> HookResult:
    if event.again:
        return None
    changed = git_files.changed(repository)
    if not changed:
        return None
    formatted = _formatted(repository)
    formatted_at = remembered_at(formatted) or 0.0
    markdown = [
        name for name in changed if name.endswith(_MARKDOWN) and (repository.root / name).stat().st_mtime > formatted_at
    ]
    unformatted = problems(run_make(repository, "fix", f"FILES={' '.join(markdown)}")) if markdown else ""
    if markdown and not unformatted:
        remember(formatted, [])
    told = _told_untracked(repository)
    result, told_now = _verdict(unformatted, problems(run_make(repository, "lint-docs")), recalled(told))
    if told_now:
        remember(told, told_now)
    else:
        forget(told)
    return result


def _verdict(unformatted: str, checked: str, told: Sequence[str]) -> tuple[HookResult, list[str]]:
    """What a stop answers, from what the formatter and the docs check reported and the untracked citations the
    user was told of; and those the user has been told of after it.

    A problem other than an untracked citation blocks, with all of them. Else the untracked citations go to the
    user as a note, unless they are those of the last time; none of them: nothing to say, and the next ones are
    new."""
    untracked = [line for line in checked.splitlines() if line.endswith(UNTRACKED)]
    others = [line for line in checked.splitlines() if line not in untracked and not _MAKES_OWN_LINE.match(line)]
    if unformatted or others:
        return Block(f"the docs after this turn's changes:\n{unformatted}{checked}"), list(told)
    if not untracked or untracked == list(told):
        return None, untracked
    report = "\n".join(untracked)
    note = f"The docs cite files that git does not track yet; staging them is yours (`git add`):\n{report}"
    return Note(for_user=note), untracked
