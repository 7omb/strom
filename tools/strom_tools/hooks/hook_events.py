"""What a Claude Code hook gets and what it answers, as data.

Claude Code passes an event as JSON on stdin; `parse` makes one of the `HookEvent` classes of it, with the fields
the handlers use. A handler returns a `HookResult`, and `answer` turns the results of all handlers of an event
into what the hook command prints and exits with: exit code 2 blocks and sends stderr to Claude; stdout holds one
JSON object with the notes.

A note beside a block is printed too. The hooks reference (read 2026-11-11) says of exit code 2: "Claude Code
still reads the JSON output fields, but they can't override the block", and that a blocking decision in the JSON
would replace stderr as the message: the JSON here holds none. Not observed on a running session; a handler whose
note must not be lost returns it again while it holds (`friction_notes.at_stop`, until a stop that is not
blocked), at the price of a note shown twice."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from strom_tools.json_objects import JsonObject, member


@dataclass(frozen=True)
class Session:
    id: str
    """`unknown` if the event names none."""
    transcript: Path | None
    """The session's transcript, if the event names it (the file need not exist)."""


@dataclass(frozen=True)
class ToolUsed:
    """PostToolUse: a tool call returned."""

    session: Session
    tool: str
    file_path: str | None
    """The file an Edit or a Write named."""
    command: str | None
    """The command of a Bash call."""


@dataclass(frozen=True)
class TurnEnded:
    """Stop: Claude is about to end its turn."""

    session: Session
    again: bool
    """A hook blocked the stop of this turn before (`stop_hook_active`): blocking again could loop."""


@dataclass(frozen=True)
class SessionStarted:
    session: Session
    source: str
    """`startup`, `clear`, `resume`, `compact`."""


@dataclass(frozen=True)
class SessionEnded:
    session: Session


type HookEvent = ToolUsed | TurnEnded | SessionStarted | SessionEnded


def parse(payload: object) -> HookEvent | None:
    """The event of a hook's input; None for an event no handler is for."""
    session = Session(_text(member(payload, "session_id")) or "unknown", _path(member(payload, "transcript_path")))
    match member(payload, "hook_event_name"):
        case "PostToolUse":
            tool_input = member(payload, "tool_input")
            return ToolUsed(
                session,
                str(member(payload, "tool_name")),
                _text(member(tool_input, "file_path")),
                _text(member(tool_input, "command")),
            )
        case "Stop":
            return TurnEnded(session, member(payload, "stop_hook_active") is True)
        case "SessionStart":
            return SessionStarted(session, str(member(payload, "source")))
        case "SessionEnd":
            return SessionEnded(session)
        case _:
            return None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _path(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) else None


def _name_of(event: HookEvent) -> str:
    """The event as Claude Code names it."""
    match event:
        case ToolUsed():
            return "PostToolUse"
        case TurnEnded():
            return "Stop"
        case SessionStarted():
            return "SessionStart"
        case SessionEnded():
            return "SessionEnd"


@dataclass(frozen=True)
class Block:
    """Claude has to deal with `message` before it goes on."""

    message: str


@dataclass(frozen=True)
class Note:
    for_user: str | None = None
    """Shown to the user."""
    for_claude: str | None = None
    """Added to Claude's context."""


@dataclass(frozen=True)
class Failed:
    """A handler raised: `message` is reported, and nothing is blocked."""

    message: str


type HookResult = Block | Note | None
"""What a handler returns; None: nothing to say."""


@dataclass(frozen=True)
class Answer:
    exit_code: int
    stdout: str
    stderr: str


def answer(event: HookEvent, results: Sequence[HookResult | Failed]) -> Answer:
    """What the hook command answers Claude Code with: the messages of the blocks and failures on stderr, the
    notes as one JSON object on stdout, and the exit code 2 if a handler blocks, else 1 if one failed."""
    blocks = [result for result in results if isinstance(result, Block)]
    failures = [result for result in results if isinstance(result, Failed)]
    notes = [result for result in results if isinstance(result, Note)]
    for_user = [note.for_user for note in notes if note.for_user is not None]
    for_claude = [note.for_claude for note in notes if note.for_claude is not None]
    output: JsonObject = {}
    if for_user:
        output["systemMessage"] = "\n\n".join(for_user)
    if for_claude:
        context: JsonObject = {"hookEventName": _name_of(event), "additionalContext": "\n\n".join(for_claude)}
        output["hookSpecificOutput"] = context
    told = [result.message for result in results if isinstance(result, Block | Failed)]
    return Answer(
        2 if blocks else 1 if failures else 0,
        f"{json.dumps(output)}\n" if output else "",
        "".join(f"{message}\n" for message in told),
    )
