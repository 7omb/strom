import pytest
from tool_helpers import commit, run_command, write

from strom_tools.commands import outline
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


def test_a_directory_stands_for_its_python_files_and_a_broken_one_is_named(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repository, ".gitignore", "ignored/\n")
    write(repository, "src/strom/_parts/shards.py", "LIMIT = 3\n")
    write(repository, "src/strom/_parts/deep/more.py", "def more() -> None: ...\n")
    write(repository, "src/strom/_parts/broken.py", "def broken(:\n")
    write(repository, "src/strom/_parts/ignored/cache.py", "X = 1\n")
    commit(repository)
    monkeypatch.chdir(repository.root)
    assert run_command(outline, ["src/strom/_parts"], repository, monkeypatch) == 0
    assert capsys.readouterr().out.splitlines() == [
        "src/strom/_parts/broken.py",
        "    (does not parse: invalid syntax, line 1)",
        "src/strom/_parts/deep/more.py",
        "    1  def more() -> None",
        "src/strom/_parts/shards.py",
        "    1  LIMIT = …",
    ]
    with pytest.raises(ToolError, match=r"nowhere\.py: no such file or directory"):
        run_command(outline, ["nowhere.py"], repository, monkeypatch)
