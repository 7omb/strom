"""What the commands that compare lines share (`collect_ids`, `typing_snapshot`): `save` a snapshot, `diff` with a
saved one, or `diff --against REV` with the lines of a revision, taken in a copy of it."""

import argparse
import tempfile
from collections.abc import Callable
from pathlib import Path

from strom_tools.change_checks import line_diffs
from strom_tools.change_checks.revisions import checkout, parse
from strom_tools.workspace.repository import Repository, shown

_ACTIONS = ["save", "diff"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=_ACTIONS)
    parser.add_argument("--name", default="before", help="name of the snapshot (default: before)")
    parser.add_argument("--against", metavar="REV", help="diff: compare with revision REV instead of a snapshot")


def save_or_diff(
    repository: Repository,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    *,
    kind: str,
    what: str,
    lines_in: Callable[[Path, bool], list[str]],
    kept: Callable[[str], bool] | None = None,
) -> int:
    """Does what the arguments of `add_arguments` ask for, with the lines `lines_in(root, is_copy)` finds in the
    repository or in the copy of a revision; the exit code: 1 if a `diff` found differences.

    `kind` names the snapshot files, `what` the lines in the output; of a saved snapshot only the `kept` lines are
    compared (default: all)."""
    action: str = args.action
    name: str = args.name
    against: str | None = args.against
    if against is not None and action != "diff":
        parser.error("--against needs `diff`")
    if against is not None:
        revision = parse(repository, against)
        with tempfile.TemporaryDirectory(prefix=f"strom-{kind}-") as tmp:
            before = lines_in(checkout(repository, revision, Path(tmp)), True)
        label = f"in {against}"
    else:
        snapshot = line_diffs.snapshot(repository, kind, name)
        if action == "save":
            current = lines_in(repository.root, False)
            line_diffs.save(snapshot, current)
            print(f"{len(current)} {what} saved in {shown(repository, snapshot)}")
            return 0
        before = [line for line in line_diffs.saved(repository, snapshot) if kept is None or kept(line)]
        label = "saved"
    diff = line_diffs.diff_lines(before, lines_in(repository.root, False))
    print(line_diffs.rendered(diff, what, label))
    return 1 if line_diffs.differs(diff) else 0
