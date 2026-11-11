"""Checks that the paths and names the docs cite in backticks are tracked and that lines are short (run by
`make lint`).

Run:  python bin/check_docs.py [FILE ...]

Reads the Markdown files git sees (tracked, or untracked and not ignored; default: all of them). Every line has
at most 120 characters (mdformat wraps paragraphs, not table rows or code blocks), except front matter, lines
with a URL and table rows in `docs/research/` (not yet restructured). It checks each span in backticks that
cites
  - a path (it contains `/` or ends in a file extension, e.g. `bin/ab.py`, `docs/plans/`, `ARCHITECTURE.md`):
    it is a tracked file (in the index, and not deleted) or a directory of one, relative to the repository
    root or to the citing file; a bare file name (`pools.py`) may be anywhere, a relative path
    (`_metrics/events.py`) may end a tracked path, an ignored path (`.checks/…`: generated) need not exist;
    a glob (`tests/**`) must match something tracked; `:LINE` and `::TEST` suffixes name the file,
  - a module or name of the library or the tools (`strom.testing`, `strom._stages.model.Step`,
    `strom_tools.docs_check`): the module is tracked and defines the first name after it at its top level.
Tracked, not merely there: a clone has only what is tracked, so a doc that cites a new file fails here until
the file is added (`git add`); such a reference is printed with that hint.
Spans with placeholders (`<topic>`, `...`, `…`), spaces, URLs, absolute or home paths (`/proc/…`, `~/`) are
skipped, and so are code blocks and the lists under **Rejected** up to the next heading (`docs/decisions.md`
cites old names there). So a doc names a file that is only planned without its path and extension (a module
`shards` in `src/strom/_runtime/`) or with an ellipsis. Each missing reference is printed as `FILE:LINE: REF`
with a hint, each long line as `FILE:LINE: N characters`; the exit code is 1 if there is any.
"""

from collections.abc import Sequence
from pathlib import Path

from strom_tools.commands import command_line
from strom_tools.docs_check import docs, known, problems, rendered
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
    parser.add_argument("files", nargs="*", type=Path, metavar="FILE", help="default: every Markdown file git sees")
    args = parser.parse_args(argv)
    files: list[Path] = args.files
    repository = this_repository()
    citable = known(repository)
    found = [
        problem for doc in [file.resolve() for file in files] or docs(repository) for problem in problems(doc, citable)
    ]
    for problem in found:
        print(rendered(problem))
    return 1 if found else 0
