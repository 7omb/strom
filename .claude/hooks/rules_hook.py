"""Loads the `.claude/rules` that a Bash command touched (called by `dispatch.py`).

Claude Code loads a rule when Read, Edit or Write touch a file matching its `paths`, but not when a Bash
command reads the file (`cat`, `sed -n`, `grep`): half of the reads in past sessions were such commands, and
the rules loaded in few sessions. After a Bash command, this hook takes each word of it that names a file or
directory of the repository (a directory stands for the files in it), and adds each rule whose `paths` match
one to Claude's context: once per session, and not when the transcript shows Claude Code loaded it already.
"""

import json
import os
import re
import shlex
from pathlib import Path, PurePosixPath

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
RULES = ROOT / ".claude" / "rules"
LOADED = ROOT / ".checks" / "rules-loaded"
"""Per session, the rules this hook added (`<session id>.txt`; removed at the session's end)."""
SAMPLES = ("x.py", "x.md")
"""What a directory named in a command stands for: files of these kinds in it."""


def after_bash(event: dict[str, object]) -> int:
    tool_input = event.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    session = str(event.get("session_id", "unknown"))
    if not isinstance(command, str):
        return 0
    loaded_file = LOADED / f"{session}.txt"
    loaded = set(loaded_file.read_text().split()) if loaded_file.exists() else set()
    named = touched(command)
    new = [rule for rule, globs in rules() if rule.name not in loaded and matches(named, globs)]
    transcript = event.get("transcript_path")
    new = [rule for rule in new if not (isinstance(transcript, str) and loaded_natively(Path(transcript), rule))]
    if not new:
        return 0
    LOADED.mkdir(parents=True, exist_ok=True)
    loaded_file.write_text(" ".join(sorted(loaded | {rule.name for rule in new})))
    context = "\n\n".join(f"Contents of {rule.relative_to(ROOT)}:\n\n{body(rule)}" for rule in new)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}}))
    return 0


def touched(command: str) -> list[PurePosixPath]:
    """The repository paths that words of `command` name (relative; directories as sample files in them)."""
    try:
        words = shlex.split(command, comments=True)
    except ValueError:  # unbalanced quotes: a rough split is good enough
        words = command.split()
    found: list[PurePosixPath] = []
    for word in words:
        for part in re.split(r"[=:,;|&<>()]", word):
            path = (ROOT / part).resolve() if part and not part.startswith("-") else None
            if path is None or not path.is_relative_to(ROOT) or not path.exists():
                continue
            relative = PurePosixPath(path.relative_to(ROOT).as_posix())
            found.extend([relative / sample for sample in SAMPLES] if path.is_dir() else [relative])
    return found


def rules() -> list[tuple[Path, list[str]]]:
    """Each rule file with the globs of its `paths` frontmatter."""
    found: list[tuple[Path, list[str]]] = []
    for rule in sorted(RULES.glob("*.md")):
        header = rule.read_text().split("---")
        if len(header) >= 3:
            found.append((rule, re.findall(r'^\s*-\s*"?([^"\n]+?)"?\s*$', header[1], re.MULTILINE)))
    return found


def matches(paths: list[PurePosixPath], globs: list[str]) -> bool:
    return any(path.full_match(glob) for path in paths for glob in globs)


def loaded_natively(transcript: Path, rule: Path) -> bool:
    """Whether Claude Code loaded `rule` itself in this session (an attachment naming it)."""
    if not transcript.exists():
        return False
    with transcript.open(encoding="utf-8") as lines:
        return any('"nested_memory"' in line and str(rule) in line for line in lines)


def body(rule: Path) -> str:
    return rule.read_text().split("---", 2)[2].strip()
