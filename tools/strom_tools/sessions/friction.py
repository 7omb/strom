"""Friction: what cost a session round trips, and the log of it.

The kinds: hook blocks (`hook_blocks`), tool errors other than rejections (`tool_errors`), tool calls the user
or the permission check rejected (`rejected`), interrupts by the user (`interrupts`; the calls an interrupt
cancels are part of it, no rejections) and diagnostics the IDE attached after edits (`diagnostics`, often stale).

The friction log (`friction.jsonl` in the state directory) gets a line when a session ends and one per
retrospective. A session's line counts what came after the log's last line about that session or, if later, the
last retrospective: so the lines after a retrospective add up, also those of a session that was resumed or that
ran the retrospective itself."""

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from strom_tools.json_objects import JsonObject, is_object, parsed
from strom_tools.sessions.transcripts import contents, records, text_of
from strom_tools.workspace.repository import Repository, state_dir

KINDS = ["hook_blocks", "tool_errors", "rejected", "interrupts", "diagnostics"]
"""The kinds of friction, as the friction log and the table name them."""
_INTERRUPTED = "[Request interrupted by user"
_REJECTED = ("The user doesn't want to proceed", "Permission for this", "denied by")


@dataclass(frozen=True)
class Event:
    """One piece of friction."""

    at: str
    """Its time in the transcript (UTC)."""
    kind: str
    """One of `KINDS`."""
    call: str
    """The tool call it came from; of an interrupt, the calls it cancelled."""
    answer: str
    """What the hook, the tool or the user answered."""


def events(path: Path, since: datetime | None = None) -> Iterator[Event]:
    """The friction of a session in the order of its transcript (with `since`: what came after it)."""
    calls: dict[str, str] = {}  # by the id of the tool use
    cancelled: list[Event] = []  # rejections that an interrupt may follow: then they are part of it
    for record in records(path, since):
        kind, at = record.get("type"), str(record.get("timestamp", ""))
        attachment = record.get("attachment")
        if kind == "attachment" and is_object(attachment):
            if attachment.get("type") == "hook_blocking_error":
                error = attachment.get("blockingError")
                answer = error.get("blockingError") if is_object(error) else error
                call = calls.get(str(attachment.get("toolUseID")), str(attachment.get("hookName")))
                yield Event(at, "hook_blocks", call, str(answer))
            elif attachment.get("type") == "diagnostics":
                yield Event(at, "diagnostics", "", json.dumps(attachment.get("files")))
        elif kind == "assistant":  # Claude went on: no interrupt followed the rejections
            yield from cancelled
            cancelled.clear()
        for block in contents(record):
            if kind == "assistant" and block.get("type") == "tool_use":
                calls[str(block.get("id"))] = _call_of(block)
            elif kind == "user" and block.get("type") == "tool_result":
                answer, call = text_of(block), calls.get(str(block.get("tool_use_id")), "")
                if any(marker in answer[:300] for marker in _REJECTED):
                    cancelled.append(Event(at, "rejected", call, answer))
                elif block.get("is_error"):
                    yield Event(at, "tool_errors", call, answer)
            elif kind == "user" and block.get("type") == "text" and text_of(block).startswith(_INTERRUPTED):
                yield Event(at, "interrupts", "; ".join(event.call for event in cancelled), text_of(block))
                cancelled.clear()
    yield from cancelled


def _call_of(block: JsonObject) -> str:
    """A tool use in short: the tool and its command or file (else its whole input)."""
    tool_input = block.get("input")
    told = tool_input.get("command") or tool_input.get("file_path") if is_object(tool_input) else None
    return f"{block.get('name')}: {told or tool_input}"


def command_beginnings(path: Path, since: datetime | None = None) -> Counter[str]:
    """How often each beginning (two words) of a Bash command occurs in a session."""
    found = Counter[str]()
    for record in records(path, since):
        for block in contents(record):
            tool_input = block.get("input")
            command = tool_input.get("command") if is_object(tool_input) else None
            if record.get("type") == "assistant" and block.get("name") == "Bash" and isinstance(command, str):
                found[" ".join(command.split()[:2])] += 1
    return found


def _log_file(repository: Repository) -> Path:
    return state_dir(repository) / "friction.jsonl"


def log_friction(repository: Repository, transcript: Path) -> None:
    """Appends a session's friction to the log: what came after the log's last line about the session or, if
    later, the last retrospective."""
    counts = Counter(event.kind for event in events(transcript, last_logged(repository, transcript.stem)))
    _append_log(repository, {"session": transcript.stem, **{kind: counts[kind] for kind in KINDS}})


def log_retro(repository: Repository) -> None:
    """Records a retrospective in the log: the sessions' lines count from here."""
    _append_log(repository, {"retro": True})


def _append_log(repository: Repository, entry: JsonObject) -> None:
    log = _log_file(repository)
    log.parent.mkdir(exist_ok=True)
    line: JsonObject = {"at": datetime.now(UTC).isoformat(timespec="seconds"), **entry}
    with log.open("a", encoding="utf-8") as lines:
        lines.write(json.dumps(line) + "\n")


def _logged(repository: Repository) -> list[JsonObject]:
    """The lines of the friction log."""
    log = _log_file(repository)
    if not log.exists():
        return []
    entries = [parsed(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return [entry for entry in entries if is_object(entry)]


def last_logged(repository: Repository, session: str | None = None) -> datetime | None:
    """When the friction log last got a retrospective or, with `session`, a line of that session."""
    times = [
        str(entry.get("at"))
        for entry in _logged(repository)
        if entry.get("retro") or (session is not None and entry.get("session") == session)
    ]
    return datetime.fromisoformat(times[-1]) if times else None


def since_last_retro(repository: Repository) -> list[JsonObject]:
    """The sessions' lines after the last retrospective."""
    entries: list[JsonObject] = []
    for entry in _logged(repository):
        entries = [] if entry.get("retro") else [*entries, entry]
    return entries
