import os
from pathlib import Path

import pytest
from tool_helpers import run_command, write_transcript

from strom_tools.commands import sessions
from strom_tools.sessions.friction import RetroLogged, _logged
from strom_tools.sessions.transcripts import _transcripts_dir
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository

PAST, FUTURE = "2020-01-01T10:00:00.000Z", "2999-01-01T10:00:00.000Z"


def prompt(text: str, at: str = PAST) -> dict[str, object]:
    return {"type": "user", "timestamp": at, "message": {"content": text}}


def failed_call(command: str, at: str = PAST) -> list[dict[str, object]]:
    use = {"type": "tool_use", "id": command, "name": "Bash", "input": {"command": command}}
    result = {"type": "tool_result", "tool_use_id": command, "content": "Exit code 2", "is_error": True}
    return [
        {"type": "assistant", "timestamp": at, "message": {"content": [use]}},
        {"type": "user", "timestamp": at, "message": {"content": [result]}},
    ]


@pytest.fixture
def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repository:
    """A repository with the transcripts of two sessions, `aaaa1111` the older one."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    repository = Repository(tmp_path / "repository")
    repository.root.mkdir()
    directory = _transcripts_dir(repository)
    directory.mkdir(parents=True)
    title = {"type": "ai-title", "aiTitle": "Pools"}
    older = [prompt("Fix the pools"), title, *failed_call("make test"), prompt("Again, please")]
    newer = [prompt("Rename it"), *failed_call("make lint"), *failed_call("make type", FUTURE)]
    write_transcript(directory / "aaaa1111-0000.jsonl", older)
    write_transcript(directory / "bbbb2222-0000.jsonl", newer)
    os.utime(directory / "aaaa1111-0000.jsonl", (1000, 1000))
    return repository


def out(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_list_shows_a_line_per_session(
    recorded: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(sessions, ["list"], recorded, monkeypatch) == 0
    assert [line.split() for line in out(capsys)] == [
        ["aaaa1111", "2020-01-01T10:00", "0", "KB", "2", "prompts", "Pools"],
        ["bbbb2222", "2020-01-01T10:00", "0", "KB", "1", "prompts"],
    ]
    run_command(sessions, ["list", "-n", "1"], recorded, monkeypatch)
    assert [line.split()[0] for line in out(capsys)] == ["bbbb2222"]


def test_prompts_shows_what_the_user_typed_in_one_session(
    recorded: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(sessions, ["prompts", "aaaa"], recorded, monkeypatch) == 0
    assert out(capsys) == ["[2020-01-01T10:00] Fix the pools", "", "[2020-01-01T10:00] Again, please", ""]
    with pytest.raises(ToolError, match="0 sessions start with 'cccc'"):
        run_command(sessions, ["prompts", "cccc"], recorded, monkeypatch)


def test_search_finds_a_term_in_the_prompts_of_all_sessions(
    recorded: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(sessions, ["search", "the POOLS|rename"], recorded, monkeypatch) == 0
    assert out(capsys) == [
        "aaaa1111 2020-01-01T10:00 USER: …Fix the pools…",
        "bbbb2222 2020-01-01T10:00 USER: …Rename it…",
    ]
    run_command(sessions, ["search", "pools", "-n", "1", "--all"], recorded, monkeypatch)
    assert out(capsys) == []


def test_friction_counts_per_session_and_lists_details_and_commands(
    recorded: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(sessions, ["friction"], recorded, monkeypatch) == 0
    table = [line.split() for line in out(capsys)]
    assert table[0] == ["session", "hook_blocks", "tool_errors", "rejected", "interrupts", "diagnostics"]
    assert table[1:] == [["aaaa1111", "0", "1", "0", "0", "0"], ["bbbb2222", "0", "2", "0", "0", "0"]]
    run_command(sessions, ["friction", "bbbb", "--details", "--commands"], recorded, monkeypatch)
    shown = out(capsys)
    assert shown[3:5] == ["bbbb2222 2020-01-01T10:00 tool_errors: Bash: make lint", "    Exit code 2"]
    assert shown[-3:] == ["most frequent Bash commands (first two words):", "    1  make lint", "    1  make type"]


def test_friction_since_a_retrospective_counts_what_came_after_it(
    recorded: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(sessions, ["mark-retro"], recorded, monkeypatch) == 0
    assert [type(line) for line in _logged(recorded)] == [RetroLogged]
    run_command(sessions, ["friction", "--since-retro"], recorded, monkeypatch)
    shown = out(capsys)
    assert shown[0].startswith("since the retrospective of ")
    assert [line.split() for line in shown[2:]] == [["bbbb2222", "0", "1", "0", "0", "0"]], "the older one ended before"
