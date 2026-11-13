import pytest
from tool_helpers import commit, write

from strom_tools.docs_check.doc_problems import (
    _MISSING,
    NOTE_LIMIT,
    SESSION_DOC_LIMIT,
    UNTRACKED,
    LongLine,
    MissingCitation,
    UntrackedCitation,
    _citation,
    _DottedName,
    _file_set,
    _GlobCitation,
    _listed,
    _PathCitation,
    _top_level_names,
    docs,
    known,
    problems,
    rendered,
)
from strom_tools.workspace.repository import Repository


@pytest.fixture
def documented(repository: Repository) -> Repository:
    """A repository with a library module, a tool module, a test, docs and an ignored directory, all tracked; and
    one file that is not."""
    write(repository, ".gitignore", ".checks/\n")
    write(repository, "src/strom/__init__.py", "")
    write(repository, "src/strom/_parts/shards.py", "import os\n\nLIMIT = 3\n\n\nclass Shards:\n    size: int\n")
    write(repository, "tools/strom_tools/renames.py", "def scan() -> None: ...\n")
    write(repository, "tests/test_pools.py", "")
    write(repository, "docs/plans/topic.md", "")
    write(repository, "ARCHITECTURE.md", "")
    commit(repository)
    write(repository, "bin/new.py", "")
    return repository


def check(repository: Repository, text: str, name: str = "docs/doc.md") -> list[str]:
    """The problems of a doc with `text`, as printed without the `FILE:LINE: ` in front of each."""
    doc = write(repository, name, text)
    return [rendered(problem).split(": ", 1)[1] for problem in problems(doc, known(repository))]


@pytest.mark.parametrize(
    "reference",
    [
        "src/strom/_parts/shards.py",  # a tracked file
        "src/strom/_parts/",  # a directory of one
        "docs/plans",
        "plans/topic.md",  # from the citing doc's directory
        "shards.py",  # a bare file name, anywhere
        "_parts/shards.py",  # the end of a tracked path
        "tests/**",  # a glob
        "src/strom/_parts/shards.py:12",
        "src/strom/_parts/shards.py:12-14",
        "tests/test_pools.py::test_open",
        ".checks/snapshot.txt",  # ignored: generated, need not exist
        "strom",
        "strom._parts.shards",  # a module
        "strom._parts.shards.Shards",  # a top-level name
        "strom._parts.shards.LIMIT",
        "strom._parts.shards.os",
        "strom._parts.shards.Shards.size",  # deeper attributes are not checked
        "strom_tools.renames.scan",  # a name of the tools, in their source root
        "make check",  # no path
        "tracked_a/b/c",  # a notation: its first part is nowhere
        "a / b",
        "Shards.open(cpu_workers=2)",
        "<topic>.md",
        "docs/plans/….md",
        "~/.claude/projects",
        "/proc/cpuinfo",
        "https://example.org/a.py",
        "--benchmark-json=out.json",
    ],
)
def test_a_reference_to_what_is_tracked_or_to_no_path_is_fine(documented: Repository, reference: str) -> None:
    assert check(documented, f"See `{reference}` for it.\n") == []


@pytest.mark.parametrize(
    "reference",
    [
        "bin/nope.py",
        "docs/nope/",
        "nope.py",
        "_stages/shards.py",
        "tests/nope*",
        "bin/nope.py:12",
        "strom.nope",
        "strom._parts.shards.Nope",
        "strom_tools.renames.nope",
        "strom_tools.shards",
    ],
)
def test_a_reference_to_what_is_not_there_is_a_problem(documented: Repository, reference: str) -> None:
    assert check(documented, f"See `{reference}` for it.\n") == [f"{reference}{_MISSING}"]


def test_an_untracked_file_is_a_problem_until_it_is_added(documented: Repository) -> None:
    assert check(documented, "The script `bin/new.py`.\n") == [f"bin/new.py{UNTRACKED}"]
    commit(documented)
    assert check(documented, "The script `bin/new.py`.\n") == []


def test_a_deleted_file_is_a_problem_before_the_deletion_is_staged(documented: Repository) -> None:
    (documented.root / "tests/test_pools.py").unlink()
    assert check(documented, "See `tests/test_pools.py`.\n") == [f"tests/test_pools.py{_MISSING}"]


def test_code_blocks_and_rejected_alternatives_are_skipped_up_to_the_next_heading(documented: Repository) -> None:
    text = (
        "```\n`bin/in_a_block.py`\n```\n\n"
        "**Rejected**\n\n- `bin/old_name.py` (cited on purpose)\n- `bin/older.py`\n\n"
        "## Next\n\n`bin/after_the_heading.py`\n"
    )
    assert check(documented, text) == [f"bin/after_the_heading.py{_MISSING}"]


def test_a_problem_names_the_doc_and_the_line(documented: Repository) -> None:
    doc = write(documented, "docs/doc.md", "# Title\n\nBoth `bin/a.py` and\n`bin/new.py`.\n\n" + "x" * 121 + "\n")
    found = problems(doc, known(documented))
    assert found == [
        MissingCitation("docs/doc.md", 3, "bin/a.py"),
        UntrackedCitation("docs/doc.md", 4, "bin/new.py"),
        LongLine("docs/doc.md", 6, 121),
    ]
    assert [rendered(problem) for problem in found] == [
        f"docs/doc.md:3: bin/a.py{_MISSING}",
        f"docs/doc.md:4: bin/new.py{UNTRACKED}",
        "docs/doc.md:6: 121 characters (at most 120)",
    ]


def test_long_lines_are_problems_except_front_matter_urls_and_wide_tables(documented: Repository) -> None:
    long = "x" * 121
    text = f"---\ndescription: {long}\n---\n\n{long}\n\n{'y' * 120}\n\nhttps://example.org/{long}\n\n| {long} |\n"
    assert check(documented, text) == ["121 characters (at most 120)", "125 characters (at most 120)"]
    assert check(documented, f"| {long} |\n", "docs/research/tables.md") == []


def test_a_rules_file_needs_paths_that_match_tracked_files(documented: Repository) -> None:
    scoped = '---\npaths:\n  - "tests/**"\n  - "bin/new.py"\n  - "gone/**"\n---\n\n# Tests\n'
    assert check(documented, scoped, ".claude/rules/tests.md") == [
        f"bin/new.py{UNTRACKED}",  # there: a `git add` makes the note load for it
        "gone/** matches no tracked file: the note never loads for it",
    ]
    unscoped = check(documented, "# Notes\n", ".claude/rules/notes.md")
    assert unscoped == ["no `paths` in its front matter: Claude Code would load it in every session"]
    assert check(documented, "# Notes\n", "docs/notes.md") == [], "only a rules file needs paths"


def test_a_rules_file_stays_under_the_note_limit(documented: Repository) -> None:
    front = '---\npaths:\n  - "tests/**"\n---\n\n'
    body = "\n".join(["x" * 99] * (NOTE_LIMIT // 100))
    assert check(documented, f"{front}{body}\n", ".claude/rules/tests.md") == []
    assert check(documented, f"{front}{body}\nmore\n", ".claude/rules/tests.md") == [
        f"{len(body) + 5} characters of text (at most {NOTE_LIMIT}): a second topic, a note of its own"
    ]


def test_claude_md_stays_under_its_limit_in_bytes(documented: Repository) -> None:
    within = "".join(["ü" * 49 + "\n"] * 80)  # 7,920 bytes: two each
    assert len(within.encode()) <= SESSION_DOC_LIMIT
    assert check(documented, within, "CLAUDE.md") == []
    over = within + "ü" * 50 + "\n"  # 8,021 bytes in 4,021 characters
    (problem,) = check(documented, over, "CLAUDE.md")
    assert problem.startswith(f"8021 bytes (at most {SESSION_DOC_LIMIT}): every session loads it")
    assert check(documented, over, "docs/CLAUDE.md") == [], "only the one at the root"


def test_listed_takes_the_files_it_is_given(documented: Repository) -> None:
    citable = known(documented)
    assert "bin/new.py" in citable.seen.files and "bin/new.py" not in citable.tracked.files
    assert _listed(_PathCitation("bin/new.py"), "docs", citable.seen, citable)
    assert not _listed(_PathCitation("bin/new.py"), "docs", citable.tracked, citable)
    assert _listed(_PathCitation("topic.md"), "docs/plans", _file_set(["docs/plans/topic.md"]), citable)
    assert _file_set(["a/b/c.py"]).with_directories == {"a/b/c.py", "a/b", "a", "."}


def test_a_reference_cites_a_dotted_name_a_path_a_glob_or_nothing(documented: Repository) -> None:
    root = documented.root
    assert _citation("strom._parts.shards.Shards", root) == _DottedName("strom._parts.shards.Shards")
    assert _citation("src/strom/a.py:12", root) == _PathCitation("src/strom/a.py")
    assert _citation("tests/test_a.py::test_one", root) == _PathCitation("tests/test_a.py")
    assert _citation("tests/**", root) == _GlobCitation("tests/**")
    for nothing in ("make check", "tracked_a/b/c", "<topic>.md", "a / b", "Shards.open(cpu_workers=2)"):
        assert _citation(nothing, root) is None, nothing


def test_the_docs_are_the_markdown_files_git_sees(documented: Repository) -> None:
    write(documented, "docs/new.md")
    write(documented, ".checks/generated.md")
    assert docs(documented) == [
        documented.root / name for name in ("ARCHITECTURE.md", "docs/new.md", "docs/plans/topic.md")
    ]


def test_top_level_names_are_definitions_assignments_and_imports() -> None:
    source = (
        "import os.path\nfrom a import b as c\n\nONE = 1\ntwo: int = 2\ntype Three = int\n\n\n"
        "def four() -> None:\n    inner = 1\n\n\nasync def five() -> None: ...\n\n\nclass Six:\n    attribute = 1\n"
    )
    assert _top_level_names(source) == {"os", "c", "ONE", "two", "Three", "four", "five", "Six"}
