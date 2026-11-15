from pathlib import Path, PurePosixPath

import pytest
from tool_helpers import imported_after, write, write_transcript

from strom_tools.docs_check.rule_notes import RuleNote
from strom_tools.hooks.hook_events import Session, SessionEnded, SessionStarted, ToolUsed
from strom_tools.hooks.hook_results import CONTEXT_LIMIT, Note
from strom_tools.hooks.memos import recalled, remembered_at
from strom_tools.hooks.rules_loading import _loaded, _matches, _to_add, _touched, after_bash, at_end, at_start
from strom_tools.sessions.transcripts import subagent_transcript
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


def bash(command: str, session: Session = SESSION, agent_id: str | None = None) -> ToolUsed:
    return ToolUsed(session, "Bash", None, command, agent_id)


def test_the_handlers_import_no_git() -> None:
    """They run after every Bash call; reading the rules files needs no git, and `git_files` with what it imports
    (`subprocess`, `tempfile`) took about half the time of importing this module."""
    assert "strom_tools.workspace.git_files" not in imported_after("import strom_tools.hooks.rules_loading")


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
    assert _touched(ruled, 'M="python tests/runtime/test_pools.py -q"; $M; echo "x pyproject.toml"') == [
        PurePosixPath("tests/runtime/test_pools.py")
    ], "the value of an assignment is words, another quoted text is one"


def test_a_word_after_cd_is_read_from_that_directory(ruled: Repository, tmp_path: Path) -> None:
    (tmp_path / "elsewhere").mkdir()
    assert _touched(ruled, f"cd {tmp_path}/elsewhere && ls tests pyproject.toml {ruled.root}/docs/todo.md") == [
        PurePosixPath("docs/todo.md")
    ]
    assert _touched(ruled, "cd tests/runtime; cat test_pools.py; cd ../..; cat pyproject.toml") == [
        PurePosixPath("tests/runtime/x.py"),
        PurePosixPath("tests/runtime/x.md"),
        PurePosixPath("tests/runtime/test_pools.py"),
        PurePosixPath("pyproject.toml"),
    ]


def test_claude_code_loads_the_rule_after_a_command_that_only_views_one_file(ruled: Repository) -> None:
    for view in ("cat", "head -5", "tail -n 3", "sed -n 1,5p", "grep -n sleep"):
        assert after_bash(ruled, bash(f"{view} tests/runtime/test_pools.py")) is None, view
    assert remembered_at(_loaded(ruled, SESSION)) is None, "not added by the hook"
    for command in (
        "cat tests/runtime/test_pools.py | head",
        "cat tests/runtime/test_pools.py > /dev/null",
        "cd tests && cat runtime/test_pools.py",
        "cat tests/runtime/test_pools.py pyproject.toml",
        "sed s/a/b/ tests/runtime/test_pools.py",
        "grep -rn sleep tests",
        "wc -l tests/runtime/test_pools.py",
    ):
        assert isinstance(after_bash(ruled, bash(command, Session(command, None))), Note), command


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
    first = after_bash(ruled, bash("wc -l docs/todo.md"))
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
    assert after_bash(ruled, ToolUsed(SESSION, "Bash", None, None, None)) is None
    assert remembered_at(_loaded(ruled, SESSION)) is None


def test_a_rule_claude_code_loaded_itself_is_not_added_again(ruled: Repository, tmp_path: Path) -> None:
    rule = ruled.root / ".claude/rules/tests.md"
    loaded = {"type": "attachment", "attachment": {"type": "nested_memory", "path": str(rule)}}
    session = Session("abcd", write_transcript(tmp_path / "abcd.jsonl", [loaded]))
    result = after_bash(ruled, bash("cat tests/runtime/test_pools.py pyproject.toml", session))
    assert result == Note(for_claude="Contents of .claude/rules/tooling.md:\n\n# Tooling\n\nUse make.")


def test_a_subagent_gets_a_rule_once_in_its_own_context(ruled: Repository) -> None:
    assert isinstance(after_bash(ruled, bash("ls tests")), Note)
    assert isinstance(after_bash(ruled, bash("ls tests", agent_id="a1")), Note), "the session has it, its subagent not"
    assert after_bash(ruled, bash("ls tests", agent_id="a1")) is None
    assert isinstance(after_bash(ruled, bash("wc pyproject.toml", agent_id="a1")), Note)
    assert isinstance(after_bash(ruled, bash("wc pyproject.toml", agent_id="a2")), Note), "each subagent has its own"
    assert isinstance(after_bash(ruled, bash("wc pyproject.toml")), Note), "added in the subagents only"
    assert recalled(_loaded(ruled, SESSION, "a1")) == ["tests.md", "tooling.md"]
    assert recalled(_loaded(ruled, SESSION, "a2")) == ["tooling.md"]


def test_a_rule_claude_code_loaded_in_a_subagent_is_not_added_to_that_subagent(
    ruled: Repository, tmp_path: Path
) -> None:
    rule = ruled.root / ".claude/rules/tests.md"
    loaded = {"type": "attachment", "isSidechain": True, "attachment": {"type": "nested_memory", "path": str(rule)}}
    transcript = write_transcript(tmp_path / "abcd.jsonl", [])
    of_subagent = subagent_transcript(transcript, "a1")
    of_subagent.parent.mkdir(parents=True)
    write_transcript(of_subagent, [loaded])
    session = Session("abcd", transcript)
    assert after_bash(ruled, bash("ls tests", session, "a1")) is None
    assert isinstance(after_bash(ruled, bash("ls tests", session, "a2")), Note)
    assert isinstance(after_bash(ruled, bash("ls tests", session)), Note)


def test_a_summary_of_the_context_forgets_what_was_added_before_it(ruled: Repository) -> None:
    assert isinstance(after_bash(ruled, bash("ls tests")), Note)
    assert isinstance(after_bash(ruled, bash("ls tests", agent_id="a1")), Note)
    assert at_start(ruled, SessionStarted(SESSION, "resume")) is None
    assert after_bash(ruled, bash("ls tests")) is None, "a resumed session still has it"
    assert at_start(ruled, SessionStarted(SESSION, "compact")) is None
    assert isinstance(after_bash(ruled, bash("ls tests")), Note), "the summary dropped it"
    assert after_bash(ruled, bash("ls tests", agent_id="a1")) is None, "a subagent's context was not summarised"


def test_the_end_of_a_session_forgets_what_was_loaded_in_it(ruled: Repository) -> None:
    after_bash(ruled, bash("ls tests"))
    after_bash(ruled, bash("ls tests", agent_id="a1"))
    assert at_end(ruled, SessionEnded(SESSION)) is None
    assert remembered_at(_loaded(ruled, SESSION)) is None and remembered_at(_loaded(ruled, SESSION, "a1")) is None
    assert at_end(ruled, SessionEnded(SESSION)) is None, "nothing was loaded: nothing to forget"
    assert isinstance(after_bash(ruled, bash("ls tests")), Note), "a new session of that id starts anew"
    assert isinstance(after_bash(ruled, bash("ls tests", agent_id="a1")), Note)
