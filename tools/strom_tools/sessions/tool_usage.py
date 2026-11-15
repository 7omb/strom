"""Tool usage: which tools sessions called, and how much the results put into their contexts."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from strom_tools.sessions.transcripts import Message, ToolResult, ToolUse, records


@dataclass(frozen=True)
class Usage:
    """The calls of one tool."""

    tool: str
    """Its name; of a call that starts a subagent, with the subagent's type (`Agent(reviewer)`)."""
    num_calls: int
    result_size: int
    """The bytes of the calls' results (as UTF-8): what they put into the context. Of a subagent that ran in the
    background only the note that it started: its report arrives as a message, which is not counted."""


def usage(paths: Iterable[Path]) -> list[Usage]:
    """The tool calls in the conversations of the sessions with the transcripts `paths`, the tool with the largest
    results first; without the calls of their subagents, whose results stay in the subagent's context."""
    num_calls = Counter[str]()
    result_size = Counter[str]()
    for path in paths:
        tools: dict[str, str] = {}  # by the id of the tool use
        for record in records(path):
            for block in record.blocks if isinstance(record, Message) else []:
                match block:
                    case ToolUse(id=use_id):
                        tools[use_id] = _tool_of(block)
                        num_calls[tools[use_id]] += 1
                    case ToolResult(tool_use_id, text) if tool_use_id in tools:
                        result_size[tools[tool_use_id]] += len(text.encode())
                    case _:
                        pass
    return sorted((Usage(tool, calls, result_size[tool]) for tool, calls in num_calls.items()), key=_largest_first)


def _tool_of(use: ToolUse) -> str:
    return use.name if use.agent_type is None else f"{use.name}({use.agent_type})"


def _largest_first(used: Usage) -> tuple[int, str]:
    return -used.result_size, used.tool
