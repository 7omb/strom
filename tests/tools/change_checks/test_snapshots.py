from pathlib import Path

import pytest

from strom_tools.change_checks.snapshots import save, saved, snapshot
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


def test_a_snapshot_is_saved_sorted_in_the_state_directory(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    file = snapshot(repository, "typing", "before")
    assert file == tmp_path / ".checks" / "typing-before.txt"
    save(file, ["b", "a", "b"])
    assert saved(repository, file) == ["a", "b", "b"]


def test_a_snapshot_never_saved_is_an_error(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    with pytest.raises(ToolError, match=r"no snapshot \.checks/typing-nope\.txt: run `save`"):
        saved(repository, snapshot(repository, "typing", "nope"))
