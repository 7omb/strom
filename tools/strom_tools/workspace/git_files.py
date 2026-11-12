"""What git knows of the repository's files: every call of git by the tools.

Files are named by their path from the root, as git prints them. "Seen" are the files a clone or a commit of
the working tree would hold: the tracked ones and the untracked ones that are not ignored.

Nothing here changes the index, which is the user's (`docs/decisions/git-index.md`): the tools read it, and what
they write of it goes into directories of their own; a commit of the working tree is made in an index file of its
own (`_git_on_index`)."""

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from strom_tools.workspace.processes import run_checked, run_process
from strom_tools.workspace.repository import Repository

_IDENTITY = ["-c", "user.name=strom tools", "-c", "user.email=tools@strom.invalid"]
"""For a commit that only the tools see: the jail has no git identity."""


def _git(directory: Path, *arguments: str, stdin: str | None = None) -> str:
    """The stdout of a git command that must succeed (a `ToolError` with git's message if it does not)."""
    return run_checked(["git", *arguments], cwd=directory, stdin=stdin)


def _git_on_index(directory: Path, index: Path, *arguments: str) -> str:
    """`_git` with `index` as the index file instead of the repository's."""
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    return run_checked(["git", *_IDENTITY, *arguments], cwd=directory, env=env)


def _git_asked(directory: Path, *arguments: str) -> bool:
    """Whether a git command that answers by its exit code says yes."""
    return run_process(["git", *arguments], cwd=directory).returncode == 0


def _names(listed: str) -> list[str]:
    """The names of a `-z` listing."""
    return [name for name in listed.split("\0") if name]


def staged(repository: Repository, *pathspecs: str) -> list[str]:
    """The files in the index (also those deleted from the working tree) that match one of `pathspecs` (none:
    all)."""
    return _names(_git(repository.root, "ls-files", "-z", "--cached", "--", *pathspecs))


def seen(repository: Repository, *pathspecs: str, untracked: bool = True) -> list[str]:
    """The files of the working tree that git sees and that match one of `pathspecs` (none: all): the tracked
    ones that are not deleted, with `untracked` also those that are neither tracked nor ignored."""
    others = ["--others", "--exclude-standard"] if untracked else []
    listed = _names(_git(repository.root, "ls-files", "-z", "--cached", *others, "--", *pathspecs))
    return [name for name in listed if (repository.root / name).exists()]


def changed(repository: Repository) -> list[str]:
    """The files with uncommitted changes (staged or not) and the untracked ones that are not ignored."""
    unstaged = _git(repository.root, "ls-files", "-z", "--modified", "--others", "--exclude-standard")
    in_index = _git(repository.root, "diff", "-z", "--name-only", "--cached")
    names = {*_names(unstaged), *_names(in_index)}
    return sorted(name for name in names if (repository.root / name).exists())


def is_ignored(repository: Repository, name: str) -> bool:
    """Whether the ignore rules match `name`, tracked or not, existing or not."""
    return _git_asked(repository.root, "check-ignore", "--quiet", "--no-index", name)


def is_commit(repository: Repository, name: str) -> bool:
    """Whether `name` names a commit (a tag or a branch too; a bare tree does not)."""
    return _git_asked(repository.root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")


def commit_has(repository: Repository, commit: str, path: str) -> bool:
    return _git_asked(repository.root, "cat-file", "-e", f"{commit}:{path}")


def archive(repository: Repository, commit: str, paths: Sequence[str], tar: Path) -> None:
    """Writes the files under `paths` of a commit into the tar archive `tar`."""
    _git(repository.root, "archive", "--format=tar", f"--output={tar}", commit, "--", *paths)


def checkout_index(repository: Repository, names: Sequence[str], dest: Path) -> None:
    """Writes the staged contents of the files `names` into `dest`."""
    listed = "".join(f"{name}\0" for name in names)
    _git(repository.root, "checkout-index", "-z", "--stdin", f"--prefix={dest}/", stdin=listed)


def commit_of_working_tree(repository: Repository) -> str:
    """The hash of a new commit, child of HEAD, holding the files git sees, as they are in the working tree; the
    index and the branches stay as they are. It hangs on no ref: `git gc` prunes it after some weeks (a tag keeps
    it)."""
    with tempfile.TemporaryDirectory(prefix="strom-baseline-") as tmp:
        index = Path(tmp) / "index"
        _git_on_index(repository.root, index, "read-tree", "HEAD")
        _git_on_index(repository.root, index, "add", "--all", "--", ".")
        tree = _git_on_index(repository.root, index, "write-tree").strip()
        message = "the working tree (a baseline of strom's tools)"
        return _git_on_index(repository.root, index, "commit-tree", tree, "-p", "HEAD", "-m", message).strip()


def apply_patch(directory: Path, patch: Path) -> None:
    """Applies a patch file (`git diff` format) to the files in `directory`, which need be no repository."""
    _git(directory, "apply", str(patch))
