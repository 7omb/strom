"""Renames an identifier in the Python code and lists (or renames) its mentions in docs and comments.

Run:  python bin/rename.py OLD NEW [--write] [--mentions] [--force] [PATH ...]

PATH: the files or directories to search (default: src, tests, benchmarks, examples, bin and the Markdown
files git sees). Without `--write`, a dry run: it lists what would change and changes nothing.

  code       every NAME token OLD in Python files (from `tokenize`, so names inside f-strings too, but not
             in other strings): definitions, uses, attributes and keyword arguments alike. Lexical: an
             attribute or local of the same name elsewhere is renamed too; check the listed lines.
  collision  each file where NEW already occurs as a name (a local that would shadow the renamed one, or
             two definitions merging); `--write` refuses while there are any, unless `--force`. Rename
             such locals first.
  mention    OLD as a whole word in strings, docstrings, comments and Markdown (e.g. `` `OLD` `` in
             ARCHITECTURE.md); renamed only with `--mentions`, else listed for review.

Edits apply by character offsets, line by line from the right, so formatting and comments stay. After
`--write`: `ruff check --fix --select I` (import order) and the suite.
"""

import argparse
import io
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ["src", "tests", "benchmarks", "examples", "bin"]
TEXT = {tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE, tokenize.TSTRING_MIDDLE}


@dataclass(frozen=True)
class Hit:
    path: Path
    row: int
    """1-based line."""
    start: int
    """Character offset in the line."""
    kind: str
    """`code`, `collision` or `mention`."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--write", action="store_true", help="apply the renames (default: a dry run)")
    parser.add_argument("--mentions", action="store_true", help="also rename the mentions")
    parser.add_argument("--force", action="store_true", help="write despite collisions")
    args = parser.parse_args()
    if not args.old.isidentifier() or not args.new.isidentifier():
        sys.exit("OLD and NEW must be identifiers")
    hits = [hit for path in files(args.paths) for hit in scan(path, args.old, args.new)]
    for hit in hits:
        line = hit.path.read_text(encoding="utf-8").splitlines()[hit.row - 1].strip()
        print(f"{hit.kind:9}  {hit.path.relative_to(ROOT)}:{hit.row}:  {line[:110]}")
    counts = {kind: sum(hit.kind == kind for hit in hits) for kind in ("code", "collision", "mention")}
    print(", ".join(f"{count} {kind}" for kind, count in counts.items()))
    if not args.write:
        return 0
    if counts["collision"] and not args.force:
        sys.exit("collisions: rename those names first, or pass --force")
    kinds = {"code", "mention"} if args.mentions else {"code"}
    changed = apply([hit for hit in hits if hit.kind in kinds], args.old, args.new)
    print(f"renamed in {changed} files")
    return 0


def files(paths: list[Path]) -> list[Path]:
    if not paths:
        markdown = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        paths = [ROOT / name for name in CODE] + [ROOT / name for name in markdown.split("\0") if name]
    found: list[Path] = []
    for path in (path.resolve() for path in paths):
        found.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path] if path.exists() else [])
    return found


def scan(path: Path, old: str, new: str) -> list[Hit]:
    source = path.read_text(encoding="utf-8")
    if old not in source and (path.suffix != ".py" or new not in source):
        return []
    word = re.compile(rf"\b{re.escape(old)}\b")
    if path.suffix != ".py":
        return [
            Hit(path, row, match.start(), "mention")
            for row, line in enumerate(source.splitlines(), start=1)
            for match in word.finditer(line)
        ]
    hits: list[Hit] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        (row, col), (end_row, _) = token.start, token.end
        if token.type == tokenize.NAME and token.string == old:
            hits.append(Hit(path, row, col, "code"))
        elif token.type == tokenize.NAME and token.string == new:
            hits.append(Hit(path, row, col, "collision"))
        elif token.type in TEXT and end_row == row:
            hits.extend(Hit(path, row, col + match.start(), "mention") for match in word.finditer(token.string))
        elif token.type in TEXT:  # a string over several lines: the offsets per line
            lines = source.splitlines()[row - 1 : end_row]
            for at, line in enumerate(lines):
                first = col if at == 0 else 0
                hits.extend(Hit(path, row + at, match.start(), "mention") for match in word.finditer(line, first))
    return hits


def apply(hits: list[Hit], old: str, new: str) -> int:
    """Replaces OLD at every hit (all files checked before any is written); the number of files changed."""
    by_path: dict[Path, list[Hit]] = {}
    for hit in hits:
        by_path.setdefault(hit.path, []).append(hit)
    renamed: dict[Path, str] = {}
    for path, path_hits in by_path.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for hit in sorted(path_hits, key=lambda hit: (hit.row, hit.start), reverse=True):
            line = lines[hit.row - 1]
            if line[hit.start : hit.start + len(old)] != old:
                sys.exit(f"{path}:{hit.row}: {old} not at column {hit.start}: nothing written")
            lines[hit.row - 1] = line[: hit.start] + new + line[hit.start + len(old) :]
        renamed[path] = "".join(lines)
    for path, text in renamed.items():
        path.write_text(text, encoding="utf-8")
    return len(renamed)


if __name__ == "__main__":
    sys.exit(main())
