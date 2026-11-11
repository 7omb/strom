from pathlib import Path

import pytest
from tool_helpers import write

from strom_tools.example_scripts import _TIMEOUTS, OK, _dependencies, check_types, examples, lock, run
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository

HEADER = "\n".join(  # line by line: a `# /// script` line of its own would make this file a script for the checkers
    [
        "# /// script",
        '# requires-python = ">=3.14"',
        '# dependencies = ["strom", "sqlalchemy>=2"]',
        "#",
        "# [tool.uv.sources]",
        '# strom = { path = "..", editable = true }',
        "# ///",
        'print("an example")',
        "",
    ]
)


def test_the_dependencies_are_those_of_the_script_header(tmp_path: Path) -> None:
    (tmp_path / "simple.py").write_text(HEADER)
    assert _dependencies(tmp_path / "simple.py") == ["strom", "sqlalchemy>=2"]
    (tmp_path / "bare.py").write_text('# /// script\n# requires-python = ">=3.14"\n# ///\n')
    assert _dependencies(tmp_path / "bare.py") == []


def test_an_example_without_a_script_header_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "plain.py").write_text('print("no header")\n')
    with pytest.raises(ToolError, match="plain.py: no `# /// script` header"):
        _dependencies(tmp_path / "plain.py")


def test_the_examples_are_the_scripts_without_an_underscore(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    for name in ("examples/simple.py", "examples/rows.py", "examples/_shared.py", "examples/simple.py.lock"):
        write(repository, name)
    directory = tmp_path / "examples"
    assert examples(repository, []) == [directory / "rows.py", directory / "simple.py"]
    assert examples(repository, ["simple", "rows.py"]) == [directory / "simple.py", directory / "rows.py"]
    with pytest.raises(ToolError, match=r"unknown examples: nope.py, _shared.py \(known: rows.py, simple.py\)"):
        examples(repository, ["nope", "_shared"])


def script(*body: str) -> str:
    """A uv script without dependencies (so that its environment needs no network), with the lines `body`."""
    return "\n".join(["# /// script", '# requires-python = ">=3.14"', "# dependencies = []", "# ///", *body, ""])


@pytest.fixture
def scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repository:
    """A repository for examples, whose environments uv keeps in a cache of this test (not in the user's, where
    each run of the tests would leave new ones)."""
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    repository = Repository(tmp_path / "repository")
    repository.root.mkdir()
    return repository


def test_an_example_runs_in_its_own_environment_and_reports_how_it_ended(scripts: Repository) -> None:
    good = write(scripts, "examples/good.py", script("import os", "print(os.getcwd())"))
    bad = write(scripts, "examples/bad.py", script("import sys", 'sys.exit("FAILED scores: expected 40, got 38")'))
    for example in (good, bad):
        lock(example)
    outcome, stdout, stderr = run(good)
    assert (outcome, stderr) == (OK, "")
    assert Path(stdout.strip()).name.startswith("tmp") and scripts.root not in Path(stdout.strip()).parents
    assert run(bad) == ("exit code 1", "", "FAILED scores: expected 40, got 38\n")


def test_an_example_without_a_current_lock_does_not_run(scripts: Repository) -> None:
    example = write(scripts, "examples/unlocked.py", script('raise SystemExit("it ran")'))
    assert run(example) == ("stale lock unlocked.py.lock (update: python bin/run_examples.py --lock)", "", "")
    assert check_types(scripts, example)[0].startswith("stale lock unlocked.py.lock")
    lock(example)
    assert run(example)[0] == "exit code 1"
    example.write_text(script('raise SystemExit("it ran")').replace(">=3.14", ">=3.13"))
    assert run(example)[0].startswith("stale lock"), "the header changed since the lock"


def test_an_example_that_takes_too_long_is_killed(scripts: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """The example sleeps for a minute and holds the output pipes: `run` returns after its timeout only if the
    whole group was killed. Two seconds are enough for uv to make the environment on an idle machine; on a busy
    one the example may not have started yet, which is a timeout all the same."""
    example = write(
        scripts, "examples/slow.py", script("import time", 'print("started", flush=True)', "time.sleep(60)")
    )
    lock(example)
    monkeypatch.setitem(_TIMEOUTS, "slow.py", 2.0)
    outcome, stdout, _ = run(example)
    assert outcome == "timeout after 2 s"
    assert stdout in ("started\n", "")


def test_an_example_is_type_checked_by_the_three_checkers_in_its_environment(scripts: Repository) -> None:
    typed = write(scripts, "examples/typed.py", script("count: int = 1", "print(count)"))
    wrong = write(scripts, "examples/wrong.py", script('count: int = "one"', "print(count)"))
    for example in (typed, wrong):
        lock(example)
    assert check_types(scripts, typed) == (OK, "", "")
    outcome, output, _ = check_types(scripts, wrong)
    assert outcome == "type errors (mypy, pyright, ty)"
    assert [line for line in output.splitlines() if line.startswith("--- ")] == ["--- mypy", "--- pyright", "--- ty"]
    assert output.count("wrong.py") >= 3
