from collections import Counter
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from strom_tools.change_checks.line_diffs import LineDiff, diff_lines, differs, rendered, save, saved, snapshot
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository

lines = st.lists(st.sampled_from(["a", "b", "c", "d"]), max_size=12)


@given(lines)
def test_a_list_does_not_differ_from_its_permutations(before: list[str]) -> None:
    diff = diff_lines(before, list(reversed(before)))
    assert not differs(diff)
    assert diff == LineDiff([], [], len(before), len(before))


@given(lines, lines)
def test_removing_and_adding_the_difference_gives_the_current_lines(before: list[str], current: list[str]) -> None:
    diff = diff_lines(before, current)
    assert Counter(before) - Counter(diff.removed) + Counter(diff.added) == Counter(current)
    assert not Counter(diff.removed) & Counter(diff.added)
    assert differs(diff) == (Counter(before) != Counter(current))
    assert (diff.num_before, diff.num_now) == (len(before), len(current))


def test_rendered_lists_the_removed_then_the_added_lines_and_a_summary() -> None:
    diff = diff_lines(["a", "b", "b", "c"], ["a", "b", "d"])
    assert rendered(diff, "IDs", "in HEAD") == "- b\n- c\n+ d\n4 IDs in HEAD, 3 now: 2 removed, 1 added"
    assert rendered(diff_lines(["a"], ["a"]), "IDs", "saved") == "1 IDs saved, 1 now: 0 removed, 0 added"


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
