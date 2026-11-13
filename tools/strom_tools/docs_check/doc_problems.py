"""The check of the docs: the paths and names they cite in backticks are tracked, and their lines are short; a
rules file of Claude Code (`.claude/rules`) has `paths` that match tracked files, and its text stays under
`NOTE_LIMIT`.

What counts as a citation and what is skipped: `strom_tools.commands.check_docs`."""

import ast
import posixpath
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from strom_tools.docs_check.doc_lines import Context, Line, lines_of
from strom_tools.docs_check.rule_notes import RULES, body_of, globs_of
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
NOTE_LIMIT = 2_500
"""The characters of a rules file's text (without the front matter): so that several fit into one hook output
(`strom_tools.hooks.hook_results.CONTEXT_LIMIT`), and a note that outgrows it holds a second topic."""
_SESSION_DOC = "CLAUDE.md"
SESSION_DOC_LIMIT = 8_000
"""The bytes of `CLAUDE.md`, which every session loads whole: what only some work needs goes elsewhere
(`.claude/rules/docs.md`)."""


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


@dataclass(frozen=True)
class LongLine:
    doc: str
    """As messages show it (`shown`)."""
    line: int
    length: int


@dataclass(frozen=True)
class MissingCitation:
    """A reference to what is not there."""

    doc: str
    line: int
    reference: str


@dataclass(frozen=True)
class UntrackedCitation:
    """A reference to a file that is there, but not tracked: a `git add` makes it citable."""

    doc: str
    line: int
    reference: str


@dataclass(frozen=True)
class UnscopedNote:
    """A rules file without `paths`: Claude Code loads it in every session."""

    doc: str
    line: int


@dataclass(frozen=True)
class DeadGlob:
    """A glob of a rules file's `paths` that matches no tracked file: the note never loads for it."""

    doc: str
    line: int
    glob: str


@dataclass(frozen=True)
class LongNote:
    """A rules file whose text is over `NOTE_LIMIT`."""

    doc: str
    line: int
    """Where its text starts."""
    length: int


@dataclass(frozen=True)
class LongSessionDoc:
    """`CLAUDE.md` over `SESSION_DOC_LIMIT`."""

    doc: str
    size: int
    """In bytes."""

    @property
    def line(self) -> int:
        return 1


type Problem = LongLine | MissingCitation | UntrackedCitation | UnscopedNote | DeadGlob | LongNote | LongSessionDoc


def rendered(problem: Problem) -> str:
    """A problem as `FILE:LINE: ...`, with a hint for a citation."""
    match problem:
        case LongLine(doc, line, length):
            return f"{doc}:{line}: {length} characters (at most {_MAX_LINE})"
        case MissingCitation(doc, line, reference):
            return f"{doc}:{line}: {reference}{_MISSING}"
        case UntrackedCitation(doc, line, reference):
            return f"{doc}:{line}: {reference}{UNTRACKED}"
        case UnscopedNote(doc, line):
            return f"{doc}:{line}: no `paths` in its front matter: Claude Code would load it in every session"
        case DeadGlob(doc, line, glob):
            return f"{doc}:{line}: {glob} matches no tracked file: the note never loads for it"
        case LongNote(doc, line, length):
            return (
                f"{doc}:{line}: {length} characters of text (at most {NOTE_LIMIT}): a second topic, a note of its own"
            )
        case LongSessionDoc(doc, size):
            return (
                f"{doc}:1: {size} bytes (at most {SESSION_DOC_LIMIT}): every session loads it; move what only some"
                " work needs to its place (.claude/rules/docs.md)"
            )


def problems(doc: Path, known: Known) -> list[Problem]:
    """The long lines of a doc, the references it cites that are not tracked and, for a rules file, the problems
    of its `paths`, in the order of its lines."""
    root = known.repository.root
    name = shown(known.repository, doc)
    text = doc.read_text(encoding="utf-8")
    lines = list(lines_of(text))
    long_lines = _long_lines(name, lines, wide_tables=doc.is_relative_to(root / _WIDE_TABLES))
    directory = doc.parent.relative_to(root).as_posix() if doc.is_relative_to(root) else None
    cited = _uncited(name, lines, directory, known)
    notes = _note_problems(name, lines, known) if directory == RULES and doc.suffix == ".md" else []
    size = len(text.encode())
    session = [LongSessionDoc(name, size)] if doc == root / _SESSION_DOC and size > SESSION_DOC_LIMIT else []
    return sorted([*session, *notes, *long_lines, *cited], key=_line_of)  # stable: a long line before what it cites


def _line_of(problem: Problem) -> int:
    return problem.line


def _note_problems(
    doc: str, lines: Sequence[Line], known: Known
) -> list[UnscopedNote | DeadGlob | UntrackedCitation | LongNote]:
    """The problems of a rules file: its `paths` (none, or globs that match no tracked file: untracked if they
    match a file a `git add` would track) and its size."""
    globs = globs_of(lines)
    if not globs:
        return [UnscopedNote(doc, 1)]
    tracked = [PurePosixPath(name) for name in known.tracked.files]
    seen = [PurePosixPath(name) for name in known.seen.files]
    dead: list[UnscopedNote | DeadGlob | UntrackedCitation | LongNote] = [
        UntrackedCitation(doc, number, glob)
        if any(file.full_match(glob) for file in seen)
        else DeadGlob(doc, number, glob)
        for number, glob in globs
        if not any(file.full_match(glob) for file in tracked)
    ]
    body = body_of(lines)
    if len(body) <= NOTE_LIMIT:
        return dead
    start = next(line.number for line in lines if line.context is not Context.FRONT_MATTER and line.text.strip())
    return [*dead, LongNote(doc, start, len(body))]


def _long_lines(doc: str, lines: Iterable[Line], *, wide_tables: bool) -> list[LongLine]:
    """The lines over `_MAX_LINE` but those of the front matter, those with a URL and, with `wide_tables`, table
    rows."""
    return [
        LongLine(doc, line.number, len(line.text))
        for line in lines
        if len(line.text) > _MAX_LINE
        and line.context is not Context.FRONT_MATTER
        and "://" not in line.text
        and not (wide_tables and line.text.startswith("|"))
    ]


def _uncited(
    doc: str, lines: Iterable[Line], directory: str | None, known: Known
) -> list[MissingCitation | UntrackedCitation]:
    """The references in backticks in the prose that cite what is not tracked, for a doc in `directory` (its path
    from the root; None: a doc outside the repository)."""
    found: list[MissingCitation | UntrackedCitation] = []
    for line in lines:
        if line.context is not Context.PROSE:
            continue
        for match in _SPAN.finditer(line.text):
            span: str = match.group(1)
            reference = span.strip()
            citation = _citation(reference, known.repository.root)
            if citation is None or _listed(citation, directory, known.tracked, known):
                continue
            if _listed(citation, directory, known.seen, known):
                found.append(UntrackedCitation(doc, line.number, reference))
            else:
                found.append(MissingCitation(doc, line.number, reference))
    return found


@dataclass(frozen=True)
class _DottedName:
    """A module of a package of `SOURCE_ROOTS`, or a name in one."""

    name: str


@dataclass(frozen=True)
class _PathCitation:
    path: str
    """From the root or from the citing doc's directory, or the end of a path (`_metrics/events.py`)."""


@dataclass(frozen=True)
class _GlobCitation:
    pattern: str


type _Citation = _DottedName | _PathCitation | _GlobCitation


def _citation(reference: str, root: Path) -> _Citation | None:
    """What a reference in backticks cites; None for one that cites nothing: a placeholder, code, a command, a
    name, a notation."""
    if _SKIPPED.search(reference):
        return None
    if _DOTTED_NAME.fullmatch(reference):
        return _DottedName(reference)
    path = re.sub(r"(::\w+.*|:\d+(-\d+)?)$", "", reference)  # `:LINE` and `::TEST` name the file
    if "/" not in path and Path(path).suffix not in _EXTENSIONS:
        return None  # code, a command, a name
    if not re.fullmatch(r"[\w./*\-\[\]]+", path):
        return None  # a command or an expression that contains a slash
    first_part_exists = (root / path.split("/")[0]).exists()
    if Path(path).suffix not in _EXTENSIONS and not path.endswith("/") and not first_part_exists:
        return None  # a notation such as `tracked_a/b/c`
    return _GlobCitation(path) if any(char in path for char in "*[") else _PathCitation(path)


def _listed(citation: _Citation, directory: str | None, files: FileSet, known: Known) -> bool:
    """Whether what `citation` cites is among `files`, for a doc in `directory`."""
    match citation:
        case _DottedName(name):
            return _library_name_cited(name, files, known)
        case _GlobCitation(pattern):
            candidates = _from_root(pattern, directory)
            return any(PurePosixPath(name).full_match(glob) for glob in candidates for name in files.with_directories)
        case _PathCitation(path):
            if _from_root(path, directory) & files.with_directories:
                return True
            inner = f"/{path.rstrip('/')}"
            if any(f"/{name}".endswith(inner) or f"{inner}/" in f"/{name}" for name in files.files):
                return True
            return git_files.is_ignored(known.repository, path)  # generated files (`.checks/…`) need not exist


def _from_root(path: str, directory: str | None) -> set[str]:
    """What `path` names from the root: itself, or from the citing doc's directory."""
    return {posixpath.normpath(posixpath.join(start, path)) for start in (".", directory) if start is not None}


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
