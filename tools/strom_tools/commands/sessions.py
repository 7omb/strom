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
`strom_tools.hooks.friction_notes`) and one per retrospective (`mark-retro`, run by the skill `retro`). A
session's line counts what came after the log's last line about that session or, if later, the last
retrospective: so the lines after a retrospective add up (the SessionStart hook sums them), also those of a
session that was resumed or that ran the retrospective itself.
"""

import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from strom_tools.commands import command_line
from strom_tools.sessions import friction, transcripts
from strom_tools.workspace.repository import Repository, this_repository

_SHOWN = 300
"""How many characters of a call and of its answer `--details` shows."""


def _show_list(repository: Repository, count: int) -> None:
    for path in transcripts.transcripts(repository)[-count:]:
        found = list(transcripts.prompts(path))
        started = found[0][0] if found else ""
        size = path.stat().st_size // 1024
        print(f"{path.stem[:8]}  {started:16}  {size:6} KB  {len(found):3} prompts  {transcripts.title(path)}")


def _show_search(repository: Repository, term: str, count: int, *, everything: bool) -> None:
    pattern = re.compile(term, re.IGNORECASE)
    for path in transcripts.transcripts(repository)[-count:]:
        for at, who, text in transcripts.texts(path, everything=everything):
            for match in pattern.finditer(text):
                start = max(0, match.start() - 150)
                excerpt = " ".join(text[start : match.end() + 150].split())
                print(f"{path.stem[:8]} {at} {who}: …{excerpt}…")


def _show_friction(paths: Sequence[Path], since: datetime | None, *, details: bool, commands: bool) -> None:
    if since is not None:
        print(f"since the retrospective of {since:%Y-%m-%d %H:%M} (UTC)")
    found = {path: list(friction.events(path, since)) for path in paths}
    print("session   " + "  ".join(f"{kind:>11}" for kind in friction.KINDS))
    for path, session_events in found.items():
        counts = Counter(event.kind for event in session_events)
        print(f"{path.stem[:8]}  " + "  ".join(f"{counts[kind]:11}" for kind in friction.KINDS))
    if details:
        for path, session_events in found.items():
            for event in session_events:
                print(
                    f"\n{path.stem[:8]} {event.at[:16]} {event.kind}: {_shown(event.call)}\n    {_shown(event.answer)}"
                )
    if commands:
        total = Counter[str]()
        for path in paths:
            total.update(friction.command_beginnings(path, since))
        print("\nmost frequent Bash commands (first two words):")
        for command, times in total.most_common(25):
            print(f"{times:5}  {command}")


def _shown(text: str) -> str:
    """`text` on one line, its first `_SHOWN` characters."""
    return " ".join(text.split())[:_SHOWN]


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
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
    args = parser.parse_args(argv)
    action: str = args.action
    repository = this_repository()
    match action:
        case "list":
            count: int = args.n
            _show_list(repository, count)
        case "prompts":
            session: str = args.session
            for at, text in transcripts.prompts(transcripts.find(repository, session)):
                print(f"[{at}] {text}\n")
        case "search":
            term: str = args.term
            last: int = args.n
            everything: bool = args.all
            _show_search(repository, term, last, everything=everything)
        case "friction":
            prefixes: list[str] = args.sessions
            recent_count: int = args.n
            since_retro: bool = args.since_retro
            details: bool = args.details
            commands: bool = args.commands
            since = friction.last_logged(repository) if since_retro else None
            paths = [transcripts.find(repository, prefix) for prefix in prefixes]
            if not paths:
                recent = transcripts.transcripts(repository)
                paths = (
                    recent[-recent_count:]
                    if since is None
                    else [path for path in recent if datetime.fromtimestamp(path.stat().st_mtime, UTC) > since]
                )
            _show_friction(paths, since, details=details, commands=commands)
        case _:
            friction.log_retro(repository)
    return 0
