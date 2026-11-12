from pathlib import Path

import pytest
from tool_helpers import write

from strom_tools.example_scripts import (
    _TIMEOUTS,
    Failed,
    Passed,
    StaleLock,
    TimedOut,
    TypeErrors,
    _require_header,
    check_types,
    described,
    examples,
    lock,
    run,
    shown_output,
)
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository

# Line by line (FLY002): a `# /// script` line of its own would make this file a script for the checkers.
HEADER = "\n".join(  # noqa: FLY002
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


def test_an_example_without_a_script_header_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "simple.py").write_text(HEADER)
    _require_header(tmp_path / "simple.py")
    (tmp_path / "bare.py").write_text('# /// script\n# requires-python = ">=3.14"\n# ///\n')
    _require_header(tmp_path / "bare.py")
    (tmp_path / "plain.py").write_text('print("no header")\n')
    with pytest.raises(ToolError, match=r"plain\.py: no `# /// script` header"):
        _require_header(tmp_path / "plain.py")
    (tmp_path / "unclosed.py").write_text(HEADER.replace("# ///\n", ""))
    with pytest.raises(ToolError, match=r"unclosed\.py: no `# /// script` header"):
        _require_header(tmp_path / "unclosed.py")


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
    passed = run(good)
    assert isinstance(passed, Passed) and passed.stderr == ""
    cwd = Path(passed.stdout.strip())
    assert cwd.name.startswith("tmp") and scripts.root not in cwd.parents
    assert run(bad) == Failed(1, "", "FAILED scores: expected 40, got 38\n")


def test_an_example_without_a_current_lock_does_not_run(scripts: Repository) -> None:
    example = write(scripts, "examples/unlocked.py", script('raise SystemExit("it ran")'))
    assert run(example) == StaleLock("unlocked.py.lock")
    assert check_types(scripts, example) == StaleLock("unlocked.py.lock")
    lock(example)
    assert run(example) == Failed(1, "", "it ran\n")
    example.write_text(script('raise SystemExit("it ran")').replace(">=3.14", ">=3.13"))
    assert run(example) == StaleLock("unlocked.py.lock"), "the header changed since the lock"


def test_an_outcome_is_described_in_a_few_words_and_shows_the_output() -> None:
    assert [
        described(outcome)
        for outcome in (
            Passed(),
            StaleLock("a.py.lock"),
            Failed(1, "", ""),
            TimedOut(2.0, "", ""),
            TypeErrors(("mypy", "ty"), ""),
        )
    ] == [
        "ok",
        "stale lock a.py.lock (update: python bin/run_examples.py --lock)",
        "exit code 1",
        "timeout after 2 s",
        "type errors (mypy, ty)",
    ]
    assert shown_output(Failed(1, "out\n", "err\n")) == "--- stdout\nout\n--- stderr\nerr\n"
    assert shown_output(TypeErrors(("ty",), "--- ty\n")) == "--- stdout\n--- ty\n--- stderr\n"
    assert shown_output(StaleLock("a.py.lock")) == "--- stdout\n--- stderr\n"


def test_an_example_that_takes_too_long_is_killed(scripts: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """The example sleeps for a minute and holds the output pipes: `run` returns after its timeout only if the
    whole group was killed. Two seconds are enough for uv to make the environment on an idle machine; on a busy
    one the example may not have started yet, which is a timeout all the same."""
    example = write(
        scripts, "examples/slow.py", script("import time", 'print("started", flush=True)', "time.sleep(60)")
    )
    lock(example)
    monkeypatch.setitem(_TIMEOUTS, "slow.py", 2.0)
    outcome = run(example)
    assert isinstance(outcome, TimedOut) and outcome.timeout == 2.0
    assert outcome.stdout in ("started\n", "")


def test_an_example_is_type_checked_by_the_three_checkers_in_its_environment(scripts: Repository) -> None:
    typed = write(scripts, "examples/typed.py", script("count: int = 1", "print(count)"))
    wrong = write(scripts, "examples/wrong.py", script('count: int = "one"', "print(count)"))
    for example in (typed, wrong):
        lock(example)
    assert check_types(scripts, typed) == Passed()
    outcome = check_types(scripts, wrong)
    assert isinstance(outcome, TypeErrors) and outcome.checkers == ("mypy", "pyright", "ty")
    headers = [line for line in outcome.output.splitlines() if line.startswith("--- ")]
    assert headers == ["--- mypy", "--- pyright", "--- ty"]
    assert outcome.output.count("wrong.py") >= 3
