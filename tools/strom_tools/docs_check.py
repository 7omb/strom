"""The check of the docs: the paths and names they cite in backticks are tracked, and their lines are short.

What counts as a citation and what is skipped: `strom_tools.commands.check_docs`."""

import ast
import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from strom_tools.workspace import git_files
from strom_tools.workspace.repository import SOURCE_ROOTS, Repository, shown

_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_EXTENSIONS = {".py", ".md", ".toml", ".json", ".jsonl", ".nix", ".lock", ".txt", ".yaml", ".yml", ".cfg", ".in"}
_SKIPPED = re.compile(r"[<>\s…]|\.\.\.|://|^~|^\$|^-|^\.\./|^/")
_DOTTED_NAME = re.compile(rf"({'|'.join(SOURCE_ROOTS)})(\.\w+)+")
"""A module of the library or of the tools, or a name in one."""
_MAX_LINE = 120  # ruff's line-length and mdformat's wrap (`.mdformat.toml`)
_WIDE_TABLES = "docs/research"
"""Its tables are exempt from `_MAX_LINE` until they are restructured (`docs/todo.md`)."""
UNTRACKED = " (untracked: `git add` it)"
_MISSING = " (not found; if it is only planned: its name without path and extension, or with `…`)"


@dataclass(frozen=True)
class FileSet:
    files: frozenset[str]
    """Paths from the root."""
    with_directories: frozenset[str]
    """The files and their directories (`.` is the root)."""


def _file_set(names: Iterable[str]) -> FileSet:
    files = frozenset(names)
    return FileSet(files, files | {parent.as_posix() for name in files for parent in PurePosixPath(name).parents})


@dataclass(frozen=True)
class Known:
    """What the docs of a repository may cite."""

    repository: Repository
    tracked: FileSet
    """The files in the index that are not deleted: what a clone has."""
    seen: FileSet
    """With those that are neither tracked nor ignored: what a `git add` would make citable."""
    names_read: dict[str, frozenset[str]]
    """The top-level names of each module source read so far (by its path from the root): filled by `_names_of`."""


def known(repository: Repository) -> Known:
    tracked = _file_set(git_files.seen(repository, untracked=False))
    return Known(repository, tracked, _file_set(git_files.seen(repository)), {})


def docs(repository: Repository) -> list[Path]:
    """The Markdown files git sees."""
    return [repository.root / name for name in sorted(git_files.seen(repository, "*.md", "**/*.md"))]


def problems(doc: Path, known: Known) -> list[str]:
    """The long lines of a doc and the references it cites that are not tracked, each as `FILE:LINE: ...`."""
    root = known.repository.root
    found: list[str] = []
    name = shown(known.repository, doc)
    directory = doc.parent.relative_to(root).as_posix() if doc.is_relative_to(root) else None
    lines = doc.read_text(encoding="utf-8").splitlines()
    in_front_matter = bool(lines) and lines[0] == "---"
    in_code_block = in_rejected = False
    for number, line in enumerate(lines, start=1):
        if in_front_matter:
            in_front_matter = number == 1 or line != "---"
            continue
        wide_table = line.startswith("|") and doc.is_relative_to(root / _WIDE_TABLES)
        if len(line) > _MAX_LINE and "://" not in line and not wide_table:
            found.append(f"{name}:{number}: {len(line)} characters (at most {_MAX_LINE})")
        if line.lstrip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if line.startswith("#"):
            in_rejected = False
        elif line.startswith("**Rejected**"):  # the alternatives cite old names on purpose
            in_rejected = True
        if in_rejected:
            continue
        for match in _SPAN.finditer(line):
            span: str = match.group(1)
            reference = span.strip()
            if not _SKIPPED.search(reference) and not _cited(reference, directory, known.tracked, known):
                hint = UNTRACKED if _cited(reference, directory, known.seen, known) else _MISSING
                found.append(f"{name}:{number}: {reference}{hint}")
    return found


def _cited(reference: str, directory: str | None, files: FileSet, known: Known) -> bool:
    """Whether what `reference` cites is among `files`, for a doc in `directory` (its path from the root; None: a
    doc outside the repository). True also for what is no path or dotted name."""
    if _DOTTED_NAME.fullmatch(reference):
        return _library_name_cited(reference, files, known)
    path = re.sub(r"(::\w+.*|:\d+(-\d+)?)$", "", reference)
    if "/" not in path and Path(path).suffix not in _EXTENSIONS:
        return True  # not a path: code, a command, a name
    if not re.fullmatch(r"[\w./*\-\[\]]+", path):
        return True  # a command or an expression that contains a slash
    first_part_exists = (known.repository.root / path.split("/")[0]).exists()
    if Path(path).suffix not in _EXTENSIONS and not path.endswith("/") and not first_part_exists:
        return True  # a notation such as `tracked_a/b/c`, not a path
    # from the root, or from the citing doc
    candidates = {posixpath.normpath(posixpath.join(start, path)) for start in (".", directory) if start is not None}
    if any(char in path for char in "*["):
        return any(PurePosixPath(name).full_match(pattern) for pattern in candidates for name in files.with_directories)
    if candidates & files.with_directories:
        return True
    inner = f"/{path.rstrip('/')}"
    if any(f"/{name}".endswith(inner) or f"{inner}/" in f"/{name}" for name in files.files):
        return True
    return git_files.is_ignored(known.repository, path)  # generated files (`.checks/…`, caches) need not exist


def _library_name_cited(dotted: str, files: FileSet, known: Known) -> bool:
    """Whether `dotted` is a module of a package of `SOURCE_ROOTS` among `files`, or a top-level name of one
    (deeper attributes unchecked)."""
    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        module = posixpath.join(SOURCE_ROOTS[parts[0]], *parts[:end])
        for source in (f"{module}/__init__.py", f"{module}.py"):
            if source in files.files:
                return end == len(parts) or parts[end] in _names_of(source, known)
    return False


def _names_of(source: str, known: Known) -> frozenset[str]:
    if source not in known.names_read:
        text = (known.repository.root / source).read_text(encoding="utf-8")
        known.names_read[source] = _top_level_names(text)
    return known.names_read[source]


def _top_level_names(source: str) -> frozenset[str]:
    """The names a module's source defines or imports at its top level."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.TypeAlias():
                names.add(node.name.id if isinstance(node, ast.TypeAlias) else node.name)
            case ast.Assign() | ast.AnnAssign():
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names.update(target.id for target in targets if isinstance(target, ast.Name))
            case ast.Import() | ast.ImportFrom():
                names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
            case _:
                pass
    return frozenset(names)
