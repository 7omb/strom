"""Prints the outline of Python modules: each definition with its line, its signature and the first line of its
docstring.

Run:  python bin/outline.py PATH ...

PATH: a Python file, or a directory (its Python files that git sees). Per file its path, then one line per
function, class, type alias and assignment, at the top level and in classes (indented), in the order of their
lines, e.g. `   42    def open(cls, *, workers: int) -> Pools  # Opens the pools.` Use it to find where a
definition is and which lines to read, instead of reading a whole module. Where a name is used:
`bin/rename.py OLD NEW` without `--write` lists every use."""

from collections.abc import Sequence
from pathlib import Path

from strom_tools import outlines
from strom_tools.commands import command_line
from strom_tools.tool_error import ToolError
from strom_tools.workspace import git_files
from strom_tools.workspace.repository import Repository, shown, this_repository


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
    parser.add_argument("paths", nargs="+", metavar="PATH", help="Python files or directories")
    args = parser.parse_args(argv)
    paths: list[str] = args.paths
    repository = this_repository()
    for path in _modules(repository, paths):
        print(shown(repository, path))
        try:
            entries = outlines.outline(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            print(f"    (does not parse: {error.msg}, line {error.lineno})")
            continue
        for entry in entries:
            print(outlines.rendered(entry))
    return 0


def _modules(repository: Repository, paths: Sequence[str]) -> list[Path]:
    """The Python files that `paths` name: a file itself, a directory the Python files in it that git sees."""
    found: list[Path] = []
    for name in paths:
        path = Path(name).resolve()
        if path.is_dir():
            inside = path.relative_to(repository.root).as_posix() if path.is_relative_to(repository.root) else None
            if inside is None:
                raise ToolError(f"{name}: a directory outside the repository")
            pattern = "*.py" if inside == "." else f"{inside}/*.py"  # in a pathspec, `*` crosses `/`
            found.extend(repository.root / seen for seen in sorted(git_files.seen(repository, pattern)))
        elif path.is_file():
            found.append(path)
        else:
            raise ToolError(f"{name}: no such file or directory")
    return found
