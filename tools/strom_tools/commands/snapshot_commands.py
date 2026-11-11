"""What the commands that compare lines share (`collect_ids`, `typing_snapshot`): `save` a snapshot, `diff` with a
saved one, or `diff --against REV` with the lines of a revision, taken in a copy of it."""

import argparse
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from strom_tools.change_checks import line_diffs, snapshots
from strom_tools.change_checks.revisions import Revision, as_argument, checkout, parse
from strom_tools.workspace.repository import Repository, shown


class _Action(Enum):
    SAVE = "save"
    DIFF = "diff"


@dataclass(frozen=True)
class Save:
    name: str


@dataclass(frozen=True)
class DiffSaved:
    name: str


@dataclass(frozen=True)
class DiffRevision:
    revision: Revision


type Request = Save | DiffSaved | DiffRevision


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = [action.value for action in _Action]
    parser.add_argument("action", choices=actions)
    parser.add_argument("--name", default="before", help="name of the snapshot (default: before)")
    parser.add_argument("--against", metavar="REV", help="diff: compare with revision REV instead of a snapshot")


def request(repository: Repository, parser: argparse.ArgumentParser, args: argparse.Namespace) -> Request:
    """What the arguments of `add_arguments` ask for (a usage error for `--against` without `diff`, a `ToolError`
    for a revision this repository does not have)."""
    chosen: str = args.action
    name: str = args.name
    against: str | None = args.against
    match _Action(chosen), against:
        case _Action.SAVE, None:
            return Save(name)
        case _Action.SAVE, _:
            parser.error("--against needs `diff`")
        case _Action.DIFF, None:
            return DiffSaved(name)
        case _Action.DIFF, revision:
            return DiffRevision(parse(repository, revision))


def save_or_diff(
    repository: Repository,
    asked: Request,
    *,
    kind: str,
    what: str,
    lines_in: Callable[[Path], list[str]],
    kept: Callable[[str], bool] | None = None,
) -> int:
    """Does what was `asked`, with the lines `lines_in(root)` finds in the repository or in the copy of a
    revision; the exit code: 1 if a diff found differences.

    `kind` names the snapshot files, `what` the lines in the output; of a saved snapshot only the `kept` lines are
    compared (default: all)."""
    match asked:
        case Save(name):
            snapshot = snapshots.snapshot(repository, kind, name)
            current = lines_in(repository.root)
            snapshots.save(snapshot, current)
            print(f"{len(current)} {what} saved in {shown(repository, snapshot)}")
            return 0
        case DiffSaved(name):
            saved = snapshots.saved(repository, snapshots.snapshot(repository, kind, name))
            before, label = [line for line in saved if kept is None or kept(line)], "saved"
        case DiffRevision(revision):
            with tempfile.TemporaryDirectory(prefix=f"strom-{kind}-") as tmp:
                before = lines_in(checkout(repository, revision, Path(tmp)))
            label = f"in {as_argument(revision)}"
    diff = line_diffs.diff_lines(before, lines_in(repository.root))
    print(line_diffs.rendered(diff, what, label))
    return 1 if line_diffs.differs(diff) else 0
