"""Reads the Claude Code transcripts of this project: past sessions, their prompts and their friction.

Run:  python bin/sessions.py list [-n N]                  sessions (newest last): start, title, size, prompts
      python bin/sessions.py prompts SESSION              the user's prompts of a session (an id prefix)
      python bin/sessions.py search TERM [-n N] [--all]   the prompts (`--all`: also Claude's text) matching TERM
      python bin/sessions.py friction [SESSION ...] [-n N] [--commands]
                                                          friction per session (default: the last 5)
      python bin/sessions.py mark-retro                   records a retrospective in the friction log

The transcripts are `~/.claude/projects/<this path, non-alphanumerics as ->/*.jsonl` (`CLAUDE_CONFIG_DIR`
replaces `~/.claude`), one JSON object per line; their format is Claude Code's own and not documented, so the
reading is lenient. TERM is a case-insensitive regular expression.

Friction counts what cost a session round trips: hook blocks (`hook_blocks`), tool errors other than
rejections (`tool_errors`), tool calls the user or the permission check rejected (`rejected`), interrupts by
the user (`interrupts`) and diagnostics the IDE attached after edits (`diagnostics`, often stale). With
`--commands`, the most frequent Bash command beginnings, candidates for a script or a make target.

The friction log `.checks/friction.jsonl` gets one line per ended session (written by the SessionEnd hook,
`.claude/hooks/friction.py`) and one per retrospective (`mark-retro`, run by the skill `retro`); the
SessionStart hook sums the sessions since the last retrospective. Standard library only: the hooks import
this module with the dev shell's Python.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRICTION_LOG = ROOT / ".checks" / "friction.jsonl"
INTERRUPTED = "[Request interrupted by user"
REJECTED = ("The user doesn't want to proceed", "Permission for this", "denied by")

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


def records(path: Path) -> Iterator[Json]:
    """The JSON objects of a transcript, without those of subagents (`isSidechain`)."""
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and not record.get("isSidechain"):
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


@dataclass
class Friction:
    session: str
    hook_blocks: int = 0
    tool_errors: int = 0
    rejected: int = 0
    interrupts: int = 0
    diagnostics: int = 0
    commands: Counter[str] = field(default_factory=Counter[str])

    def total(self) -> int:
        return self.hook_blocks + self.tool_errors + self.rejected + self.interrupts


def friction(path: Path) -> Friction:
    found = Friction(path.stem)
    for record in records(path):
        kind = record.get("type")
        if kind == "attachment":
            attachment = record.get("attachment")
            attached = attachment.get("type") if isinstance(attachment, dict) else None
            found.hook_blocks += attached == "hook_blocking_error"
            found.diagnostics += attached == "diagnostics"
        for block in contents(record):
            if kind == "assistant" and block.get("type") == "tool_use" and block.get("name") == "Bash":
                tool_input = block.get("input")
                command = tool_input.get("command") if isinstance(tool_input, dict) else None
                if isinstance(command, str):
                    found.commands[" ".join(command.split()[:2])] += 1
            elif kind == "user" and block.get("type") == "tool_result":
                result = text_of(block)
                if any(marker in result[:300] for marker in REJECTED):
                    found.rejected += 1
                elif block.get("is_error"):
                    found.tool_errors += 1
            elif kind == "user" and block.get("type") == "text" and text_of(block).startswith(INTERRUPTED):
                found.interrupts += 1
    return found


def log_friction(found: Friction) -> None:
    """Appends a session's counts to the friction log."""
    entry = {key: value for key, value in asdict(found).items() if key != "commands"}
    append_log({"at": datetime.now(UTC).isoformat(timespec="seconds"), **entry})


def append_log(entry: Json) -> None:
    FRICTION_LOG.parent.mkdir(exist_ok=True)
    with FRICTION_LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry) + "\n")


def since_last_retro() -> list[Json]:
    """The logged sessions after the last retrospective."""
    if not FRICTION_LOG.exists():
        return []
    entries: list[Json] = []
    for line in FRICTION_LOG.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
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


def show_friction(paths: list[Path], *, commands: bool) -> None:
    columns = ["hook_blocks", "tool_errors", "rejected", "interrupts", "diagnostics"]
    print("session   " + "  ".join(f"{column:>11}" for column in columns))
    total = Counter[str]()
    for path in paths:
        found = friction(path)
        counts = asdict(found)
        print(f"{found.session[:8]}  " + "  ".join(f"{counts[column]:11}" for column in columns))
        total.update(found.commands)
    if commands:
        print("\nmost frequent Bash commands (first two words):")
        for command, times in total.most_common(25):
            print(f"{times:5}  {command}")


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
    counting.add_argument("--commands", action="store_true")
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
            paths = [find(prefix) for prefix in args.sessions] or transcripts()[-args.n :]
            show_friction(paths, commands=args.commands)
        case _:
            append_log({"at": datetime.now(UTC).isoformat(timespec="seconds"), "retro": True})
    return 0


if __name__ == "__main__":
    sys.exit(main())
