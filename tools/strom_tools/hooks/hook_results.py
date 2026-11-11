"""What a Claude Code hook answers, as data: a handler returns a `HookResult`, and `answer` turns the results of all
handlers of an event into what the hook command prints and exits with: exit code 2 blocks and sends stderr to
Claude; stdout holds one JSON object with the notes.

A note beside a block is printed too. The hooks reference (read 2026-11-11) says of exit code 2: "Claude Code
still reads the JSON output fields, but they can't override the block", and that a blocking decision in the JSON
would replace stderr as the message: the JSON here holds none. Not observed on a running session; a handler whose
note must not be lost returns it again while it holds (`friction_notes.at_stop`, until a stop that is not
blocked), at the price of a note shown twice."""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from strom_tools.hooks.hook_events import HookEvent, SessionEnded, SessionStarted, ToolUsed, TurnEnded
from strom_tools.json_objects import JsonObject

CONTEXT_LIMIT = 10_000
"""The characters Claude Code takes of `additionalContext`, and of `systemMessage`, in one hook output (hooks
reference, read 2026-11-11): a longer text goes to a file, of which Claude sees a preview (2026-11-11: three
rules in one note of 23.5 KB)."""


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
        output["systemMessage"] = _within_limit(for_user)
    if for_claude:
        context: JsonObject = {"hookEventName": _name_of(event), "additionalContext": _within_limit(for_claude)}
        output["hookSpecificOutput"] = context
    told = [result.message for result in results if isinstance(result, Block | Failed)]
    return Answer(
        2 if blocks else 1 if failures else 0,
        f"{json.dumps(output)}\n" if output else "",
        "".join(f"{message}\n" for message in told),
    )


def _within_limit(texts: Sequence[str]) -> str:
    """The texts joined, each whole while it fits into `CONTEXT_LIMIT`; one that does not is replaced by a line
    saying so (left out too where that line does not fit)."""
    kept: list[str] = []
    for text in texts:
        for candidate in (text, f"(a note of {len(text)} characters was left out: over Claude Code's limit)"):
            if len("\n\n".join([*kept, candidate])) <= CONTEXT_LIMIT:
                kept.append(candidate)
                break
    return "\n\n".join(kept)


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
