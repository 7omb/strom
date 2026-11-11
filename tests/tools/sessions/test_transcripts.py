import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tool_helpers import write_transcript

from strom_tools.sessions.transcripts import (
    Author,
    ContextSummarised,
    DiagnosticsAttached,
    HookBlocked,
    Message,
    Origin,
    Said,
    StopHooksRan,
    Text,
    TitleGiven,
    ToolResult,
    ToolUse,
    _transcripts_dir,
    find,
    loaded_natively,
    minute,
    prompts,
    records,
    summaries,
    texts,
    title,
    transcripts,
)
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository

AT = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


def user(text: object, at: str = "2026-11-01T10:00:00.000Z", **more: object) -> dict[str, object]:
    return {"type": "user", "timestamp": at, "message": {"role": "user", "content": text}, **more}


def assistant(*blocks: object, at: str = "2026-11-01T10:00:05.000Z") -> dict[str, object]:
    return {"type": "assistant", "timestamp": at, "message": {"role": "assistant", "content": list(blocks)}}


def test_the_transcripts_of_a_repository_are_in_the_directory_named_after_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    repository = Repository(Path("/home/me/Projects/my_repo.x"))
    directory = tmp_path / "config" / "projects" / "-home-me-Projects-my-repo-x"
    assert _transcripts_dir(repository) == directory
    directory.mkdir(parents=True)
    for number, name in enumerate(["bbbb-2", "aaaa-1", "abcd-3"]):
        write_transcript(directory / f"{name}.jsonl", [])
        os.utime(directory / f"{name}.jsonl", (1000 + number, 1000 + number))
    assert [path.stem for path in transcripts(repository)] == ["bbbb-2", "aaaa-1", "abcd-3"], "oldest first"
    assert find(repository, "bb") == directory / "bbbb-2.jsonl"
    for prefix, count in (("a", 2), ("zz", 0)):
        with pytest.raises(ToolError, match=f"{count} sessions start with '{prefix}'"):
            find(repository, prefix)


def test_records_are_those_of_the_main_conversation_the_tools_read(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(
        '{"type": "user", "timestamp": "2026-11-01T10:00:00.000Z"}\n'
        "not json\n"
        '["a", "list"]\n'
        '{"type": "assistant", "isSidechain": true}\n'
        '{"type": "summary"}\n'
        '{"type": "system", "subtype": "compact_boundary", "timestamp": "no time"}\n'
        '{"type": "assistant", "timestamp": "2026-11-01T11:00:00.000Z"}\n'
    )
    later = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
    assert list(records(path)) == [
        Message(AT, Author.USER, Origin.CONVERSATION, []),
        ContextSummarised(None),
        Message(later, Author.ASSISTANT, Origin.CONVERSATION, []),
    ]
    since = datetime(2026, 11, 1, 10, 30, tzinfo=UTC)
    assert [type(record) for record in records(path, since)] == [ContextSummarised, Message], "one without a time stays"


def test_a_message_holds_its_text_tool_use_and_tool_result_blocks(tmp_path: Path) -> None:
    edit = {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/a.py", "old_string": "x"}}
    bash = {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "make", "timeout": 5}}
    result = {
        "type": "tool_result",
        "tool_use_id": "t2",
        "content": [{"type": "text", "text": "two"}, {"text": "parts"}, 3],
    }
    path = write_transcript(
        tmp_path / "session.jsonl",
        [
            user("a prompt"),
            assistant({"type": "text", "text": "an answer"}, "stray", {"type": "thinking"}, edit, bash),
            user([result, {"type": "tool_result", "tool_use_id": "t1", "content": "failed", "is_error": True}]),
            user("injected", isMeta=True),
            user("the context so far", isCompactSummary=True),
        ],
    )
    assert [
        (record.author, record.origin, record.blocks) for record in records(path) if isinstance(record, Message)
    ] == [
        (Author.USER, Origin.CONVERSATION, [Text("a prompt")]),
        (
            Author.ASSISTANT,
            Origin.CONVERSATION,
            [
                Text("an answer"),
                ToolUse("t1", "Edit", None, "/a.py", "{'file_path': '/a.py', 'old_string': 'x'}"),
                ToolUse("t2", "Bash", "make", None, "{'command': 'make', 'timeout': 5}"),
            ],
        ),
        (Author.USER, Origin.CONVERSATION, [ToolResult("t2", "two parts", False), ToolResult("t1", "failed", True)]),
        (Author.USER, Origin.INJECTED, [Text("injected")]),
        (Author.USER, Origin.SUMMARY, [Text("the context so far")]),
    ]


def test_the_other_records_are_hook_blocks_diagnostics_summaries_stops_and_titles(tmp_path: Path) -> None:
    at = "2026-11-01T10:00:00.000Z"
    blocked = {"type": "hook_blocking_error", "toolUseID": "t1", "hookName": "Stop", "blockingError": "no"}
    nested = {**blocked, "blockingError": {"blockingError": "nested"}}
    path = write_transcript(
        tmp_path / "session.jsonl",
        [
            {"type": "attachment", "timestamp": at, "attachment": blocked},
            {"type": "attachment", "timestamp": at, "attachment": nested},
            {"type": "attachment", "timestamp": at, "attachment": {"type": "diagnostics", "files": ["a.py"]}},
            {"type": "attachment", "timestamp": at, "attachment": {"type": "nested_memory", "path": "x"}},
            {"type": "system", "subtype": "compact_boundary", "timestamp": at},
            {"type": "system", "subtype": "stop_hook_summary", "timestamp": at, "hookErrors": ["ruff"]},
            {"type": "system", "subtype": "stop_hook_summary", "timestamp": at},
            {"type": "system", "subtype": "other", "timestamp": at},
            {"type": "ai-title", "aiTitle": "A title"},
        ],
    )
    assert list(records(path)) == [
        HookBlocked(AT, "t1", "Stop", "no"),
        HookBlocked(AT, "t1", "Stop", "nested"),
        DiagnosticsAttached(AT, '["a.py"]'),
        ContextSummarised(AT),
        StopHooksRan(AT, failed=True),
        StopHooksRan(AT, failed=False),
        TitleGiven(None, "A title"),
    ]


def test_prompts_are_what_the_user_typed(tmp_path: Path) -> None:
    second_at = "2026-11-01T12:34:56.000Z"
    path = write_transcript(
        tmp_path / "session.jsonl",
        [
            user("the first prompt"),
            user("injected", isMeta=True),
            user("a summary of the context", isCompactSummary=True),
            user("<local-command-stdout>output</local-command-stdout>"),
            user("<command-name>/clear</command-name>"),
            user([{"type": "tool_result", "content": "a result"}]),
            assistant({"type": "text", "text": "an answer"}),
            user([{"type": "text", "text": "the second prompt"}], at=second_at),
        ],
    )
    second = datetime.fromisoformat(second_at)
    expected = [Said(AT, Author.USER, "the first prompt"), Said(second, Author.USER, "the second prompt")]
    assert list(prompts(path)) == expected
    assert list(texts(path, everything=False)) == expected
    everything = [(said.author, said.text) for said in texts(path, everything=True)]
    assert (Author.ASSISTANT, "an answer") in everything and (Author.USER, "a summary of the context") in everything
    assert (Author.USER, "injected") not in everything


def test_a_time_is_shown_to_the_minute() -> None:
    assert minute(datetime.fromisoformat("2026-11-01T12:34:56.000Z")) == "2026-11-01T12:34"
    assert minute(None) == ""


def test_the_title_is_the_last_one_given(tmp_path: Path) -> None:
    path = write_transcript(
        tmp_path / "session.jsonl",
        [
            {"type": "ai-title", "aiTitle": "First"},
            user("a prompt"),
            {"type": "ai-title", "title": "Second"},
            {"type": "ai-title"},
        ],
    )
    assert title(path) == "Second"
    assert title(write_transcript(tmp_path / "untitled.jsonl", [user("a prompt")])) == ""


def test_summaries_count_in_all_and_since_a_turn_ended(tmp_path: Path) -> None:
    summary = {"type": "system", "subtype": "compact_boundary"}
    stop = {"type": "system", "subtype": "stop_hook_summary"}
    blocked_stop = {**stop, "hookErrors": ["ruff check"]}
    path = tmp_path / "session.jsonl"
    assert summaries(write_transcript(path, [user("a prompt"), stop])) == (0, 0)
    assert summaries(write_transcript(path, [summary, stop, summary])) == (2, 1)
    assert summaries(write_transcript(path, [summary, summary, blocked_stop])) == (2, 2), "the turn has not ended"
    assert summaries(write_transcript(path, [summary, blocked_stop, stop])) == (1, 0)


def test_a_rule_is_loaded_natively_if_an_attachment_of_the_transcript_names_it(tmp_path: Path) -> None:
    rule = tmp_path / ".claude/rules/tests.md"
    attachment = {"type": "attachment", "attachment": {"type": "nested_memory", "path": str(rule)}}
    path = write_transcript(tmp_path / "session.jsonl", [user(f"read {rule}"), attachment])
    assert loaded_natively(path, rule)
    assert not loaded_natively(path, tmp_path / ".claude/rules/docs.md")
    assert not loaded_natively(write_transcript(path, [user(f"read {rule}")]), rule), "a mention is no load"
    assert not loaded_natively(tmp_path / "no_such.jsonl", rule)
