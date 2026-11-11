"""Formats and checks the docs after Claude's changes (called by `dispatch.py`).

Stop (the end of a turn), if the working tree has changes:
  - `make fix` on the Markdown files among them that changed since it last ran here (the Makefile: mdformat as
    the commit hook has it), so that a commit reformats nothing and a line that passes the limit only then
    shows now;
  - `make lint-docs` (`bin/check_docs.py` on every doc): a change to the code may have taken a path or a name
    that a doc cites.
What they report goes back to Claude (exit code 2, on stderr), once per turn like ruff's errors (`ruff_hook`).
"""

import sys

from ruff_hook import ROOT, changed_files, make

MARKDOWN = ".md"
FORMATTED = ROOT / ".checks" / "docs-formatted"
"""Touched after mdformat ran: the next Stop formats the files changed since (the commit hook formats them all)."""


def at_stop(event: dict[str, object]) -> int:
    if event.get("stop_hook_active") is True:
        return 0
    changed = changed_files()
    if not changed:
        return 0
    formatted_at = FORMATTED.stat().st_mtime if FORMATTED.exists() else 0.0
    markdown = [name for name in changed if name.endswith(MARKDOWN) and (ROOT / name).stat().st_mtime > formatted_at]
    problems = make("fix", f"FILES={' '.join(markdown)}") if markdown else ""
    if markdown and not problems:
        FORMATTED.parent.mkdir(exist_ok=True)
        FORMATTED.touch()
    problems += make("lint-docs")
    if problems:
        print(f"the docs after this turn's changes:\n{problems}", file=sys.stderr)
        return 2
    return 0
