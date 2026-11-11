from pathlib import Path, PurePosixPath

import pytest
from tool_helpers import write, write_transcript

from strom_tools.docs_check import RuleNote
from strom_tools.hooks.hook_events import Session, SessionEnded, ToolUsed
from strom_tools.hooks.hook_results import CONTEXT_LIMIT, Note
from strom_tools.hooks.memos import recalled, remembered_at
from strom_tools.hooks.rules_loading import _loaded, _matches, _to_add, _touched, after_bash, at_end
from strom_tools.workspace.repository import Repository

TESTS_RULE = '---\npaths:\n  - "tests/**"\n  - "benchmarks/**"\n---\n\n# Tests\n\nNo sleeps.\n'
TOOLING_RULE = "---\npaths:\n  - pyproject.toml\n---\n# Tooling\n\nUse make.\n"


@pytest.fixture
def ruled(tmp_path: Path) -> Repository:
    repository = Repository(tmp_path / "repository")
    write(repository, ".claude/rules/tests.md", TESTS_RULE)
    write(repository, ".claude/rules/tooling.md", TOOLING_RULE)
    write(repository, ".claude/rules/notes.md", "# No frontmatter: no paths\n")
    write(repository, "tests/runtime/test_pools.py")
    write(repository, "pyproject.toml")
    write(repository, "docs/todo.md")
    return repository


SESSION = Session("abcd", None)


def bash(command: str, session: Session = SESSION) -> ToolUsed:
    return ToolUsed(session, "Bash", None, command)


def test_the_rules_to_add_match_a_touched_path_and_were_not_added_before() -> None:
    tests = RuleNote(Path("/r/tests.md"), ["tests/**"], "")
    tooling = RuleNote(Path("/r/tooling.md"), ["pyproject.toml"], "")
    touched = [PurePosixPath("tests/a.py"), PurePosixPath("pyproject.toml")]
    assert _to_add(touched, [tests, tooling], []) == [tests, tooling]
    assert _to_add(touched, [tests, tooling], ["tests.md"]) == [tooling]
    assert _to_add([PurePosixPath("docs/todo.md")], [tests, tooling], []) == []


def test_touched_are_the_words_of_a_command_that_name_files_of_the_repository(ruled: Repository) -> None:
    command = f"cat tests/runtime/test_pools.py | head -5; ls nope.py --color /etc/passwd {ruled.root}/pyproject.toml"
    assert _touched(ruled, command) == [PurePosixPath("tests/runtime/test_pools.py"), PurePosixPath("pyproject.toml")]
    assert _touched(ruled, "make fix FILES=docs/todo.md,pyproject.toml") == [
        PurePosixPath("docs/todo.md"),
        PurePosixPath("pyproject.toml"),
    ]
    assert _touched(ruled, "echo 'an unbalanced quote docs/todo.md") == [PurePosixPath("docs/todo.md")]


def test_a_directory_stands_for_files_in_it(ruled: Repository) -> None:
    named = _touched(ruled, "ls tests")
    assert named == [PurePosixPath("tests/x.py"), PurePosixPath("tests/x.md")]
    assert _matches(named, ["tests/**"]) and not _matches(named, ["benchmarks/**", "pyproject.toml"])
    assert _touched(ruled, f"git diff . ./ {ruled.root}; bin/ab.py HEAD .") == [], "the root names no area"


def test_a_rule_is_added_once_per_session(ruled: Repository) -> None:
    result = after_bash(ruled, bash("cat tests/runtime/test_pools.py pyproject.toml"))
    assert result == Note(
        for_claude="Contents of .claude/rules/tests.md:\n\n# Tests\n\nNo sleeps.\n\n"
        "Contents of .claude/rules/tooling.md:\n\n# Tooling\n\nUse make."
    )
    assert after_bash(ruled, bash("rg x tests pyproject.toml")) is None
    assert recalled(_loaded(ruled, SESSION)) == ["tests.md", "tooling.md"]
    other = after_bash(ruled, bash("ls tests", Session("another", None)))
    assert isinstance(other, Note) and other.for_claude is not None and "tooling.md" not in other.for_claude


def test_rules_over_the_hook_limit_are_named_and_added_by_a_later_command(ruled: Repository) -> None:
    body = "x" * (CONTEXT_LIMIT // 3)
    for name in ("a.md", "b.md", "c.md"):
        write(ruled, f".claude/rules/{name}", f'---\npaths:\n  - "docs/**"\n---\n{body}\n')
    first = after_bash(ruled, bash("cat docs/todo.md"))
    assert isinstance(first, Note) and first.for_claude is not None
    assert len(first.for_claude) <= CONTEXT_LIMIT
    assert first.for_claude.startswith("Contents of .claude/rules/a.md:")
    assert "Contents of .claude/rules/b.md:" in first.for_claude and "Contents of" not in first.for_claude[-200:]
    assert first.for_claude.endswith("not added at Claude Code's limit for a hook output: `.claude/rules/c.md`")
    assert recalled(_loaded(ruled, SESSION)) == ["a.md", "b.md"]
    assert after_bash(ruled, bash("ls docs")) == Note(for_claude=f"Contents of .claude/rules/c.md:\n\n{body}")
    assert recalled(_loaded(ruled, SESSION)) == ["a.md", "b.md", "c.md"]


def test_a_command_that_touches_no_rule_adds_nothing(ruled: Repository) -> None:
    assert after_bash(ruled, bash("git status; cat docs/todo.md")) is None
    assert after_bash(ruled, ToolUsed(SESSION, "Bash", None, None)) is None
    assert remembered_at(_loaded(ruled, SESSION)) is None


def test_a_rule_claude_code_loaded_itself_is_not_added_again(ruled: Repository, tmp_path: Path) -> None:
    rule = ruled.root / ".claude/rules/tests.md"
    loaded = {"type": "attachment", "attachment": {"type": "nested_memory", "path": str(rule)}}
    session = Session("abcd", write_transcript(tmp_path / "abcd.jsonl", [loaded]))
    result = after_bash(ruled, bash("cat tests/runtime/test_pools.py pyproject.toml", session))
    assert result == Note(for_claude="Contents of .claude/rules/tooling.md:\n\n# Tooling\n\nUse make.")


def test_the_end_of_a_session_forgets_what_was_loaded_in_it(ruled: Repository) -> None:
    after_bash(ruled, bash("ls tests"))
    assert at_end(ruled, SessionEnded(SESSION)) is None
    assert remembered_at(_loaded(ruled, SESSION)) is None
    assert at_end(ruled, SessionEnded(SESSION)) is None, "nothing was loaded: nothing to forget"
    assert isinstance(after_bash(ruled, bash("ls tests")), Note), "a new session of that id starts anew"
