"""What git knows of the repository's files: every call of git by the tools.

Files are named by their path from the root, as git prints them. "Seen" are the files a clone or a commit of
the working tree would hold: the tracked ones and the untracked ones that are not ignored.

Nothing here changes the index, which is the user's (`docs/decisions.md`, Index): the tools read it, and what
they write of it goes into directories of their own."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from strom_tools.workspace.repository import Repository


def _git(
    directory: Path, *arguments: str, stdin: bytes | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *arguments], cwd=directory, input=stdin, capture_output=True, check=check)


def _names(listed: bytes) -> list[str]:
    """The names of a `-z` listing."""
    return [name for name in listed.decode().split("\0") if name]


def staged(repository: Repository, *pathspecs: str) -> list[str]:
    """The files in the index (also those deleted from the working tree) that match one of `pathspecs` (none:
    all)."""
    return _names(_git(repository.root, "ls-files", "-z", "--cached", "--", *pathspecs).stdout)


def seen(repository: Repository, *pathspecs: str, untracked: bool = True) -> list[str]:
    """The files of the working tree that git sees and that match one of `pathspecs` (none: all): the tracked
    ones that are not deleted, with `untracked` also those that are neither tracked nor ignored."""
    others = ["--others", "--exclude-standard"] if untracked else []
    listed = _names(_git(repository.root, "ls-files", "-z", "--cached", *others, "--", *pathspecs).stdout)
    return [name for name in listed if (repository.root / name).exists()]


def changed(repository: Repository) -> list[str]:
    """The files with uncommitted changes (staged or not) and the untracked ones that are not ignored."""
    unstaged = _git(repository.root, "ls-files", "-z", "--modified", "--others", "--exclude-standard").stdout
    in_index = _git(repository.root, "diff", "-z", "--name-only", "--cached").stdout
    names = {*_names(unstaged), *_names(in_index)}
    return sorted(name for name in names if (repository.root / name).exists())


def is_ignored(repository: Repository, name: str) -> bool:
    """Whether the ignore rules match `name`, tracked or not, existing or not."""
    return _git(repository.root, "check-ignore", "--quiet", "--no-index", name, check=False).returncode == 0


def is_commit(repository: Repository, name: str) -> bool:
    """Whether `name` names a commit (a tag or a branch too; a bare tree does not)."""
    verified = _git(repository.root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}", check=False)
    return verified.returncode == 0


def commit_has(repository: Repository, commit: str, path: str) -> bool:
    return _git(repository.root, "cat-file", "-e", f"{commit}:{path}", check=False).returncode == 0


def archive(repository: Repository, commit: str, paths: Sequence[str]) -> bytes:
    """The files under `paths` of a commit, as a tar archive."""
    return _git(repository.root, "archive", "--format=tar", commit, "--", *paths).stdout


def checkout_index(repository: Repository, names: Sequence[str], dest: Path) -> None:
    """Writes the staged contents of the files `names` into `dest`."""
    listed = "".join(f"{name}\0" for name in names).encode()
    _git(repository.root, "checkout-index", "-z", "--stdin", f"--prefix={dest}/", stdin=listed)


def apply_patch(directory: Path, patch: Path) -> None:
    """Applies a patch file (`git diff` format) to the files in `directory`, which need be no repository."""
    _git(directory, "apply", str(patch))
