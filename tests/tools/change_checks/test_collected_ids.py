from pathlib import Path

import pytest

from strom_tools.change_checks.collected_ids import collected
from strom_tools.tool_error import ToolError

TESTS = """\
import pytest


def test_one() -> None: ...


@pytest.mark.parametrize("n", [1, 2])
def test_many(n: int) -> None: ...
"""


def test_collected_are_the_ids_of_the_selected_tests(tmp_path: Path) -> None:
    (tmp_path / "test_some.py").write_text(TESTS)
    assert collected([], tmp_path) == [
        "test_some.py::test_one",
        "test_some.py::test_many[1]",
        "test_some.py::test_many[2]",
    ]
    assert collected(["-k", "one"], tmp_path) == ["test_some.py::test_one"]


def test_a_collection_error_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "test_broken.py").write_text("def test_broken(:\n")
    with pytest.raises(ToolError, match=r"collection failed \(exit code 2\)"):
        collected([], tmp_path)
