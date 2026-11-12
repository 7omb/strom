import pytest
from tool_helpers import write

from strom_tools.hooks.command_guards import _simple_commands, before_bash
from strom_tools.hooks.hook_events import Session, ToolRequested
from strom_tools.hooks.hook_results import Block
from strom_tools.workspace.repository import Repository

SESSION = Session("abcd", None)


@pytest.fixture
def guarded(repository: Repository) -> Repository:
    write(repository, "src/strom/_parts/shards.py", "LIMIT = 3\n")
    write(repository, ".checks/probe.py", "")
    return repository


def refusal(repository: Repository, command: str) -> str | None:
    result = before_bash(repository, ToolRequested(SESSION, "Bash", command))
    assert result is None or isinstance(result, Block)
    return None if result is None else result.message


@pytest.mark.parametrize(
    ("command", "refused_for"),
    [
        ("sed -i 's/3/4/' src/strom/_parts/shards.py", "`sed -i` on src/strom/_parts/shards.py"),
        ("cd /x && sed -E -i.bak -e 's/a/b/' src/strom/_parts/shards.py", "`sed -i`"),
        ("sed --in-place 's/a/b/' src/strom/_parts/shards.py", "`sed -i`"),
        ("perl -pi -e 's/a/b/' src/strom/_parts/shards.py", "`perl -i`"),
        ("timeout 300 uv run --frozen python bin/mutant.py --replace a b c", "`timeout` kills"),
        ("timeout -k 5 600 python bin/ab.py HEAD .", "`timeout` kills"),
        ("git stash", "`git stash`"),
        ("git stash -u", "`git stash`"),
        ("git stash save wip", "`git stash`"),
        ("git add -A", "`git add` writes the index"),
        ("cd sub && git add x", "`git add`"),
        ("git -C . add x", "`git add`"),
        ("ls; git reset --hard", "`git reset`"),
        ("git restore --staged a.py", "`git restore`"),
        ("git read-tree HEAD", "`git read-tree`"),
        ("echo ok\ngit commit -m x", "`git commit`"),
    ],
)
def test_a_command_against_an_agreement_is_refused_with_what_to_do(
    guarded: Repository, command: str, refused_for: str
) -> None:
    message = refusal(guarded, command)
    assert message is not None and refused_for in message


@pytest.mark.parametrize(
    "command",
    [
        "sed -n 1,20p src/strom/_parts/shards.py",  # a read
        "sed -i 's/a/b/' .checks/probe.py",  # generated files
        "sed -i 's/a/b/' /tmp/somewhere/probe.py",  # outside the repository
        "sed -i 's/a/b/' src/strom/_parts/missing.py",  # nothing to edit
        "timeout 120 uv run --frozen pytest -q",
        "uv run --frozen python bin/mutant.py --timeout 60 --replace a b c",
        "git stash create",
        "git stash list",
        "GIT_INDEX_FILE=/tmp/x/index git read-tree HEAD && GIT_INDEX_FILE=/tmp/x/index git add -A",
        "env GIT_INDEX_FILE=/tmp/x/index git add -A",
        "git status --short; git diff --cached | head",
        "git restore src/strom/_parts/shards.py",  # the working tree only
        "grep -rn 'git add' docs  # a mention",
        "python3 - <<'EOF'\nimport subprocess\n# git add, in a comment of the input\nEOF",
        "echo 'unbalanced",
    ],
)
def test_other_commands_pass(guarded: Repository, command: str) -> None:
    assert refusal(guarded, command) is None


def test_every_refused_part_is_named_once(guarded: Repository) -> None:
    message = refusal(guarded, "git add a && git add b; git stash")
    assert message is not None
    assert message.count("`git add`") == 1 and message.count("`git stash`") == 1


def test_only_bash_is_guarded(guarded: Repository) -> None:
    assert before_bash(guarded, ToolRequested(SESSION, "Read", None)) is None


def test_simple_commands_are_split_at_operators_and_lines_but_not_inside_here_documents() -> None:
    command = "A=1 cmd x|other 'y z' && last\ncat <<EOF\nnot; a command\nEOF\nafter"
    assert list(_simple_commands(command)) == [
        ["A=1", "cmd", "x"],
        ["other", "y z"],
        ["last"],
        ["cat", "<<EOF"],
        ["after"],
    ]
