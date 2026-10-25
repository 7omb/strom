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
  - a module or name of the library (`strom.testing`, `strom._stages.model.Step`): the module is tracked and
    defines the first name after it at its top level.
Tracked, not merely there: a clone has only what is tracked, so a doc that cites a new file fails here until
the file is added (`git add`); such a reference is printed with that hint.
Spans with placeholders (`<topic>`, `...`, `…`), spaces, URLs, absolute or home paths (`/proc/…`, `~/`) are
skipped, and so are code blocks and the lists under **Rejected** up to the next heading (`docs/decisions.md`
cites old names there). Each missing reference is printed as `FILE:LINE: REF`, each long line as
`FILE:LINE: N characters`; the exit code is 1 if there is any.
"""

import ast
import posixpath
import re
import subprocess
import sys
from functools import cache
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
EXTENSIONS = {".py", ".md", ".toml", ".json", ".jsonl", ".nix", ".lock", ".txt", ".yaml", ".yml", ".cfg", ".in"}
SKIPPED = re.compile(r"[<>\s…]|\.\.\.|://|^~|^\$|^-|^\.\./|^/")
LIBRARY = "src"
MAX_LINE = 120  # ruff's line-length and mdformat's wrap (`.mdformat.toml`)
WIDE_TABLES = ROOT / "docs" / "research"
UNTRACKED = " (untracked: `git add` it)"


def main() -> int:
    files = [Path(name).resolve() for name in sys.argv[1:]] or [ROOT / name for name in sorted(seen("*.md"))]
    missing = [problem for file in files for problem in check(file)]
    for problem in missing:
        print(problem)
    return 1 if missing else 0


def seen(pattern: str, untracked: bool = True) -> frozenset[str]:
    """The files git sees that match `pattern`, as paths from the root: the tracked ones (in the index, and
    not deleted), with `untracked` also those that are neither tracked nor ignored."""
    others = ["--others", "--exclude-standard"] if untracked else []
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", *others, "--", pattern, f"**/{pattern}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return frozenset(name for name in listed.split("\0") if name and (ROOT / name).exists())


@cache
def tracked() -> frozenset[str]:
    return seen("*", untracked=False)


@cache
def in_working_tree() -> frozenset[str]:
    return seen("*")


@cache
def with_directories(files: frozenset[str]) -> frozenset[str]:
    """`files` and their directories, as paths from the root (`.` is the root)."""
    return files | {parent.as_posix() for name in files for parent in PurePosixPath(name).parents}


def check(file: Path) -> list[str]:
    problems: list[str] = []
    shown = file.relative_to(ROOT) if file.is_relative_to(ROOT) else file
    directory = file.parent.relative_to(ROOT).as_posix() if file.is_relative_to(ROOT) else None
    lines = file.read_text(encoding="utf-8").splitlines()
    in_front_matter = bool(lines) and lines[0] == "---"
    in_code_block = in_rejected = False
    for number, line in enumerate(lines, start=1):
        if in_front_matter:
            in_front_matter = number == 1 or line != "---"
            continue
        if (
            len(line) > MAX_LINE
            and "://" not in line
            and not (line.startswith("|") and file.is_relative_to(WIDE_TABLES))
        ):
            problems.append(f"{shown}:{number}: {len(line)} characters (at most {MAX_LINE})")
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
        for match in SPAN.finditer(line):
            reference = match.group(1).strip()
            if not SKIPPED.search(reference) and not cited(reference, directory, tracked()):
                hint = UNTRACKED if cited(reference, directory, in_working_tree()) else ""
                problems.append(f"{shown}:{number}: {reference}{hint}")
    return problems


def cited(reference: str, directory: str | None, files: frozenset[str]) -> bool:
    """Whether what `reference` cites is among `files` (paths from the root), for a doc in `directory` (its
    path from the root; None: a doc outside the repository). True also for what is no path or library name."""
    if re.fullmatch(r"strom(\.\w+)+", reference):
        return library_name_cited(reference, files)
    path = re.sub(r"(::\w+.*|:\d+(-\d+)?)$", "", reference)
    if "/" not in path and Path(path).suffix not in EXTENSIONS:
        return True  # not a path: code, a command, a name
    if not re.fullmatch(r"[\w./*\-\[\]]+", path):
        return True  # a command or an expression that contains a slash
    if Path(path).suffix not in EXTENSIONS and not path.endswith("/") and not (ROOT / path.split("/")[0]).exists():
        return True  # a notation such as `tracked_a/b/c`, not a path
    # from the root, or from the citing doc
    candidates = {posixpath.normpath(posixpath.join(start, path)) for start in (".", directory) if start is not None}
    known = with_directories(files)
    if any(char in path for char in "*["):
        return any(PurePosixPath(name).full_match(pattern) for pattern in candidates for name in known)
    if candidates & known:
        return True
    inner = f"/{path.rstrip('/')}"
    if any(f"/{name}".endswith(inner) or f"{inner}/" in f"/{name}" for name in files):
        return True
    ignored = subprocess.run(["git", "check-ignore", "--quiet", "--no-index", path], cwd=ROOT, check=False)
    return ignored.returncode == 0  # generated files (`.checks/…`, caches) need not exist


def library_name_cited(dotted: str, files: frozenset[str]) -> bool:
    """Whether `dotted` is a module of the library among `files` or a top-level name of one (deeper attributes
    unchecked)."""
    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        module = posixpath.join(LIBRARY, *parts[:end])
        for source in (f"{module}/__init__.py", f"{module}.py"):
            if source in files:
                return end == len(parts) or parts[end] in top_level_names(ROOT / source)
    return False


@cache
def top_level_names(source: Path) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
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


if __name__ == "__main__":
    sys.exit(main())
