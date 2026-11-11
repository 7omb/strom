import re
import tarfile
from pathlib import Path

import pytest
from tool_helpers import commit, git, write

from strom_tools.workspace import git_files
from strom_tools.workspace.repository import Repository


@pytest.fixture
def files(repository: Repository) -> Repository:
    """A repository with a committed, a deleted, a modified, a staged, an untracked and an ignored file."""
    write(repository, ".gitignore", "ignored/\n")
    write(repository, "kept.py", "kept = 1\n")
    write(repository, "docs/deleted.md", "gone\n")
    write(repository, "docs/modified.md", "before\n")
    commit(repository)
    (repository.root / "docs/deleted.md").unlink()
    write(repository, "docs/modified.md", "after\n")
    write(repository, "staged.py", "staged = 1\n")
    git(repository, "add", "staged.py")
    write(repository, "untracked.py", "untracked = 1\n")
    write(repository, "ignored/cache.py", "cache = 1\n")
    return repository


def test_seen_are_the_tracked_files_that_exist_and_the_untracked_ones_not_ignored(files: Repository) -> None:
    assert sorted(git_files.seen(files)) == [".gitignore", "docs/modified.md", "kept.py", "staged.py", "untracked.py"]
    assert sorted(git_files.seen(files, untracked=False)) == [".gitignore", "docs/modified.md", "kept.py", "staged.py"]


def test_seen_takes_pathspecs(files: Repository) -> None:
    assert sorted(git_files.seen(files, "*.py")) == ["kept.py", "staged.py", "untracked.py"]
    assert git_files.seen(files, "docs") == ["docs/modified.md"]
    assert git_files.seen(files, "nowhere") == []


def test_staged_are_the_files_in_the_index_also_the_deleted_ones(files: Repository) -> None:
    assert sorted(git_files.staged(files, "docs", "staged.py")) == ["docs/deleted.md", "docs/modified.md", "staged.py"]


def test_changed_are_the_modified_the_staged_and_the_untracked_files(files: Repository) -> None:
    assert git_files.changed(files) == ["docs/modified.md", "staged.py", "untracked.py"]


def test_nothing_is_changed_after_a_commit(files: Repository) -> None:
    commit(files)
    assert git_files.changed(files) == []


def test_ignored_is_what_the_ignore_rules_match(files: Repository) -> None:
    assert git_files.is_ignored(files, "ignored/cache.py")
    assert git_files.is_ignored(files, "ignored/not_there.py")
    assert not git_files.is_ignored(files, "kept.py")


def test_no_function_changes_the_index() -> None:
    """The index is the user's (`docs/decisions.md`, Index): the tools read it, and write only into directories of
    their own (`checkout_index`, `apply_patch`)."""
    source = Path(git_files.__file__).read_text()
    commands = set(re.findall(r'_git(?:_asked)?\(\s*[\w.]+,\s*"([\w-]+)"', source))
    assert commands == {
        "ls-files",
        "diff",
        "check-ignore",
        "rev-parse",
        "cat-file",
        "archive",
        "checkout-index",
        "apply",
    }


def test_a_commit_is_named_by_what_git_resolves_to_one(files: Repository) -> None:
    tree = git(files, "rev-parse", "HEAD^{tree}")
    assert git_files.is_commit(files, "HEAD") and git_files.is_commit(files, "main")
    assert not git_files.is_commit(files, tree)
    assert not git_files.is_commit(files, "no-such-branch")
    assert git_files.commit_has(files, "HEAD", "docs/deleted.md") and git_files.commit_has(files, "HEAD", "docs")
    assert not git_files.commit_has(files, "HEAD", "staged.py")


def test_archive_holds_the_committed_contents(files: Repository, tmp_path: Path) -> None:
    git_files.archive(files, "HEAD", ["docs"], tmp_path / "docs.tar")
    with tarfile.open(tmp_path / "docs.tar") as tar:
        assert sorted(member.name for member in tar.getmembers() if member.isfile()) == [
            "docs/deleted.md",
            "docs/modified.md",
        ]
        modified = tar.extractfile("docs/modified.md")
        assert modified is not None and modified.read() == b"before\n"


def test_checkout_index_writes_the_staged_contents(files: Repository, tmp_path: Path) -> None:
    git(files, "add", "docs/modified.md")
    write(files, "docs/modified.md", "after the staging\n")
    git_files.checkout_index(files, ["docs/modified.md", "staged.py"], tmp_path / "out")
    assert (tmp_path / "out/docs/modified.md").read_text() == "after\n"
    assert (tmp_path / "out/staged.py").read_text() == "staged = 1\n"


def test_apply_patch_changes_files_outside_a_repository(files: Repository, tmp_path: Path) -> None:
    patch = tmp_path / "bug.patch"
    patch.write_text(git(files, "diff", "--", "docs/modified.md") + "\n")
    copy = tmp_path / "copy"
    (copy / "docs").mkdir(parents=True)
    (copy / "docs/modified.md").write_text("before\n")
    git_files.apply_patch(copy, patch)
    assert (copy / "docs/modified.md").read_text() == "after\n"
