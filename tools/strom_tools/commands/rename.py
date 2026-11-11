"""Renames an identifier in the Python code or moves a file, with what the docs and comments say of it.

Run:  python bin/rename.py OLD NEW [--write] [--mentions] [--force] [PATH ...]

OLD and NEW are two identifiers, or the path of a file and the path it moves to (with a `/` or an extension).
PATH: the files or directories to search (default for an identifier: the Python files of src, tests,
benchmarks, examples, bin, tools and the hooks, and the Markdown files git sees; for a file: every file git
sees). Without `--write`, a dry run: it lists what would change and changes nothing.

An identifier:
  code       every NAME token OLD in Python files (from `tokenize`, so names inside f-strings too, but not
             in other strings): definitions, uses, attributes and keyword arguments alike. Lexical: an
             attribute or local of the same name elsewhere is renamed too; check the listed lines.
  collision  each file where NEW already occurs as a name (a local that would shadow the renamed one, or
             two definitions merging); `--write` refuses while there are any, unless `--force`. Rename
             such locals first.
  mention    OLD as a whole word in strings, docstrings, comments and Markdown (e.g. `` `OLD` `` in
             ARCHITECTURE.md); renamed only with `--mentions`, else listed for review.

A file (say `src/strom/_runtime/shards.py` to `src/strom/_interpreters/shards.py`; its test module is a call
of its own):
  path       OLD wherever a text cites it, also by an ending of two or more parts (`_runtime/shards.py`)
  module     of a module of the library or the tools, the dotted name likewise (`strom._runtime.shards`, also
             in front of a name it defines: imports, docs), and the package in `from PACKAGE import MODULE`
  review     a `from PACKAGE import MODULE` that needs more than a new package: one with further names or
             over several lines, or of a module whose own name changes (its uses in that file are a rename
             of an identifier with that file as PATH). Listed, never written: change these by hand.
`--write` then moves the file, in the working tree only: nothing is staged, also not for a tracked file (the
old path shows as deleted, the new one as untracked, until both are staged: `git add OLD NEW`).

Edits apply by character offsets, line by line from the right, so formatting and comments stay. After a
write, ruff sorts the imports of the changed Python files and formats them (`make fix`), and the lines it
leaves over the limit are listed (docstrings and comments: it does not wrap those). Then run the suite.
"""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from strom_tools import renames
from strom_tools.commands import command_line
from strom_tools.renames import FileMove, HitKind, IdentifierRename
from strom_tools.workspace.repository import shown, this_repository


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--write", action="store_true", help="apply the renames (default: a dry run)")
    parser.add_argument("--mentions", action="store_true", help="an identifier: also rename the mentions")
    parser.add_argument("--force", action="store_true", help="an identifier: write despite collisions")
    args = parser.parse_args(argv)
    old_name: str = args.old
    new_name: str = args.new
    paths: list[Path] = args.paths
    write: bool = args.write
    mentions: bool = args.mentions
    force: bool = args.force
    repository = this_repository()
    rename = renames.rename_of(repository, old_name, new_name)
    hits = renames.hits(repository, rename, paths)
    for hit in hits:
        print(f"{hit.kind.value:9}  {shown(repository, hit.path)}:{hit.row}:  {renames.line_of(hit)[:110]}")
    counts = Counter(hit.kind for hit in hits)
    print(", ".join(f"{counts[kind]} {kind.value}" for kind in renames.kinds(rename)))
    if not write:
        return 0
    written = renames.write(repository, rename, hits, mentions=mentions, force=force)
    print(written.tidied, end="")
    match rename:
        case FileMove(old, new):
            print(f"renamed in {len(written.changed)} files, moved to {shown(repository, new)}")
            print(f"not staged: `git add {shown(repository, old)} {shown(repository, new)}`")
        case IdentifierRename():
            print(f"renamed in {len(written.changed)} files")
    if counts[HitKind.REVIEW]:
        print("change the lines listed as review by hand")
    return 0
