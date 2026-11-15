"""Reading the Claude Code transcripts of this project.

The transcripts are `~/.claude/projects/<the repository's path, non-alphanumerics as ->/*.jsonl`
(`CLAUDE_CONFIG_DIR` replaces `~/.claude`), one JSON object per line, a record. A subagent of a session has a
transcript of its own, `SESSION/subagents/agent-ID.jsonl` beside the session's `SESSION.jsonl`: a file is one
conversation (its records are marked `isSidechain`, and no session's transcript of 54 held one, 2026-11-15, so the
mark is not read). Their format is Claude Code's own and not documented, so the reading is lenient: `records`
parses each line once into one of the `Record` classes, with the fields the tools read; a line that is none of
them, or a field that is not as expected, counts as missing."""

import json
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from strom_tools.json_objects import JsonObject, is_list, is_object, member, parsed
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    command: str | None
    """Of a Bash call."""
    file_path: str | None
    """Of a call that names a file (Read, Edit, Write)."""
    agent_type: str | None
    """Of a call that starts a subagent (Agent): its type."""
    arguments: str
    """The whole input, as Python shows it."""


@dataclass(frozen=True)
class ToolResult:
    tool_use_id: str
    text: str
    is_error: bool


type Block = Text | ToolUse | ToolResult
"""A content block of a message."""


class Author(Enum):
    USER = "user"
    ASSISTANT = "assistant"


class Origin(Enum):
    """Where a message comes from."""

    CONVERSATION = "conversation"
    """Typed by the user (prompts, tool results) or written by Claude."""
    INJECTED = "injected"
    """Added by Claude Code (`isMeta`: a skill's text, a command's caveat; `isApiErrorMessage`: a failed request
    in the place of Claude's message)."""
    SUMMARY = "summary"
    """The summary of the context that a new context starts with (`isCompactSummary`)."""


@dataclass(frozen=True)
class Message:
    at: datetime | None
    author: Author
    origin: Origin
    blocks: list[Block]


@dataclass(frozen=True)
class HookBlocked:
    at: datetime | None
    tool_use_id: str
    """The tool call a PostToolUse hook blocked after (an id no call has for other events)."""
    hook_name: str
    message: str


@dataclass(frozen=True)
class DiagnosticsAttached:
    """Diagnostics the IDE attached after edits."""

    at: datetime | None
    files: str
    """The files and their diagnostics, as JSON."""


@dataclass(frozen=True)
class ContextSummarised:
    at: datetime | None


@dataclass(frozen=True)
class StopHooksRan:
    """The Stop hooks ran at the end of a turn."""

    at: datetime | None
    failed: bool
    """One of them blocked or failed: the turn goes on."""


@dataclass(frozen=True)
class TitleGiven:
    at: datetime | None
    title: str


type Record = Message | HookBlocked | DiagnosticsAttached | ContextSummarised | StopHooksRan | TitleGiven


def _transcripts_dir(repository: Repository) -> Path:
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(repository.root))


def transcripts(repository: Repository) -> list[Path]:
    """The transcripts of this project, oldest first (by modification time)."""
    return sorted(_transcripts_dir(repository).glob("*.jsonl"), key=_modified_at)


def _modified_at(path: Path) -> float:
    return path.stat().st_mtime


def find(repository: Repository, prefix: str) -> Path:
    """The transcript of the one session whose id starts with `prefix`; a `ToolError` if there is no such one."""
    matches = [path for path in transcripts(repository) if path.stem.startswith(prefix)]
    if len(matches) != 1:
        raise ToolError(f"{len(matches)} sessions start with {prefix!r}")
    return matches[0]


def chosen(repository: Repository, prefixes: Sequence[str], num_recent: int) -> list[Path]:
    """The transcripts of the sessions whose ids start with `prefixes`; without any, the last `num_recent`."""
    if prefixes:
        return [find(repository, prefix) for prefix in prefixes]
    return transcripts(repository)[-num_recent:]


def subagent_transcripts(path: Path) -> list[Path]:
    """The transcripts of the subagents of the session with the transcript `path`, oldest first."""
    return sorted(_subagents_dir(path).glob("agent-*.jsonl"), key=_modified_at)


def subagent_transcript(path: Path, agent_id: str) -> Path:
    """The transcript of the subagent `agent_id` in the session with the transcript `path` (the file need not
    exist)."""
    return _subagents_dir(path) / f"agent-{agent_id}.jsonl"


def _subagents_dir(path: Path) -> Path:
    return path.with_suffix("") / "subagents"


def records(path: Path, since: datetime | None = None) -> Iterator[Record]:
    """The records of the conversation with the transcript `path`, a session's or a subagent's; with `since`,
    without those written up to then (a record that carries no time stays)."""
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                value = parsed(line)
            except json.JSONDecodeError:
                continue
            if not is_object(value):
                continue
            record = _record(value)
            if record is not None and (since is None or record.at is None or record.at > since):
                yield record


def _record(value: JsonObject) -> Record | None:
    at = _time(value.get("timestamp"))
    attachment = value.get("attachment")
    match value.get("type"), value.get("subtype"), member(attachment, "type"):
        case ("user" | "assistant") as author, _, _:
            return Message(at, Author(author), _origin(value), _blocks(member(value.get("message"), "content")))
        case "attachment", _, "hook_blocking_error":
            error = member(attachment, "blockingError")
            message = member(error, "blockingError") if is_object(error) else error
            tool_use_id, hook_name = member(attachment, "toolUseID"), member(attachment, "hookName")
            return HookBlocked(at, str(tool_use_id), str(hook_name), str(message))
        case "attachment", _, "diagnostics":
            return DiagnosticsAttached(at, json.dumps(member(attachment, "files")))
        case "system", "compact_boundary", _:
            return ContextSummarised(at)
        case "system", "stop_hook_summary", _:
            return StopHooksRan(at, bool(value.get("hookErrors")))
        case "ai-title", _, _:
            return TitleGiven(at, str(value.get("aiTitle") or value.get("title") or ""))
        case _:
            return None


def _time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _origin(record: JsonObject) -> Origin:
    if record.get("isMeta") or record.get("isApiErrorMessage"):
        return Origin.INJECTED
    if record.get("isCompactSummary"):
        return Origin.SUMMARY
    return Origin.CONVERSATION


def _blocks(content: object) -> list[Block]:
    """The content blocks of a message (a plain string as one text block)."""
    if isinstance(content, str):
        return [Text(content)]
    found = [_block(block) for block in content if is_object(block)] if is_list(content) else []
    return [block for block in found if block is not None]


def _block(block: JsonObject) -> Block | None:
    match block.get("type"):
        case "text":
            return Text(_text_of(block.get("text")))
        case "tool_use":
            tool_input = block.get("input")
            return ToolUse(
                str(block.get("id")),
                str(block.get("name")),
                _text_member(tool_input, "command"),
                _text_member(tool_input, "file_path"),
                _text_member(tool_input, "subagent_type"),
                str(tool_input),
            )
        case "tool_result":
            return ToolResult(
                str(block.get("tool_use_id")), _text_of(block.get("content")), block.get("is_error") is True
            )
        case _:
            return None


def _text_member(value: object, key: str) -> str | None:
    found = member(value, key)
    return found if isinstance(found, str) else None


def _text_of(content: object) -> str:
    """The text of a block's content: a string, or the text parts of a list."""
    if is_list(content):
        return " ".join(str(member(part, "text") or "") for part in content if is_object(part))
    return str(content) if content is not None else ""


def minute(at: datetime | None) -> str:
    """A record's time as the listings show it (`2026-11-01T10:00`, UTC as written); empty if it has none."""
    return f"{at:%Y-%m-%dT%H:%M}" if at is not None else ""


@dataclass(frozen=True)
class Said:
    """A text of the conversation: a prompt, or a text block of the user's or Claude's messages."""

    at: datetime | None
    author: Author
    text: str


_NOT_TYPED = ("<local-command", "<command-", "<bash-", "<task-notification")
"""The beginnings of text Claude Code adds to a user message: command output, notifications."""


def prompts(path: Path) -> Iterator[Said]:
    """Each prompt the user typed (no tool results, command output or injected text)."""
    for record in records(path):
        yield from _prompts_of(record)


def _prompts_of(record: Record) -> Iterator[Said]:
    if isinstance(record, Message) and record.author is Author.USER and record.origin is Origin.CONVERSATION:
        for block in record.blocks:
            if isinstance(block, Text) and block.text and not block.text.startswith(_NOT_TYPED):
                yield Said(record.at, record.author, block.text)


def answer(path: Path, asked_at: str) -> Said:
    """Claude's last text of the turn that the first prompt typed at `asked_at` started (a time as `minute` shows
    it, or its beginning): what it wrote before the next prompt. A `ToolError` if no prompt was typed then, or no
    text followed it."""
    asked = False
    last: Said | None = None
    for record in records(path):
        if next(_prompts_of(record), None) is not None:
            if asked:
                break
            asked = minute(record.at).startswith(asked_at)
        elif (
            asked
            and isinstance(record, Message)
            and record.author is Author.ASSISTANT
            and record.origin is Origin.CONVERSATION
        ):
            for block in record.blocks:
                if isinstance(block, Text) and block.text.strip():
                    last = Said(record.at, record.author, block.text)
    if last is None:
        raise ToolError(f"no answer to a prompt typed at {asked_at!r}")
    return last


def texts(path: Path, *, everything: bool) -> Iterator[Said]:
    """Each prompt; with `everything`, each text block of the user's and Claude's messages (the summaries of the
    context too)."""
    if not everything:
        yield from prompts(path)
        return
    for record in records(path):
        if isinstance(record, Message) and record.origin is not Origin.INJECTED:
            yield from (
                Said(record.at, record.author, block.text) for block in record.blocks if isinstance(block, Text)
            )


def title(path: Path) -> str:
    """The last title given to the session (empty if none)."""
    found = ""
    for record in records(path):
        if isinstance(record, TitleGiven) and record.title:
            found = record.title
    return found


def summaries(path: Path) -> tuple[int, int]:
    """How often the context of a session was summarised: in all, and since a turn last ended (a stop at which
    no hook blocked or failed)."""
    num_summaries = num_new = 0
    for record in records(path):
        match record:
            case ContextSummarised():
                num_summaries, num_new = num_summaries + 1, num_new + 1
            case StopHooksRan(failed=False):
                num_new = 0
            case _:
                pass
    return num_summaries, num_new


@dataclass(frozen=True)
class ApiCall:
    """A request of a conversation to the model, with the tokens it was charged."""

    input: int
    """The tokens of the context that were neither read from the cache nor written to it."""
    cache_written: int
    """Those written to the cache for five minutes (a subagent's)."""
    cache_written_for_an_hour: int
    cache_read: int
    output: int

    @property
    def context(self) -> int:
        """The tokens the request sent: the context of the conversation at that call."""
        return self.input + self.cache_written + self.cache_written_for_an_hour + self.cache_read


def api_calls(path: Path) -> list[ApiCall]:
    """The requests of the conversation with the transcript `path` (a session's or a subagent's), in their order.

    A request's answer is a record per content block, each with the same message id and usage, so an id counts
    once; an answer Claude Code made up itself (an API error, model `<synthetic>`) is no request. The records of
    type `api-request-blob` repeat messages and are not read."""
    calls: dict[str, ApiCall] = {}
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            if '"usage"' not in line:
                continue
            try:
                value = parsed(line)
            except json.JSONDecodeError:
                continue
            message = member(value, "message")
            message_id, usage = member(message, "id"), member(message, "usage")
            if member(value, "type") != "assistant" or member(message, "model") == "<synthetic>":
                continue
            if isinstance(message_id, str) and is_object(usage):
                for_an_hour = _count(member(usage.get("cache_creation"), "ephemeral_1h_input_tokens"))
                calls[message_id] = ApiCall(
                    _count(usage.get("input_tokens")),
                    _count(usage.get("cache_creation_input_tokens")) - for_an_hour,
                    for_an_hour,
                    _count(usage.get("cache_read_input_tokens")),
                    _count(usage.get("output_tokens")),
                )
    return list(calls.values())


def _count(value: object) -> int:
    return value if isinstance(value, int) else 0


def subagent_type(path: Path) -> str:
    """The type of the subagent with the transcript `path` (`reviewer`), from the file Claude Code writes beside
    it; `?` without one."""
    described = path.with_name(path.name.removesuffix(".jsonl") + ".meta.json")
    try:
        found = member(parsed(described.read_text(encoding="utf-8")), "agentType")
    except OSError, json.JSONDecodeError:
        return "?"
    return found if isinstance(found, str) else "?"


def loaded_natively(transcript: Path, rule: Path) -> bool:
    """Whether Claude Code loaded the rule file `rule` itself in the conversation of `transcript`, a session's or a
    subagent's (an attachment naming it), since the last summary of the context, which drops it (Claude Code loads
    it again at the next read).

    A scan of the raw lines, not of `records`: the hook after every Bash call asks it, and parsing a transcript of
    several MB would cost more than the rest of the hook."""
    if not transcript.exists():
        return False
    loaded = False
    with transcript.open(encoding="utf-8") as lines:
        for line in lines:
            if '"compact_boundary"' in line:
                loaded = False
            elif '"nested_memory"' in line and str(rule) in line:
                loaded = True
    return loaded
