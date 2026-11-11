"""Reads the Claude Code transcripts of this project: past sessions, their prompts and their friction.

Run:  python bin/sessions.py list [-n N]                  sessions (newest last): start, title, size, prompts
      python bin/sessions.py prompts SESSION              the user's prompts of a session (an id prefix)
      python bin/sessions.py search TERM [-n N] [--all]   the prompts (`--all`: also Claude's text) matching TERM
      python bin/sessions.py friction [SESSION ...] [-n N] [--since-retro] [--details] [--commands]
                                                          friction per session (default: the last 5)
      python bin/sessions.py mark-retro                   records a retrospective in the friction log

TERM is a case-insensitive regular expression. Where the transcripts are and how they are read:
`strom_tools.sessions.transcripts`.

`friction` shows a column per kind of friction (`strom_tools.sessions.friction.Kind`: hook blocks, tool errors,
rejections, interrupts, IDE diagnostics). `--since-retro` takes the sessions that went on after the last
retrospective, and of each only what came after it; `--details` lists each piece of friction, the tool call and
its answer; `--commands` the most frequent Bash command beginnings, candidates for a script or a make target.
`mark-retro` (run by the skill `retro`) starts the count of the friction log anew; what its lines count:
`strom_tools.sessions.friction`.
"""

import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import assert_never

from strom_tools.commands import command_line
from strom_tools.sessions import friction, transcripts
from strom_tools.sessions.friction import Kind
from strom_tools.workspace.repository import Repository, this_repository

_SHOWN = 300
"""How many characters of a call and of its answer `--details` shows."""


def _show_list(repository: Repository, num_sessions: int) -> None:
    for path in transcripts.transcripts(repository)[-num_sessions:]:
        found = list(transcripts.prompts(path))
        started_at = transcripts.minute(found[0].at) if found else ""
        size = path.stat().st_size // 1024
        print(f"{path.stem[:8]}  {started_at:16}  {size:6} KB  {len(found):3} prompts  {transcripts.title(path)}")


def _show_search(repository: Repository, term: str, num_sessions: int, *, everything: bool) -> None:
    pattern = re.compile(term, re.IGNORECASE)
    for path in transcripts.transcripts(repository)[-num_sessions:]:
        for said in transcripts.texts(path, everything=everything):
            for match in pattern.finditer(said.text):
                start = max(0, match.start() - 150)
                excerpt = " ".join(said.text[start : match.end() + 150].split())
                print(f"{path.stem[:8]} {transcripts.minute(said.at)} {said.author.name}: …{excerpt}…")


def _show_friction(paths: Sequence[Path], since: datetime | None, *, details: bool, commands: bool) -> None:
    if since is not None:
        print(f"since the retrospective of {since:%Y-%m-%d %H:%M} (UTC)")
    found = {path: list(friction.events(path, since)) for path in paths}
    print("session   " + "  ".join(f"{kind.value:>11}" for kind in Kind))
    for path, session_events in found.items():
        counts = friction.counted(session_events)
        print(f"{path.stem[:8]}  " + "  ".join(f"{counts[kind]:11}" for kind in Kind))
    if details:
        for path, session_events in found.items():
            for event in session_events:
                at, kind = transcripts.minute(event.at), event.kind.value
                print(f"\n{path.stem[:8]} {at} {kind}: {_shown(event.call)}\n    {_shown(event.answer)}")
    if commands:
        total = Counter[str]()
        for path in paths:
            total.update(friction.command_beginnings(path, since))
        print("\nmost frequent Bash commands (first two words):")
        for command, num_uses in total.most_common(25):
            print(f"{num_uses:5}  {command}")


def _shown(text: str) -> str:
    """`text` on one line, its first `_SHOWN` characters."""
    return " ".join(text.split())[:_SHOWN]


class _Action(Enum):
    LIST = "list"
    PROMPTS = "prompts"
    SEARCH = "search"
    FRICTION = "friction"
    MARK_RETRO = "mark-retro"


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
    chosen: str = args.action
    action = _Action(chosen)
    repository = this_repository()
    match action:
        case _Action.LIST:
            num_listed: int = args.n
            _show_list(repository, num_listed)
        case _Action.PROMPTS:
            session: str = args.session
            for said in transcripts.prompts(transcripts.find(repository, session)):
                print(f"[{transcripts.minute(said.at)}] {said.text}\n")
        case _Action.SEARCH:
            term: str = args.term
            num_searched: int = args.n
            everything: bool = args.all
            _show_search(repository, term, num_searched, everything=everything)
        case _Action.FRICTION:
            prefixes: list[str] = args.sessions
            num_recent: int = args.n
            since_retro: bool = args.since_retro
            details: bool = args.details
            commands: bool = args.commands
            since = friction.last_logged(repository) if since_retro else None
            paths = friction.covered(repository, prefixes, num_recent, since)
            _show_friction(paths, since, details=details, commands=commands)
        case _Action.MARK_RETRO:
            friction.log_retro(repository)
        case _:
            assert_never(action)
    return 0
