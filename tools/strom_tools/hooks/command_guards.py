"""Refuses a Bash command that breaks a working agreement before it runs (PreToolUse), saying what to do instead.

  `before_bash`   blocks a command any of whose simple commands
                  - edits a file of the repository in place (`sed -i`, `perl -i`): Edit and Write show the user a
                    diff and run the edit hook (`CLAUDE.md`, Process);
                  - wraps `bin/mutant.py` or `bin/ab.py` in `timeout`, which kills the script before its verdict and
                    orphans its pytest and forkserver workers: they have their own limits;
                  - runs a bare `git stash` (or `stash save`): its `pop` without `--index` unstages what the user
                    staged; `git stash create` changes nothing;
                  - writes the index without `GIT_INDEX_FILE` set (`add`, `rm`, `mv`, `reset`, `read-tree`,
                    `update-index`, `restore --staged`, `commit`): the index is the user's
                    (`docs/decisions/git-index.md`), and a prefix rule of `.claude/settings.json` misses
                    `cd x && git add` or `git -C x add`.

A simple command is a part between `;`, `&&`, `||`, `|` and newlines; the lines of a here-document are its
input, not commands. A command that `shlex` cannot split is let through: the guard prevents slips, it is no
sandbox."""

import re
import shlex
from collections.abc import Iterator, Sequence
from pathlib import Path

from strom_tools.hooks.hook_events import ToolRequested
from strom_tools.hooks.hook_results import Block, HookResult
from strom_tools.workspace.repository import Repository

_OPERATORS = set(";&|(){}")
"""What a token between simple commands consists of (`;`, `&&`, `||`, `|`, `&`, parentheses, braces)."""
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=.*")
_WRAPPERS = {"env", "nice", "nohup", "command", "exec", "time"}
"""Words in front of a command that run it."""
_GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
_WRITES_INDEX = {"add", "stage", "rm", "mv", "reset", "read-tree", "update-index", "commit"}
_STASH_CHANGES = {"push", "pop", "apply", "drop", "save", "clear"}
_TIMED_SCRIPTS = ("bin/mutant.py", "bin/ab.py")


def before_bash(repository: Repository, event: ToolRequested) -> HookResult:
    if event.tool != "Bash" or event.command is None:
        return None
    reasons = [reason for words in _simple_commands(event.command) if (reason := _refused(repository, words))]
    once = [reason for number, reason in enumerate(reasons) if reason not in reasons[:number]]
    return Block("\n".join(once)) if reasons else None


def _simple_commands(command: str) -> Iterator[list[str]]:
    """The words of each simple command, with its leading assignments (`VAR=value`)."""
    for line in _command_lines(command):
        lexer = shlex.shlex(line, posix=True, punctuation_chars="".join(sorted(_OPERATORS)))
        lexer.whitespace_split = True
        lexer.commenters = "#"
        words: list[str] = []
        try:
            for token in lexer:
                if set(token) <= _OPERATORS:
                    if words:
                        yield words
                    words = []
                else:
                    words.append(token)
        except ValueError:  # unbalanced quotes
            return
        if words:
            yield words


def _command_lines(command: str) -> Iterator[str]:
    """The lines of `command` that hold commands: without the bodies of here-documents."""
    ends: list[str] = []
    for line in command.splitlines():
        if ends:
            if line.strip() == ends[0]:
                ends.pop(0)
            continue
        ends.extend(match.group(2) for match in _HEREDOC.finditer(line))
        yield line


def _refused(repository: Repository, words: Sequence[str]) -> str | None:
    """Why the simple command `words` is refused; None if it is not."""
    rest = list(words)
    assigned: set[str] = set()
    timed = False
    while rest:
        if _ASSIGNMENT.fullmatch(rest[0]):
            assigned.add(rest[0].split("=", 1)[0])
            rest = rest[1:]
        elif rest[0] == "timeout":
            timed = True
            rest = rest[1:]
            while rest and (rest[0].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?", rest[0])):
                rest = rest[1:]
        elif rest[0] in _WRAPPERS:
            rest = rest[1:]
        else:
            break
    if not rest:
        return None
    if timed and any(word.endswith(_TIMED_SCRIPTS) for word in rest):
        return (
            "`timeout` kills bin/mutant.py or bin/ab.py before its verdict and orphans its workers: use the script's "
            "own `--timeout` (mutant) or fewer runs and a narrower `-k` (ab), in the background."
        )
    match Path(rest[0]).name:
        case "sed" | "perl" if _in_place(rest[1:]) and (edited := _repository_files(repository, rest[1:])):
            return (
                f"`{rest[0]} -i` on {', '.join(edited)}: edit files of the repository with Edit or Write (they show "
                "the user a diff and run the edit hook); a rename or a move across many files: bin/rename.py."
            )
        case "git":
            return _refused_git(rest[1:], index_file="GIT_INDEX_FILE" in assigned)
        case _:
            return None


def _in_place(words: Sequence[str]) -> bool:
    """Whether the options of a `sed` or `perl` call (`words` after its name) edit files in place."""
    return any(
        word == "--in-place" or word.startswith("--in-place=") or re.fullmatch(r"-[a-zA-Z]*i\S*", word) is not None
        for word in words
        if word.startswith("-")
    )


def _repository_files(repository: Repository, words: Sequence[str]) -> list[str]:
    """The words that name a file of the repository outside `.checks/`, from its root."""
    found: list[str] = []
    for word in words:
        if word.startswith("-"):
            continue
        path = (repository.root / word).resolve()
        if path.is_file() and path.is_relative_to(repository.root):
            relative = path.relative_to(repository.root).as_posix()
            if not relative.startswith(".checks/"):
                found.append(relative)
    return found


def _refused_git(words: Sequence[str], *, index_file: bool) -> str | None:
    """Why a git call (`words` after `git`) is refused."""
    rest = list(words)
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in _GIT_OPTIONS_WITH_VALUE else rest[1:]
    if not rest:
        return None
    subcommand, arguments = rest[0], rest[1:]
    if subcommand == "stash" and (not arguments or arguments[0] in _STASH_CHANGES or arguments[0].startswith("-")):
        return (
            "`git stash` (bare, push, pop, apply, drop, save, clear) can unstage what the user staged: for a "
            "baseline of the working tree, bin/baseline.py; `git stash create` changes nothing."
        )
    staging = subcommand in _WRITES_INDEX or (
        subcommand == "restore" and any(word in ("--staged", "-S") or word.startswith("-S") for word in arguments)
    )
    if staging and not index_file:
        return (
            f"`git {subcommand}` writes the index, which is the user's (docs/decisions/git-index.md): leave staging "
            "to the user and name the command in the report; a baseline: bin/baseline.py; a scratch index: set "
            "GIT_INDEX_FILE on the command."
        )
    return None
