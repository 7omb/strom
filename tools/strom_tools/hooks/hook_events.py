"""What a Claude Code hook gets, as data: Claude Code passes an event as JSON on stdin, and `parse` makes one of the
`HookEvent` classes of it, with the fields the handlers use. What a hook answers: `hook_results`."""

from dataclasses import dataclass
from pathlib import Path

from strom_tools.json_objects import member


@dataclass(frozen=True)
class Session:
    id: str
    """`unknown` if the event names none."""
    transcript: Path | None
    """The session's transcript, if the event names it (the file need not exist)."""


@dataclass(frozen=True)
class ToolRequested:
    """PreToolUse: a tool call is about to run; a block stops it."""

    session: Session
    tool: str
    command: str | None
    """The command of a Bash call."""


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


type HookEvent = ToolRequested | ToolUsed | TurnEnded | SessionStarted | SessionEnded


def parse(payload: object) -> HookEvent | None:
    """The event of a hook's input; None for an event no handler is for."""
    session = Session(_text(member(payload, "session_id")) or "unknown", _path(member(payload, "transcript_path")))
    match member(payload, "hook_event_name"):
        case "PreToolUse":
            command = _text(member(member(payload, "tool_input"), "command"))
            return ToolRequested(session, str(member(payload, "tool_name")), command)
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
