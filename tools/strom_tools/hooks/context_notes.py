"""What a session needs again after a summary of its context, at the `SessionStart` that follows it (source
`compact`): the plans in progress and the changed files, which a summary tends to lose or to keep only vaguely.

  `at_start`   adds to Claude's context each plan of `docs/plans/` with its line `Open: …`, and the files with
               uncommitted changes"""

import re

from strom_tools.hooks.hook_events import SessionStarted
from strom_tools.hooks.hook_results import HookResult, Note
from strom_tools.workspace import git_files
from strom_tools.workspace.repository import Repository

_PLANS = "docs/plans"
_OPEN = re.compile(r"\bOpen: [^\n]*")
_MAX_FILES = 40
"""The changed files named; more are counted."""


def at_start(repository: Repository, event: SessionStarted) -> HookResult:
    if event.source != "compact":
        return None
    lines = ["After the summary: the state of the work."]
    plans = sorted((repository.root / _PLANS).glob("*.md"))
    for plan in plans:
        found = _OPEN.search(plan.read_text(encoding="utf-8"))
        lines.append(f"- plan `{_PLANS}/{plan.name}`" + (f": {found.group(0)}" if found else ""))
    if not plans:
        lines.append("- no plan in progress")
    changed = git_files.changed(repository)
    named = ", ".join(changed[:_MAX_FILES]) + (
        f" and {len(changed) - _MAX_FILES} more" if len(changed) > _MAX_FILES else ""
    )
    lines.append(f"- uncommitted changes: {named}" if changed else "- no uncommitted changes")
    return Note(for_claude="\n".join(lines))
