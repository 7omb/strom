from pathlib import Path

from tool_helpers import assistant_record, tool_result, tool_use, user_record, write_transcript

from strom_tools.sessions.tool_usage import Usage, usage


def call(tool_id: str, name: str, **tool_input: object) -> dict[str, object]:
    return assistant_record(tool_use(tool_id, name, **tool_input))


def result(tool_id: str, text: str) -> dict[str, object]:
    return user_record([tool_result(tool_id, text)])


def test_usage_counts_the_calls_of_a_tool_and_the_bytes_of_their_results(tmp_path: Path) -> None:
    one = write_transcript(
        tmp_path / "one.jsonl",
        [
            call("t1", "Read", file_path="/a.py"),
            result("t1", "x" * 10),
            call("t2", "Bash", command="ls"),
            result("t2", "ä" * 10),
            call("t3", "Agent", subagent_type="reviewer"),
            result("t3", "findings"),
            call("t4", "Write", file_path="/b.py"),
            call("t5", "Agent", subagent_type="researcher"),
            result("unknown", "the result of no call"),
        ],
    )
    in_two = [call("t1", "Read", file_path="/c.py"), result("t1", "y" * 15), result("t2", "the result of no call here")]
    two = write_transcript(tmp_path / "two.jsonl", in_two)
    assert usage([one]) == [
        Usage("Bash", 1, 20),
        Usage("Read", 1, 10),
        Usage("Agent(reviewer)", 1, 8),
        Usage("Agent(researcher)", 1, 0),
        Usage("Write", 1, 0),
    ]
    assert usage([one, two])[:2] == [Usage("Read", 2, 25), Usage("Bash", 1, 20)], "an id is one session's"
    assert usage([]) == []
