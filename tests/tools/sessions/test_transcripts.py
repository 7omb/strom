import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tool_helpers import write_transcript

from strom_tools.sessions.transcripts import (
    _transcripts_dir,
    contents,
    find,
    loaded_natively,
    prompts,
    records,
    summaries,
    text_of,
    texts,
    title,
    transcripts,
)
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


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


def test_records_are_the_objects_of_the_main_conversation(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(
        '{"type": "user", "timestamp": "2026-11-01T10:00:00.000Z"}\n'
        "not json\n"
        '["a", "list"]\n'
        '{"type": "assistant", "isSidechain": true}\n'
        '{"type": "summary"}\n'
        '{"type": "assistant", "timestamp": "2026-11-01T11:00:00.000Z"}\n'
    )
    assert [record["type"] for record in records(path)] == ["user", "summary", "assistant"]
    since = datetime(2026, 11, 1, 10, 30, tzinfo=UTC)
    assert [record["type"] for record in records(path, since)] == ["summary", "assistant"], "one without a time stays"


def test_contents_are_the_blocks_of_a_message() -> None:
    assert contents(user("a prompt")) == [{"type": "text", "text": "a prompt"}]
    assert contents(assistant({"type": "text", "text": "an answer"}, "stray", {"type": "tool_use"})) == [
        {"type": "text", "text": "an answer"},
        {"type": "tool_use"},
    ]
    assert contents({"type": "system"}) == [] and contents({"message": "no object"}) == []


def test_text_of_a_text_block_or_a_tool_result() -> None:
    assert text_of({"type": "text", "text": "plain"}) == "plain"
    assert text_of({"type": "tool_result", "content": "an error"}) == "an error"
    assert (
        text_of({"type": "tool_result", "content": [{"type": "text", "text": "two"}, {"text": "parts"}, 3]})
        == "two parts"
    )
    assert text_of({"type": "tool_use"}) == ""


def test_prompts_are_what_the_user_typed(tmp_path: Path) -> None:
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
            user([{"type": "text", "text": "the second prompt"}], at="2026-11-01T12:34:56.000Z"),
        ],
    )
    assert list(prompts(path)) == [("2026-11-01T10:00", "the first prompt"), ("2026-11-01T12:34", "the second prompt")]
    assert list(texts(path, everything=False)) == [
        ("2026-11-01T10:00", "USER", "the first prompt"),
        ("2026-11-01T12:34", "USER", "the second prompt"),
    ]
    everything = [(who, text) for _, who, text in texts(path, everything=True)]
    assert ("ASSISTANT", "an answer") in everything and ("USER", "a summary of the context") in everything
    assert ("USER", "injected") not in everything


def test_the_title_is_the_last_one_given(tmp_path: Path) -> None:
    path = write_transcript(
        tmp_path / "session.jsonl",
        [{"type": "ai-title", "aiTitle": "First"}, user("a prompt"), {"type": "ai-title", "title": "Second"}],
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
