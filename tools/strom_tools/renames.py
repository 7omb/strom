"""Renaming an identifier in the Python code, or moving a file, with what the docs and comments say of it.

A rename is a list of hits (where a text would change, and to what), found without changing anything; `apply`
writes them. The kinds of hit and what each covers: `strom_tools.commands.rename`."""

import ast
import io
import re
import tokenize
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from strom_tools.tool_error import ToolError
from strom_tools.workspace import git_files
from strom_tools.workspace.make_targets import output, run_make
from strom_tools.workspace.repository import SOURCE_ROOTS, Repository

_CODE = ["src", "tests", "benchmarks", "examples", "bin", "tools", ".claude/hooks"]
"""Where the Python code is that an identifier is renamed in."""
_TEXT = {tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE, tokenize.TSTRING_MIDDLE}
IDENTIFIER_KINDS = ["code", "collision", "mention"]
FILE_KINDS = ["path", "module", "review"]
WRITTEN = {"code", "path", "module"}
"""The kinds a write applies; `mention` only on request, `collision` and `review` never."""


@dataclass(frozen=True)
class Hit:
    path: Path
    row: int
    """1-based line."""
    start: int
    """Character offset in the line."""
    kind: str
    """One of `IDENTIFIER_KINDS` or `FILE_KINDS`."""
    old: str
    """The text at `start`."""
    new: str
    """What replaces it."""


def files(repository: Repository, paths: Sequence[Path], *, everything: bool = False) -> list[Path]:
    """The files to search: `paths` (of a directory, its Python files); without any, the Python files of `_CODE`
    and the Markdown files git sees, or with `everything` every file git sees but the locks."""
    if not paths and everything:
        return [path for path in _seen(repository) if path.suffix != ".lock"]
    if not paths:
        paths = [repository.root / name for name in _CODE] + _seen(repository, "*.md")
    found: list[Path] = []
    for path in (path.resolve() for path in paths):
        found.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path] if path.exists() else [])
    return found


def _seen(repository: Repository, *pathspecs: str) -> list[Path]:
    return [repository.root / name for name in git_files.seen(repository, *pathspecs)]


def scan(path: Path, old: str, new: str) -> list[Hit]:
    """Where the file `path` names the identifier `old` (`code` in Python code, a `mention` in strings, comments
    and other files), and where its Python code names `new` already (a `collision`)."""
    source = path.read_text(encoding="utf-8")
    if old not in source and (path.suffix != ".py" or new not in source):
        return []
    word = re.compile(rf"\b{re.escape(old)}\b")
    if path.suffix != ".py":
        return [
            Hit(path, row, match.start(), "mention", old, new)
            for row, line in enumerate(source.splitlines(), start=1)
            for match in word.finditer(line)
        ]
    hits: list[Hit] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        (row, col), (end_row, _) = token.start, token.end
        if token.type == tokenize.NAME and token.string == old:
            hits.append(Hit(path, row, col, "code", old, new))
        elif token.type == tokenize.NAME and token.string == new:
            hits.append(Hit(path, row, col, "collision", new, new))
        elif token.type in _TEXT and end_row == row:
            hits.extend(
                Hit(path, row, col + match.start(), "mention", old, new) for match in word.finditer(token.string)
            )
        elif token.type in _TEXT:  # a string over several lines: the offsets per line
            lines = source.splitlines()[row - 1 : end_row]
            for at, line in enumerate(lines):
                first = col if at == 0 else 0
                hits.extend(
                    Hit(path, row + at, match.start(), "mention", old, new) for match in word.finditer(line, first)
                )
    return hits


def check_move(repository: Repository, old: Path, new: Path) -> None:
    """A `ToolError` unless `old` is a file of the repository and `new` a free path in it."""
    root = repository.root
    if not (old.is_file() and old.is_relative_to(root) and new.is_relative_to(root) and not new.exists()):
        raise ToolError("OLD and NEW must be identifiers, or a file of the repository and a free path in it")


def move(old: Path, new: Path) -> None:
    """Moves a file in the working tree. The index stays as it is, also for a tracked file (it is the user's,
    `docs/decisions.md`, Index): git finds the move by content once both paths are staged."""
    new.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new)


def citations(repository: Repository, old: Path, new: Path, searched: Sequence[Path]) -> list[Hit]:
    """Where the files `searched` cite the file `old`, which moves to `new`: its `path` (also by an ending of two
    or more parts) and, for a module of a package of `SOURCE_ROOTS`, its dotted name and its imports (`module`,
    or `review` where a new package does not suffice)."""
    old_parts, new_parts = old.relative_to(repository.root).parts, new.relative_to(repository.root).parts
    cited = _endings(old_parts, new_parts, "/")
    old_module: list[str] = []
    new_module: list[str] = []
    if old.suffix == new.suffix == ".py" and old_parts[0] == new_parts[0] and old_parts[0] in SOURCE_ROOTS.values():
        old_module, new_module = [*old_parts[1:-1], old.stem], [*new_parts[1:-1], new.stem]
        cited |= _endings(old_module, new_module, ".")
    if not cited:  # a file at the root: its bare name is no citation
        return []
    alternatives = "|".join(re.escape(text) for text in sorted(cited, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w./-])(?:{alternatives})(?!\w)")  # on its own, not inside a longer path or name
    hits: list[Hit] = []
    for path in searched:
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for row, line in enumerate(source.splitlines(), start=1):
            for match in pattern.finditer(line):
                found: str = match.group()
                hits.append(Hit(path, row, match.start(), "path" if "/" in found else "module", found, cited[found]))
        if path.suffix == ".py" and len(old_module) > 1:
            hits.extend(_package_imports(path, source, old_module, new_module))
    return hits


def _endings(old: Sequence[str], new: Sequence[str], separator: str) -> dict[str, str]:
    """Each ending of two or more parts of `old`, joined, with what replaces it: `new` without the leading parts
    the ending leaves out (an ending whose left-out parts differ in `new` has no replacement)."""
    return {
        separator.join(old[cut:]): separator.join(new[cut:]) for cut in range(len(old) - 1) if old[:cut] == new[:cut]
    }


def _package_imports(path: Path, source: str, old_module: Sequence[str], new_module: Sequence[str]) -> list[Hit]:
    """The statements `from PACKAGE import MODULE` of the moved module: a hit for the package where a new one
    suffices, else one for review."""
    old_package, new_package = ".".join(old_module[:-1]), ".".join(new_module[:-1])
    if old_package not in source:
        return []
    lines = source.splitlines()
    hits: list[Hit] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom) or node.level or node.module != old_package:
            continue
        if any(alias.name == old_module[-1] for alias in node.names):
            start = lines[node.lineno - 1].index(old_package, node.col_offset)
            suffices = len(node.names) == 1 and node.end_lineno == node.lineno and old_module[-1] == new_module[-1]
            hits.append(Hit(path, node.lineno, start, "module" if suffices else "review", old_package, new_package))
    return hits


def line_of(hit: Hit) -> str:
    """The line of a hit as it is now, without its indentation."""
    return hit.path.read_text(encoding="utf-8").splitlines()[hit.row - 1].strip()


def apply(hits: Sequence[Hit]) -> list[Path]:
    """Replaces the old text at every hit (all files checked before any is written); the files changed."""
    by_path: dict[Path, list[Hit]] = {}
    for hit in hits:
        by_path.setdefault(hit.path, []).append(hit)
    renamed: dict[Path, str] = {}
    for path, path_hits in by_path.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for hit in sorted(path_hits, key=_position, reverse=True):  # from the right: the offsets before it stay
            line = lines[hit.row - 1]
            if line[hit.start : hit.start + len(hit.old)] != hit.old:
                raise ToolError(f"{path}:{hit.row}: {hit.old} not at column {hit.start}: nothing written")
            lines[hit.row - 1] = line[: hit.start] + hit.new + line[hit.start + len(hit.old) :]
        renamed[path] = "".join(lines)
    for path, text in renamed.items():
        path.write_text(text, encoding="utf-8")
    return list(renamed)


def _position(hit: Hit) -> tuple[int, int]:
    return hit.row, hit.start


def tidy(repository: Repository, changed: Sequence[Path]) -> str:
    """Sorts the imports of the changed Python files and formats them; what that reports, and the lines that stay
    over the limit: `make fix` and `make lint-python`, each with the one rule (a rename runs amid other changes,
    which the other fixes are not for)."""
    python = " ".join(str(path) for path in changed if path.suffix == ".py")
    if not python:
        return ""
    fixed = run_make(repository, f"FILES={python}", "fix", "ARGS=--select I")
    long_lines = run_make(
        repository, f"FILES={python}", "lint-python", "ARGS=--quiet --select E501 --output-format concise"
    )
    return f"{output(fixed)}{long_lines.stdout if long_lines.returncode != 0 else ''}"
