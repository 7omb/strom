"""Reading the Claude Code transcripts of this project.

The transcripts are `~/.claude/projects/<the repository's path, non-alphanumerics as ->/*.jsonl`
(`CLAUDE_CONFIG_DIR` replaces `~/.claude`), one JSON object per line, a record. Their format is Claude Code's own
and not documented, so the reading is lenient: what is not as expected counts as missing."""

import json
import os
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from strom_tools.json_objects import JsonObject, is_list, is_object, member, parsed
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


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


def records(path: Path, since: datetime | None = None) -> Iterator[JsonObject]:
    """The records of a transcript, without those of subagents (`isSidechain`); with `since`, without those
    written up to then (a record that carries no time stays)."""
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                record = parsed(line)
            except json.JSONDecodeError:
                continue
            if not is_object(record) or record.get("isSidechain"):
                continue
            at = record.get("timestamp")
            if since is None or not isinstance(at, str) or datetime.fromisoformat(at) > since:
                yield record


def contents(record: JsonObject) -> list[JsonObject]:
    """The content blocks of a message record (a plain string as one text block)."""
    content = member(record.get("message"), "content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [block for block in content if is_object(block)] if is_list(content) else []


def text_of(block: JsonObject) -> str:
    """The text of a text block or a tool result."""
    content = block.get("text", block.get("content"))
    if is_list(content):
        return " ".join(str(part.get("text", "")) for part in content if is_object(part))
    return str(content) if content is not None else ""


def prompts(path: Path) -> Iterator[tuple[str, str]]:
    """The time and text of each prompt the user typed (no tool results, command output or injected text)."""
    for record in records(path):
        if record.get("type") != "user" or record.get("isMeta") or record.get("isCompactSummary"):
            continue
        for block in contents(record):
            text = text_of(block) if block.get("type") == "text" else ""
            if text and not text.startswith(("<local-command", "<command-", "<bash-", "<task-notification")):
                yield str(record.get("timestamp", ""))[:16], text


def texts(path: Path, *, everything: bool) -> Iterator[tuple[str, str, str]]:
    """The time, the author (`USER`, `ASSISTANT`) and the text of each prompt; with `everything`, of each text
    block of the user's and Claude's messages."""
    if not everything:
        yield from ((at, "USER", text) for at, text in prompts(path))
        return
    for record in records(path):
        if record.get("type") in ("user", "assistant") and not record.get("isMeta"):
            for block in contents(record):
                if block.get("type") == "text":
                    yield str(record.get("timestamp", ""))[:16], str(record["type"]).upper(), text_of(block)


def title(path: Path) -> str:
    found = ""
    for record in records(path):
        if record.get("type") == "ai-title":
            found = str(record.get("aiTitle") or record.get("title") or found)
    return found


def summaries(path: Path) -> tuple[int, int]:
    """How often the context of a session was summarised: in all, and since a turn last ended (a Stop that no
    hook blocked or failed at)."""
    num_summaries = num_new = 0
    for record in records(path):
        if record.get("type") != "system":
            continue
        if record.get("subtype") == "compact_boundary":
            num_summaries, num_new = num_summaries + 1, num_new + 1
        elif record.get("subtype") == "stop_hook_summary" and not record.get("hookErrors"):
            num_new = 0
    return num_summaries, num_new


def loaded_natively(transcript: Path, rule: Path) -> bool:
    """Whether Claude Code loaded the rule file `rule` itself in this session (an attachment naming it)."""
    if not transcript.exists():
        return False
    with transcript.open(encoding="utf-8") as lines:
        return any('"nested_memory"' in line and str(rule) in line for line in lines)
