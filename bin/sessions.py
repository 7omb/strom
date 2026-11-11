"""Reads the Claude Code transcripts of this project: past sessions, their prompts and their friction.

Run:  python bin/sessions.py list [-n N]                  sessions (newest last): start, title, size, prompts
      python bin/sessions.py prompts SESSION              the user's prompts of a session (an id prefix)
      python bin/sessions.py search TERM [-n N] [--all]   the prompts (`--all`: also Claude's text) matching TERM
      python bin/sessions.py friction [SESSION ...] [-n N] [--since-retro] [--details] [--commands]
                                                          friction per session (default: the last 5)
      python bin/sessions.py mark-retro                   records a retrospective in the friction log

The transcripts are `~/.claude/projects/<this path, non-alphanumerics as ->/*.jsonl` (`CLAUDE_CONFIG_DIR`
replaces `~/.claude`), one JSON object per line; their format is Claude Code's own and not documented, so the
reading is lenient. TERM is a case-insensitive regular expression.

Friction counts what cost a session round trips: hook blocks (`hook_blocks`), tool errors other than
rejections (`tool_errors`), tool calls the user or the permission check rejected (`rejected`), interrupts by
the user (`interrupts`; the calls an interrupt cancels are part of it, no rejections) and diagnostics the IDE
attached after edits (`diagnostics`, often stale). `--since-retro` takes the sessions that went on after the
last retrospective, and of each only what came after it; `--details` lists each piece of friction, the tool
call and its answer; `--commands` the most frequent Bash command beginnings, candidates for a script or a make
target.

The friction log `.checks/friction.jsonl` gets a line when a session ends (written by the SessionEnd hook,
`.claude/hooks/friction.py`) and one per retrospective (`mark-retro`, run by the skill `retro`). A session's
line counts what came after the log's last line about that session or, if later, the last retrospective: so
the lines after a retrospective add up (the SessionStart hook sums them), also those of a session that was
resumed or that ran the retrospective itself. Standard library only: the hooks import this module with the dev
shell's Python.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRICTION_LOG = ROOT / ".checks" / "friction.jsonl"
KINDS = ["hook_blocks", "tool_errors", "rejected", "interrupts", "diagnostics"]
"""The kinds of friction, as the friction log and the table name them."""
INTERRUPTED = "[Request interrupted by user"
REJECTED = ("The user doesn't want to proceed", "Permission for this", "denied by")
SHOWN = 300
"""How many characters of a call and of its answer `--details` shows."""

type Json = dict[str, object]


def transcripts_dir() -> Path:
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))


def transcripts() -> list[Path]:
    """The transcripts of this project, oldest first (by modification time)."""
    return sorted(transcripts_dir().glob("*.jsonl"), key=lambda path: path.stat().st_mtime)


def find(prefix: str) -> Path:
    matches = [path for path in transcripts() if path.stem.startswith(prefix)]
    if len(matches) != 1:
        sys.exit(f"{len(matches)} sessions start with {prefix!r}")
    return matches[0]


def records(path: Path, since: datetime | None = None) -> Iterator[Json]:
    """The JSON objects of a transcript, without those of subagents (`isSidechain`); with `since`, without those
    written up to then (an object that carries no time stays)."""
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or record.get("isSidechain"):
                continue
            at = record.get("timestamp")
            if since is None or not isinstance(at, str) or datetime.fromisoformat(at) > since:
                yield record


def contents(record: Json) -> list[Json]:
    """The content blocks of a message record (a plain string as one text block)."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def text_of(block: Json) -> str:
    """The text of a text block or a tool result."""
    content = block.get("text", block.get("content"))
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
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


def title(path: Path) -> str:
    found = ""
    for record in records(path):
        if record.get("type") == "ai-title":
            found = str(record.get("aiTitle") or record.get("title") or found)
    return found


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
        if kind == "attachment" and isinstance(attachment, dict):
            if attachment.get("type") == "hook_blocking_error":
                error = attachment.get("blockingError")
                answer = error.get("blockingError") if isinstance(error, dict) else error
                call = calls.get(str(attachment.get("toolUseID")), str(attachment.get("hookName")))
                yield Event(at, "hook_blocks", call, str(answer))
            elif attachment.get("type") == "diagnostics":
                yield Event(at, "diagnostics", "", json.dumps(attachment.get("files")))
        elif kind == "assistant":  # Claude went on: no interrupt followed the rejections
            yield from cancelled
            cancelled.clear()
        for block in contents(record):
            if kind == "assistant" and block.get("type") == "tool_use":
                calls[str(block.get("id"))] = call_of(block)
            elif kind == "user" and block.get("type") == "tool_result":
                answer, call = text_of(block), calls.get(str(block.get("tool_use_id")), "")
                if any(marker in answer[:300] for marker in REJECTED):
                    cancelled.append(Event(at, "rejected", call, answer))
                elif block.get("is_error"):
                    yield Event(at, "tool_errors", call, answer)
            elif kind == "user" and block.get("type") == "text" and text_of(block).startswith(INTERRUPTED):
                yield Event(at, "interrupts", "; ".join(event.call for event in cancelled), text_of(block))
                cancelled.clear()
    yield from cancelled


def call_of(block: Json) -> str:
    """A tool use in short: the tool and its command or file (else its whole input)."""
    tool_input = block.get("input")
    told = tool_input.get("command") or tool_input.get("file_path") if isinstance(tool_input, dict) else None
    return f"{block.get('name')}: {told or tool_input}"


def command_beginnings(path: Path, since: datetime | None = None) -> Counter[str]:
    """How often each beginning (two words) of a Bash command occurs in a session."""
    found = Counter[str]()
    for record in records(path, since):
        for block in contents(record):
            tool_input = block.get("input")
            command = tool_input.get("command") if isinstance(tool_input, dict) else None
            if record.get("type") == "assistant" and block.get("name") == "Bash" and isinstance(command, str):
                found[" ".join(command.split()[:2])] += 1
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


def log_friction(path: Path) -> None:
    """Appends a session's friction to the log: what came after the log's last line about the session or, if
    later, the last retrospective."""
    counts = Counter(event.kind for event in events(path, last_logged(path.stem)))
    append_log({"session": path.stem, **{kind: counts[kind] for kind in KINDS}})


def append_log(entry: Json) -> None:
    FRICTION_LOG.parent.mkdir(exist_ok=True)
    with FRICTION_LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), **entry}) + "\n")


def logged() -> list[Json]:
    """The lines of the friction log."""
    if not FRICTION_LOG.exists():
        return []
    return [json.loads(line) for line in FRICTION_LOG.read_text(encoding="utf-8").splitlines()]


def last_logged(session: str | None = None) -> datetime | None:
    """When the friction log last got a retrospective or, with `session`, a line of that session."""
    times = [
        str(entry.get("at"))
        for entry in logged()
        if entry.get("retro") or (session is not None and entry.get("session") == session)
    ]
    return datetime.fromisoformat(times[-1]) if times else None


def since_last_retro() -> list[Json]:
    """The sessions' lines after the last retrospective."""
    entries: list[Json] = []
    for entry in logged():
        entries = [] if entry.get("retro") else [*entries, entry]
    return entries


def show_list(count: int) -> None:
    for path in transcripts()[-count:]:
        found = list(prompts(path))
        started = found[0][0] if found else ""
        print(
            f"{path.stem[:8]}  {started:16}  {path.stat().st_size // 1024:6} KB  {len(found):3} prompts  {title(path)}"
        )


def show_search(term: str, count: int, *, everything: bool) -> None:
    pattern = re.compile(term, re.IGNORECASE)
    for path in transcripts()[-count:]:
        for at, who, text in hits(path, everything=everything):
            for match in pattern.finditer(text):
                start = max(0, match.start() - 150)
                excerpt = " ".join(text[start : match.end() + 150].split())
                print(f"{path.stem[:8]} {at} {who}: …{excerpt}…")


def hits(path: Path, *, everything: bool) -> Iterator[tuple[str, str, str]]:
    if not everything:
        yield from ((at, "USER", text) for at, text in prompts(path))
        return
    for record in records(path):
        if record.get("type") in ("user", "assistant") and not record.get("isMeta"):
            for block in contents(record):
                if block.get("type") == "text":
                    yield str(record.get("timestamp", ""))[:16], str(record["type"]).upper(), text_of(block)


def show_friction(paths: list[Path], since: datetime | None, *, details: bool, commands: bool) -> None:
    if since is not None:
        print(f"since the retrospective of {since:%Y-%m-%d %H:%M} (UTC)")
    found = {path: list(events(path, since)) for path in paths}
    print("session   " + "  ".join(f"{kind:>11}" for kind in KINDS))
    for path, session_events in found.items():
        counts = Counter(event.kind for event in session_events)
        print(f"{path.stem[:8]}  " + "  ".join(f"{counts[kind]:11}" for kind in KINDS))
    if details:
        for path, session_events in found.items():
            for event in session_events:
                print(f"\n{path.stem[:8]} {event.at[:16]} {event.kind}: {shown(event.call)}\n    {shown(event.answer)}")
    if commands:
        total = Counter[str]()
        for path in paths:
            total.update(command_beginnings(path, since))
        print("\nmost frequent Bash commands (first two words):")
        for command, times in total.most_common(25):
            print(f"{times:5}  {command}")


def shown(text: str) -> str:
    """`text` on one line, its first `SHOWN` characters."""
    return " ".join(text.split())[:SHOWN]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("-n", type=int, default=30, help="the last N sessions")
    prompting = actions.add_parser("prompts")
    prompting.add_argument("session")
    searching = actions.add_parser("search")
    searching.add_argument("term")
    searching.add_argument("-n", type=int, default=1000, help="the last N sessions")
    searching.add_argument("--all", action="store_true", help="also Claude's text")
    counting = actions.add_parser("friction")
    counting.add_argument("sessions", nargs="*")
    counting.add_argument("-n", type=int, default=5, help="the last N sessions (without SESSION)")
    counting.add_argument("--since-retro", action="store_true", help="only what came after the last retrospective")
    counting.add_argument("--details", action="store_true", help="each piece of friction: the call and its answer")
    counting.add_argument("--commands", action="store_true", help="the most frequent Bash command beginnings")
    actions.add_parser("mark-retro")
    args = parser.parse_args()
    match args.action:
        case "list":
            show_list(args.n)
        case "prompts":
            for at, text in prompts(find(args.session)):
                print(f"[{at}] {text}\n")
        case "search":
            show_search(args.term, args.n, everything=args.all)
        case "friction":
            since = last_logged() if args.since_retro else None
            paths = [find(prefix) for prefix in args.sessions]
            if not paths:
                recent = transcripts()
                paths = (
                    recent[-args.n :]
                    if since is None
                    else [path for path in recent if datetime.fromtimestamp(path.stat().st_mtime, UTC) > since]
                )
            show_friction(paths, since, details=args.details, commands=args.commands)
        case _:
            append_log({"retro": True})
    return 0


if __name__ == "__main__":
    sys.exit(main())
