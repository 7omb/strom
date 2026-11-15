"""Checks that the paths and names the docs cite in backticks are tracked, that lines are short and that a
decision has its form (run by `make lint`).

Run:  python bin/check_docs.py [--style] [FILE ...]

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
    `strom_tools.docs_check.doc_problems`): the module is tracked and defines the first name after it at its top
    level.
Tracked, not merely there: a clone has only what is tracked, so a doc that cites a new file fails here until
the file is added (`git add`); such a reference is printed with that hint.
Spans with placeholders (`<topic>`, `...`, `…`), spaces, URLs, absolute or home paths (`/proc/…`, `~/`) are
skipped, and so are code blocks and the lists under **Rejected** up to the next heading or the next line that
starts in bold (the decisions in `docs/decisions/` cite old names there). So a doc names a file that is only
planned without its path and extension (a module `shards` in `src/strom/_runtime/`) or with an ellipsis. Each
missing reference is printed as `FILE:LINE: REF` with a hint, each long line as `FILE:LINE: N characters`; the
exit code is 1 if there is any.
A rules file of Claude Code (`.claude/rules/*.md`) needs `paths` in its front matter (Claude Code loads one
without them in every session), each of its globs must match a tracked file, and its text (without the front
matter) stays under `strom_tools.docs_check.doc_problems.NOTE_LIMIT`: several notes fit into one hook output,
and a longer one holds two topics.
The `description` of a skill (`.claude/skills/`) or a subagent (`.claude/agents/`) has at most
`strom_tools.docs_check.doc_problems.DESCRIPTION_WORDS` words: every session loads it with the list of them.
A decision (`docs/decisions/*.md`) has its form (`strom_tools.docs_check.decision_form`): it starts, after its
title, with a paragraph whose first sentence has at most 40 words (a code span counts as one); each alternative
under **Rejected** ends with its reason in parentheses, or has it after a parenthesis and a colon
(`alternative (when): why`); and outside tables and code no paragraph or list item has numbers separated by
slashes, a sentence with more than six numbers (dates and code spans apart) or `->` between two numbers. A
fraction, two versions and a mapping of numbers look like these: they go in words or into a code span.

`--style` prints after the problems, for a review of the docs, the paragraphs and list items with a count that
prompts a look (`strom_tools.docs_check.prose_counts`): more than two semicolons in a sentence, a parenthesis of
more than 12 words (not under **Rejected**). They are no problems: the exit code is that of the check without
them.
"""

from collections.abc import Sequence
from pathlib import Path

from strom_tools.commands import command_line
from strom_tools.docs_check import prose_counts
from strom_tools.docs_check.doc_problems import docs, known, problems, rendered
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
    parser.add_argument("--style", action="store_true", help="also the counts that prompt a look")
    parser.add_argument("files", nargs="*", type=Path, metavar="FILE", help="default: every Markdown file git sees")
    args = parser.parse_args(argv)
    files: list[Path] = args.files
    style: bool = args.style
    repository = this_repository()
    citable = known(repository)
    checked = [file.resolve() for file in files] or docs(repository)
    found = [problem for doc in checked for problem in problems(doc, citable)]
    for problem in found:
        print(rendered(problem))
    if style:
        for doc in checked:
            for count in prose_counts.counts(repository, doc):
                print(prose_counts.rendered(count))
    return 1 if found else 0
