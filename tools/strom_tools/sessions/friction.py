"""Friction: what cost a session round trips, and the log of it.

The kinds: `Kind`. The calls an interrupt cancels count as part of it, not as rejections.

The friction log (`friction.jsonl` in the state directory) gets a line when a session ends (`SessionLogged`) and
one per retrospective (`RetroLogged`). A session's line counts what came after the log's last line about that
session or, if later, the last retrospective: so the lines after a retrospective add up, also those of a session
that was resumed or that ran the retrospective itself."""

import json
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from strom_tools.json_objects import JsonObject, is_object, member, parsed
from strom_tools.sessions.transcripts import (
    Author,
    DiagnosticsAttached,
    HookBlocked,
    Message,
    Text,
    ToolResult,
    ToolUse,
    find,
    records,
    transcripts,
)
from strom_tools.workspace.repository import Repository, state_dir


class Kind(Enum):
    """A kind of friction, by the name the friction log and the table give it."""

    HOOK_BLOCKS = "hook_blocks"
    """A hook blocked."""
    TOOL_ERRORS = "tool_errors"
    """A tool call failed (not a rejection)."""
    REJECTED = "rejected"
    """The user or the permission check rejected a tool call."""
    INTERRUPTS = "interrupts"
    """The user interrupted."""
    DIAGNOSTICS = "diagnostics"
    """The IDE attached diagnostics after edits (often stale)."""


_INTERRUPTED = "[Request interrupted by user"
_REJECTED = ("The user doesn't want to proceed", "Permission for this", "denied by")


@dataclass(frozen=True)
class Event:
    """One piece of friction."""

    at: datetime | None
    """Its time in the transcript."""
    kind: Kind
    call: str
    """The tool call it came from; of an interrupt, the calls it cancelled."""
    answer: str
    """What the hook, the tool or the user answered."""


def events(path: Path, since: datetime | None = None) -> Iterator[Event]:
    """The friction of a session in the order of its transcript (with `since`: what came after it)."""
    calls: dict[str, str] = {}  # by the id of the tool use
    cancelled: list[Event] = []  # rejections that an interrupt may follow: then they are part of it
    for record in records(path, since):
        match record:
            case HookBlocked(at, tool_use_id, hook_name, message):
                yield Event(at, Kind.HOOK_BLOCKS, calls.get(tool_use_id, hook_name), message)
            case DiagnosticsAttached(at, files):
                yield Event(at, Kind.DIAGNOSTICS, "", files)
            case Message(author=Author.ASSISTANT, blocks=blocks):  # Claude went on: no interrupt followed
                yield from cancelled
                cancelled.clear()
                calls.update((block.id, _call_of(block)) for block in blocks if isinstance(block, ToolUse))
            case Message(at, Author.USER, blocks=blocks):
                for block in blocks:
                    match block:
                        case ToolResult(tool_use_id, answer) if any(mark in answer[:300] for mark in _REJECTED):
                            cancelled.append(Event(at, Kind.REJECTED, calls.get(tool_use_id, ""), answer))
                        case ToolResult(tool_use_id, answer, is_error=True):
                            yield Event(at, Kind.TOOL_ERRORS, calls.get(tool_use_id, ""), answer)
                        case Text(text) if text.startswith(_INTERRUPTED):
                            yield Event(at, Kind.INTERRUPTS, "; ".join(event.call for event in cancelled), text)
                            cancelled.clear()
                        case _:
                            pass
            case _:
                pass
    yield from cancelled


def counted(found: Iterable[Event]) -> dict[Kind, int]:
    """How many events of each kind (every kind, also those that did not occur)."""
    counts = Counter(event.kind for event in found)
    return {kind: counts[kind] for kind in Kind}


def covered(repository: Repository, prefixes: Sequence[str], num_recent: int, since: datetime | None) -> list[Path]:
    """The transcripts a report of friction covers: those of the sessions whose ids start with `prefixes`;
    without any, those written after `since` (the last retrospective), or without that the last `num_recent`."""
    if prefixes:
        return [find(repository, prefix) for prefix in prefixes]
    recent = transcripts(repository)
    if since is None:
        return recent[-num_recent:]
    return [path for path in recent if datetime.fromtimestamp(path.stat().st_mtime, UTC) > since]


def _call_of(use: ToolUse) -> str:
    """A tool use in short: the tool and its command or file (else its whole input)."""
    return f"{use.name}: {use.command or use.file_path or use.arguments}"


def command_beginnings(path: Path, since: datetime | None = None) -> Counter[str]:
    """How often each beginning (two words) of a Bash command occurs in a session."""
    found = Counter[str]()
    for record in records(path, since):
        if isinstance(record, Message) and record.author is Author.ASSISTANT:
            for block in record.blocks:
                if isinstance(block, ToolUse) and block.name == "Bash" and block.command is not None:
                    found[" ".join(block.command.split()[:2])] += 1
    return found


@dataclass(frozen=True)
class SessionLogged:
    """A line of the friction log: a session's friction since its last line or the last retrospective."""

    at: datetime
    session: str
    counts: Mapping[Kind, int]
    """Every kind, also those that did not occur."""


@dataclass(frozen=True)
class RetroLogged:
    """A line of the friction log: a retrospective, from which the sessions' lines count anew."""

    at: datetime


type LogLine = SessionLogged | RetroLogged


def _log_file(repository: Repository) -> Path:
    return state_dir(repository) / "friction.jsonl"


def log_friction(repository: Repository, transcript: Path) -> None:
    """Appends a session's friction to the log: what came after the log's last line about the session or, if
    later, the last retrospective."""
    found = events(transcript, last_logged(repository, transcript.stem))
    _append_log(repository, SessionLogged(_now(), transcript.stem, counted(found)))


def log_retro(repository: Repository) -> None:
    """Records a retrospective in the log: the sessions' lines count from here."""
    _append_log(repository, RetroLogged(_now()))


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _append_log(repository: Repository, line: LogLine) -> None:
    log = _log_file(repository)
    log.parent.mkdir(exist_ok=True)
    with log.open("a", encoding="utf-8") as lines:
        lines.write(json.dumps(_serialised(line)) + "\n")


def _serialised(line: LogLine) -> JsonObject:
    match line:
        case SessionLogged(at, session, counts):
            return {"at": at.isoformat(), "session": session, **{kind.value: counts[kind] for kind in Kind}}
        case RetroLogged(at):
            return {"at": at.isoformat(), "retro": True}


def _log_line(value: object) -> LogLine | None:
    """A line of the log as `_serialised` writes it; None for one that is not."""
    try:
        at = datetime.fromisoformat(str(member(value, "at")))
    except ValueError:
        return None
    session = member(value, "session")
    if member(value, "retro") is True:
        return RetroLogged(at)
    if not isinstance(session, str):
        return None
    counts = {kind: member(value, kind.value) for kind in Kind}
    return SessionLogged(at, session, {kind: count if isinstance(count, int) else 0 for kind, count in counts.items()})


def _logged(repository: Repository) -> list[LogLine]:
    """The lines of the friction log (a line that is none is left out)."""
    log = _log_file(repository)
    if not log.exists():
        return []
    found: list[LogLine] = []
    for text in log.read_text(encoding="utf-8").splitlines():
        try:
            value = parsed(text)
        except json.JSONDecodeError:
            continue
        line = _log_line(value) if is_object(value) else None
        if line is not None:
            found.append(line)
    return found


def last_logged(repository: Repository, session: str | None = None) -> datetime | None:
    """When the friction log last got a retrospective or, with `session`, a line of that session."""
    times = [
        line.at
        for line in _logged(repository)
        if isinstance(line, RetroLogged) or (session is not None and line.session == session)
    ]
    return times[-1] if times else None


def since_last_retro(repository: Repository) -> list[SessionLogged]:
    """The sessions' lines after the last retrospective."""
    found: list[SessionLogged] = []
    for line in _logged(repository):
        found = [] if isinstance(line, RetroLogged) else [*found, line]
    return found
