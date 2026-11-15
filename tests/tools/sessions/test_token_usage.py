from pathlib import Path

from tool_helpers import api_answer as answer
from tool_helpers import user_record, write_transcript

from strom_tools.sessions.token_usage import Tokens, context, usage


def test_usage_weighs_the_tokens_of_a_session_and_of_each_subagent(tmp_path: Path) -> None:
    first = answer("m1", read=1000, output=10, for_an_hour=100)
    session = write_transcript(
        tmp_path / "abcd.jsonl",
        [
            first,
            first,  # the same answer, a record per content block
            {**first, "type": "api-request-blob"},
            answer("error", read=10**6, output=10**6, model="<synthetic>"),
            answer("m2", read=900, output=20),
            user_record("no usage"),
        ],
    )
    subagents = tmp_path / "abcd" / "subagents"
    subagents.mkdir(parents=True)
    write_transcript(subagents / "agent-a1.jsonl", [answer("m1", read=500, output=4, written=40)])
    (subagents / "agent-a1.meta.json").write_text('{"agentType": "reviewer"}', encoding="utf-8")
    write_transcript(subagents / "agent-a2.jsonl", [])
    assert usage(session) == [
        Tokens("session", 2, 1102, written=2 + 2 * 100 + 2, reread=190.0, output=150.0),
        Tokens("reviewer", 1, 542, written=2 + 1.25 * 40, reread=50.0, output=20.0),
        Tokens("?", 0, 0, 0, 0, 0),
    ]
    assert usage(session)[0].total == 544.0
    assert context(session) == 902, "that of the last request, not the largest"
    assert context(subagents / "agent-a2.jsonl") == 0
