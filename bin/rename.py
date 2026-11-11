"""Renames an identifier in the Python code or moves a file, with what the docs and comments say of it.

Run:  python bin/rename.py OLD NEW [--write] [--mentions] [--force] [PATH ...]

OLD and NEW are two identifiers, or the path of a file and the path it moves to (with a `/` or an extension).
PATH: the files or directories to search (default for an identifier: the Python files of src, tests,
benchmarks, examples, bin and the hooks, and the Markdown files git sees; for a file: every file git sees).
Without `--write`, a dry run: it lists what would change and changes nothing.

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
  module     of a module of the library, the dotted name likewise (`strom._runtime.shards`, also in front of
             a name it defines: imports, docs), and the package in `from PACKAGE import MODULE`
  review     a `from PACKAGE import MODULE` that needs more than a new package: one with further names or
             over several lines, or of a module whose own name changes (its uses in that file are a rename
             of an identifier with that file as PATH). Listed, never written: change these by hand.
`--write` then moves the file (`git mv` if it is tracked, which stages the move).

Edits apply by character offsets, line by line from the right, so formatting and comments stay. After a
write, ruff sorts the imports of the changed Python files and formats them (`make fix`), and the lines it
leaves over the limit are listed (docstrings and comments: it does not wrap those). Then run the suite.
"""

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ["src", "tests", "benchmarks", "examples", "bin", ".claude/hooks"]
LIBRARY = "src"
TEXT = {tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE, tokenize.TSTRING_MIDDLE}
IDENTIFIER_KINDS = ["code", "collision", "mention"]
FILE_KINDS = ["path", "module", "review"]
WRITTEN = {"code", "path", "module"}
"""The kinds a `--write` applies; `mention` only with `--mentions`, `collision` and `review` never."""


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--write", action="store_true", help="apply the renames (default: a dry run)")
    parser.add_argument("--mentions", action="store_true", help="an identifier: also rename the mentions")
    parser.add_argument("--force", action="store_true", help="an identifier: write despite collisions")
    args = parser.parse_args()
    moving = not (args.old.isidentifier() and args.new.isidentifier())
    old, new = Path(args.old).resolve(), Path(args.new).resolve()  # of the file, if one moves
    if not moving:
        hits, kinds = [hit for path in files(args.paths) for hit in scan(path, args.old, args.new)], IDENTIFIER_KINDS
    elif old.is_file() and old.is_relative_to(ROOT) and new.is_relative_to(ROOT) and not new.exists():
        hits, kinds = citations(old, new, files(args.paths, everything=True)), FILE_KINDS
    else:
        sys.exit("OLD and NEW must be identifiers, or a file of the repository and a free path in it")
    for hit in hits:
        line = hit.path.read_text(encoding="utf-8").splitlines()[hit.row - 1].strip()
        print(f"{hit.kind:9}  {hit.path.relative_to(ROOT)}:{hit.row}:  {line[:110]}")
    counts = Counter(hit.kind for hit in hits)
    print(", ".join(f"{counts[kind]} {kind}" for kind in kinds))
    if not args.write:
        return 0
    if counts["collision"] and not args.force:
        sys.exit("collisions: rename those names first, or pass --force")
    written = WRITTEN | ({"mention"} if args.mentions else set())
    changed = apply([hit for hit in hits if hit.kind in written])
    if moving:
        move(old, new)
        changed = [new if path == old else path for path in changed]
    tidy(changed)
    print(f"renamed in {len(changed)} files" + (f", moved to {new.relative_to(ROOT)}" if moving else ""))
    if counts["review"]:
        print("change the lines listed as review by hand")
    return 0


def files(paths: list[Path], *, everything: bool = False) -> list[Path]:
    """The files to search: `paths` (of a directory, its Python files); without any, the Python files of `CODE`
    and the Markdown files git sees, or with `everything` every file git sees but the locks."""
    if not paths and everything:
        return [path for path in seen() if path.suffix != ".lock"]
    if not paths:
        paths = [ROOT / name for name in CODE] + seen("*.md")
    found: list[Path] = []
    for path in (path.resolve() for path in paths):
        found.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path] if path.exists() else [])
    return found


def seen(*patterns: str) -> list[Path]:
    """The files git sees (tracked, or untracked and not ignored) that match one of `patterns` (none: all)."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *patterns],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / name for name in listed.split("\0") if name and (ROOT / name).is_file()]


def scan(path: Path, old: str, new: str) -> list[Hit]:
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
        elif token.type in TEXT and end_row == row:
            hits.extend(
                Hit(path, row, col + match.start(), "mention", old, new) for match in word.finditer(token.string)
            )
        elif token.type in TEXT:  # a string over several lines: the offsets per line
            lines = source.splitlines()[row - 1 : end_row]
            for at, line in enumerate(lines):
                first = col if at == 0 else 0
                hits.extend(
                    Hit(path, row + at, match.start(), "mention", old, new) for match in word.finditer(line, first)
                )
    return hits


def citations(old: Path, new: Path, searched: list[Path]) -> list[Hit]:
    """Where the files `searched` cite the file `old`, which moves to `new`."""
    old_parts, new_parts = old.relative_to(ROOT).parts, new.relative_to(ROOT).parts
    cited = endings(old_parts, new_parts, "/")
    old_module: list[str] = []
    new_module: list[str] = []
    if old.suffix == new.suffix == ".py" and old_parts[0] == new_parts[0] == LIBRARY:
        old_module, new_module = [*old_parts[1:-1], old.stem], [*new_parts[1:-1], new.stem]
        cited |= endings(old_module, new_module, ".")
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
        hits.extend(
            Hit(path, row, match.start(), "path" if "/" in match[0] else "module", match[0], cited[match[0]])
            for row, line in enumerate(source.splitlines(), start=1)
            for match in pattern.finditer(line)
        )
        if path.suffix == ".py" and len(old_module) > 1:
            hits.extend(package_imports(path, source, old_module, new_module))
    return hits


def endings(old: Sequence[str], new: Sequence[str], separator: str) -> dict[str, str]:
    """Each ending of two or more parts of `old`, joined, with what replaces it: `new` without the leading parts
    the ending leaves out (an ending whose left-out parts differ in `new` has no replacement)."""
    return {
        separator.join(old[cut:]): separator.join(new[cut:]) for cut in range(len(old) - 1) if old[:cut] == new[:cut]
    }


def package_imports(path: Path, source: str, old_module: Sequence[str], new_module: Sequence[str]) -> list[Hit]:
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


def apply(hits: list[Hit]) -> list[Path]:
    """Replaces the old text at every hit (all files checked before any is written); the files changed."""
    by_path: dict[Path, list[Hit]] = {}
    for hit in hits:
        by_path.setdefault(hit.path, []).append(hit)
    renamed: dict[Path, str] = {}
    for path, path_hits in by_path.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for hit in sorted(path_hits, key=lambda hit: (hit.row, hit.start), reverse=True):
            line = lines[hit.row - 1]
            if line[hit.start : hit.start + len(hit.old)] != hit.old:
                sys.exit(f"{path}:{hit.row}: {hit.old} not at column {hit.start}: nothing written")
            lines[hit.row - 1] = line[: hit.start] + hit.new + line[hit.start + len(hit.old) :]
        renamed[path] = "".join(lines)
    for path, text in renamed.items():
        path.write_text(text, encoding="utf-8")
    return list(renamed)


def move(old: Path, new: Path) -> None:
    new.parent.mkdir(parents=True, exist_ok=True)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(old)], cwd=ROOT, capture_output=True)
    if tracked.returncode == 0:
        subprocess.run(["git", "mv", str(old), str(new)], cwd=ROOT, check=True)
    else:
        old.rename(new)


def tidy(changed: list[Path]) -> None:
    """Sorts the imports of the changed Python files and formats them, then lists the lines that stay over the
    limit: `make fix` and `make lint-python`, each with the one rule (a rename runs amid other changes, which the
    other fixes are not for)."""
    python = " ".join(str(path) for path in changed if path.suffix == ".py")
    if python:
        make = ["make", "--no-print-directory", "--silent", f"FILES={python}"]
        subprocess.run([*make, "fix", "ARGS=--select I"], cwd=ROOT, check=False)
        report = [*make, "lint-python", "ARGS=--quiet --select E501 --output-format concise"]
        long_lines = subprocess.run(report, cwd=ROOT, capture_output=True, text=True, check=False)
        print(long_lines.stdout if long_lines.returncode != 0 else "", end="")


if __name__ == "__main__":
    sys.exit(main())
