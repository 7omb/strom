import pytest
from tool_helpers import commit, git, make_calls, run_command, with_makefile, write

from strom_tools.commands import rename
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


@pytest.fixture
def code(repository: Repository) -> Repository:
    with_makefile(repository)
    write(repository, "src/strom/__init__.py", "from strom._parts import shards\n")
    write(repository, "src/strom/_parts/shards.py", "def fetch(load: int) -> int:\n    return load  # fetch it\n")
    write(repository, "tests/test_shards.py", "from strom._parts.shards import fetch\n")
    write(repository, "docs/notes.md", "Call `fetch` of `src/strom/_parts/shards.py`.\n")
    commit(repository)
    return repository


def test_a_dry_run_lists_the_hits_and_changes_nothing(
    code: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(rename, ["fetch", "retrieve"], code, monkeypatch) == 0
    assert capsys.readouterr().out.splitlines() == [
        "code       src/strom/_parts/shards.py:1:  def fetch(load: int) -> int:",
        "mention    src/strom/_parts/shards.py:2:  return load  # fetch it",
        "code       tests/test_shards.py:1:  from strom._parts.shards import fetch",
        "mention    docs/notes.md:1:  Call `fetch` of `src/strom/_parts/shards.py`.",
        "2 code, 0 collision, 2 mention",
    ]
    assert git(code, "status", "--short") == ""


def test_a_write_renames_the_code_and_on_request_the_mentions(
    code: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(rename, ["fetch", "retrieve", "--write"], code, monkeypatch) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "renamed in 2 files"
    shards = code.root / "src/strom/_parts/shards.py"
    assert shards.read_text() == "def retrieve(load: int) -> int:\n    return load  # fetch it\n"
    assert "import retrieve" in (code.root / "tests/test_shards.py").read_text()
    assert [call.split(" ARGS=")[1] for call in make_calls(code)] == [
        "--select I",
        "--quiet --select E501 --output-format concise",
    ], "the imports of the changed files are sorted, their long lines listed"
    # the name is taken by now: the mentions alone need `--force`
    assert run_command(rename, ["fetch", "retrieve", "--write", "--mentions", "--force"], code, monkeypatch) == 0
    assert shards.read_text().endswith("# retrieve it\n")
    assert (code.root / "docs/notes.md").read_text().startswith("Call `retrieve` of")


def test_a_write_refuses_collisions_unless_forced(code: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ToolError, match="collisions: rename those names first, or pass --force"):
        run_command(rename, ["fetch", "load", "--write"], code, monkeypatch)
    assert git(code, "status", "--short") == ""
    assert run_command(rename, ["fetch", "load", "--write", "--force"], code, monkeypatch) == 0
    assert (code.root / "src/strom/_parts/shards.py").read_text().startswith("def load(load: int)")


def test_a_file_moves_with_what_cites_it(
    code: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    old, new = str(code.root / "src/strom/_parts/shards.py"), str(code.root / "src/strom/_other/shards.py")
    assert run_command(rename, [old, new], code, monkeypatch) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "1 path, 2 module, 0 review"
    assert run_command(rename, [old, new, "--write"], code, monkeypatch) == 0
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "renamed in 3 files, moved to src/strom/_other/shards.py",
        "not staged: `git add src/strom/_parts/shards.py src/strom/_other/shards.py`",
    ]
    assert (code.root / "src/strom/__init__.py").read_text() == "from strom._other import shards\n"
    assert (code.root / "tests/test_shards.py").read_text() == "from strom._other.shards import fetch\n"
    assert (code.root / "docs/notes.md").read_text() == "Call `fetch` of `src/strom/_other/shards.py`.\n"
    changed = git(code, "status", "--short", "--untracked-files=all").splitlines()
    assert " D src/strom/_parts/shards.py" in changed and "?? src/strom/_other/shards.py" in changed
    assert git(code, "diff", "--cached", "--name-only") == "", "the index is the user's: nothing is staged"


def test_what_is_neither_two_identifiers_nor_a_move_is_an_error(
    code: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ToolError, match="OLD and NEW must be identifiers, or a file of the repository"):
        run_command(rename, ["no/such.py", "other.py"], code, monkeypatch)
