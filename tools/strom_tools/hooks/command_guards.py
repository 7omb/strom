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
                  To a subagent whose definition says that it changes nothing (`_CHANGE_NOTHING`) it also blocks
                  what writes the repository outside `.checks/`: a redirection into a file, `rm`, `mv`, `cp`,
                  `tee` and their like, a git call that changes the working tree, and the fixers.

A simple command is a part between `;`, `&&`, `||`, `|` and newlines; the lines of a here-document are its
input, not commands. A command that `shlex` cannot split is let through: the guard prevents slips, it is no
sandbox."""

import re
import shlex
from collections.abc import Iterator, Sequence
from itertools import pairwise
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
_CHANGE_NOTHING = {"reviewer", "researcher"}
"""The subagents whose definitions (`.claude/agents/`) say that they change nothing in the repository."""
_REDIRECTIONS = {">", ">>", ">|", "&>", "&>>"}
_WRITERS = {"rm", "mv", "tee", "touch", "mkdir", "rmdir", "truncate", "ln"}
"""Commands that write each path they name; `cp` writes its last."""
_CHANGES_WORKING_TREE = {
    "checkout",
    "switch",
    "restore",
    "apply",
    "am",
    "clean",
    "merge",
    "rebase",
    "cherry-pick",
    "revert",
    "pull",
}
_NOTHING_CHANGED = (
    "this subagent changes nothing in the repository (its definition in .claude/agents/): write a probe or a copy "
    "outside the repository or into .checks/, and leave the change to the session that called you."
)


def before_bash(repository: Repository, event: ToolRequested) -> HookResult:
    if event.tool != "Bash" or event.command is None:
        return None
    read_only = event.agent_type in _CHANGE_NOTHING
    reasons = [
        reason
        for words in _simple_commands(event.command)
        if (reason := _refused(repository, words, read_only=read_only))
    ]
    if read_only and (redirected := _inside(repository, list(_redirected(event.command)))):
        reasons.append(f"a redirection writes {', '.join(redirected)}: {_NOTHING_CHANGED}")
    once = [reason for number, reason in enumerate(reasons) if reason not in reasons[:number]]
    return Block("\n".join(once)) if reasons else None


def _redirected(command: str) -> Iterator[str]:
    """The files the redirections of `command` write (`> file`, `2>>file`); a `>` inside quotes is none."""
    for line in _command_lines(command):
        lexer = shlex.shlex(line, posix=False, punctuation_chars=True)  # not posix: a quoted word keeps its quotes
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:  # unbalanced quotes
            return
        for token, target in pairwise(tokens):
            if token in _REDIRECTIONS:
                yield target.strip("'\"")


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


def _refused(repository: Repository, words: Sequence[str], *, read_only: bool) -> str | None:
    """Why the simple command `words` is refused; None if it is not. `read_only`: its caller changes nothing in
    the repository."""
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
        case "git" if reason := _refused_git(rest[1:], index_file="GIT_INDEX_FILE" in assigned):
            return reason
        case _:
            written = _written(repository, rest) if read_only else None
            return None if written is None else f"{written}: {_NOTHING_CHANGED}"


def _written(repository: Repository, words: Sequence[str]) -> str | None:
    """What the simple command `words` (from its name on) writes in the repository, as far as this guard knows
    the command; None if nothing."""
    command = _run_by_uv(words)
    if not command:
        return None
    name, arguments = Path(command[0]).name, command[1:]
    named = [word for word in arguments if not word.startswith("-")]
    match name:
        case "cp" if inside := _inside(repository, named[-1:]):
            return f"`cp` writes {', '.join(inside)}"
        case _ if name in _WRITERS and (inside := _inside(repository, named)):
            return f"`{name}` writes {', '.join(inside)}"
        case "git" if (call := _git_call(arguments)) and call[0] in _CHANGES_WORKING_TREE:
            return f"`git {call[0]}` changes the working tree"
        case "make" if "fix" in arguments:
            return "`make fix` rewrites files"
        case "ruff" if arguments[:1] == ["format"] and not {"--check", "--diff"} & set(arguments):
            return "`ruff format` rewrites files"
        case "ruff" if arguments[:1] == ["check"] and "--fix" in arguments:
            return "`ruff check --fix` rewrites files"
        case _:
            return None


def _run_by_uv(words: Sequence[str]) -> list[str]:
    """The command that `uv run` runs, after its options; `words` themselves for another command."""
    if list(words[:2]) != ["uv", "run"]:
        return list(words)
    rest = list(words[2:])
    while rest and rest[0].startswith("-"):
        rest = rest[1:]
    return rest


def _in_place(words: Sequence[str]) -> bool:
    """Whether the options of a `sed` or `perl` call (`words` after its name) edit files in place."""
    return any(
        word == "--in-place" or word.startswith("--in-place=") or re.fullmatch(r"-[a-zA-Z]*i\S*", word) is not None
        for word in words
        if word.startswith("-")
    )


def _repository_files(repository: Repository, words: Sequence[str]) -> list[str]:
    """The words that name a file of the repository outside `.checks/`, from its root."""
    return [path for path in _inside(repository, words) if (repository.root / path).is_file()]


def _inside(repository: Repository, words: Sequence[str]) -> list[str]:
    """The words that name a path in the repository outside `.checks/` (it need not exist), from its root; an
    option and a word that the shell expands (`~`, `$`) name none."""
    found: list[str] = []
    for word in words:
        if word.startswith(("-", "~", "$")):
            continue
        path = (repository.root / word).resolve()
        if path != repository.root and path.is_relative_to(repository.root):
            relative = path.relative_to(repository.root).as_posix()
            if relative != ".checks" and not relative.startswith(".checks/"):
                found.append(relative)
    return found


def _git_call(words: Sequence[str]) -> list[str]:
    """The subcommand of a git call and its arguments (`words` after `git`, without git's own options)."""
    rest = list(words)
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in _GIT_OPTIONS_WITH_VALUE else rest[1:]
    return rest


def _refused_git(words: Sequence[str], *, index_file: bool) -> str | None:
    """Why a git call (`words` after `git`) is refused."""
    rest = _git_call(words)
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
