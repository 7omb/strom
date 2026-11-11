from pathlib import Path

import pytest
from tool_helpers import commit, git, make_calls, with_makefile, write

from strom_tools.renames import (
    FileMove,
    Hit,
    HitKind,
    IdentifierRename,
    Written,
    _apply,
    _citations,
    _endings,
    _files,
    _move,
    _scan,
    _tidy,
    hits,
    line_of,
    rename_of,
)
from strom_tools.renames import kinds as kinds_of_rename
from strom_tools.renames import write as write_rename
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository

SOURCE = '''\
"""Uses fetch and fetch_all."""

from library import fetch


def run(load: int) -> str:
    # fetch it
    value = fetch(load, fetch=1).fetch
    return f"{fetch(value)} by fetch: \\
fetch"
'''


def kinds(hits: list[Hit]) -> list[tuple[int, int, str]]:
    return [(hit.row, hit.start, hit.kind.value) for hit in hits]


def test_scan_tells_code_from_mentions_in_python(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text(SOURCE)
    assert kinds(_scan(path, "fetch", "load")) == [
        (1, 8, "mention"),  # in the docstring, as a whole word: not in `fetch_all`
        (3, 20, "code"),
        (6, 8, "collision"),  # the parameter `load` is there already
        (7, 6, "mention"),  # a comment
        (8, 12, "code"),
        (8, 18, "collision"),
        (8, 24, "code"),  # a keyword argument
        (8, 33, "code"),  # an attribute
        (9, 14, "code"),  # a name inside an f-string
        (9, 31, "mention"),  # the text of the f-string
        (10, 0, "mention"),  # on its second line
    ]


def test_scan_finds_only_mentions_outside_python_and_nothing_without_the_name(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("# fetch\n\nCall `fetch` (not `prefetch`), then fetch.\n")
    assert kinds(_scan(doc, "fetch", "load")) == [(1, 2, "mention"), (3, 6, "mention"), (3, 36, "mention")]
    assert _scan(doc, "absent", "load") == []


def test_apply_renames_there_and_back(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text(SOURCE)
    assert _apply(_scan(path, "fetch", "retrieve")) == [path]
    assert path.read_text() == SOURCE.replace("fetch_all", "\0").replace("fetch", "retrieve").replace("\0", "fetch_all")
    _apply(_scan(path, "retrieve", "fetch"))
    assert path.read_text() == SOURCE


def test_apply_writes_nothing_if_a_hit_is_not_where_it_was(tmp_path: Path) -> None:
    first, second = tmp_path / "a.py", tmp_path / "b.py"
    first.write_text("fetch = 1\n")
    second.write_text("fetch = 2\n")
    hits = _scan(first, "fetch", "load") + _scan(second, "fetch", "load")
    second.write_text("x = fetch\n")
    with pytest.raises(ToolError, match="fetch not at column 0: nothing written"):
        _apply(hits)
    assert first.read_text() == "fetch = 1\n"


def test_endings_of_two_or_more_parts_with_what_replaces_them() -> None:
    old, new = ["src", "strom", "_runtime", "shards.py"], ["src", "strom", "_interpreters", "shards.py"]
    assert _endings(old, new, "/") == {
        "src/strom/_runtime/shards.py": "src/strom/_interpreters/shards.py",
        "strom/_runtime/shards.py": "strom/_interpreters/shards.py",
        "_runtime/shards.py": "_interpreters/shards.py",
    }
    assert _endings(["docs", "a.md"], ["notes", "a.md"], "/") == {"docs/a.md": "notes/a.md"}
    assert _endings(["a.md"], ["b.md"], "/") == {}


@pytest.fixture
def library(repository: Repository) -> Repository:
    write(repository, "src/strom/__init__.py", "from strom._runtime import shards\n")
    write(repository, "src/strom/_runtime/shards.py", "class Shard: ...\n")
    write(
        repository,
        "src/strom/_runtime/routes.py",
        "from strom._runtime.shards import Shard\nfrom strom._runtime import shards, backends\n",
    )
    write(
        repository,
        "docs/notes.md",
        "See `src/strom/_runtime/shards.py` (`_runtime/shards.py`), `strom._runtime.shards.Shard`.\n",
    )
    write(repository, "docs/other_shards.py.md", "Not `other/_runtime/shards.pyc` nor `my_strom._runtime.shards`.\n")
    write(repository, "uv.lock", "src/strom/_runtime/shards.py\n")
    commit(repository)
    return repository


def test_citations_of_a_moving_module_are_its_paths_its_dotted_name_and_its_imports(library: Repository) -> None:
    old, new = library.root / "src/strom/_runtime/shards.py", library.root / "src/strom/_interpreters/shards.py"
    hits = _citations(library, old, new, _files(library, [], everything=True))
    found = sorted((hit.path.name, hit.kind.value, hit.old, hit.new) for hit in hits)
    assert found == [
        ("__init__.py", "module", "strom._runtime", "strom._interpreters"),  # `from PACKAGE import MODULE`
        ("notes.md", "module", "strom._runtime.shards", "strom._interpreters.shards"),
        ("notes.md", "path", "_runtime/shards.py", "_interpreters/shards.py"),
        ("notes.md", "path", "src/strom/_runtime/shards.py", "src/strom/_interpreters/shards.py"),
        ("routes.py", "module", "strom._runtime.shards", "strom._interpreters.shards"),
        ("routes.py", "review", "strom._runtime", "strom._interpreters"),  # it imports a second name
    ]
    assert line_of(hits[0]).startswith("from strom._runtime") or line_of(hits[0]).startswith("See")


def test_citations_of_a_file_outside_the_packages_are_its_paths_only(library: Repository) -> None:
    old, new = library.root / "docs/notes.md", library.root / "docs/plans/notes.md"
    write(library, "README.md", "Read `docs/notes.md`, not `notes.md`.\n")
    hits = _citations(library, old, new, _files(library, [], everything=True))
    assert [(hit.path.name, hit.kind.value, hit.old, hit.new) for hit in hits] == [
        ("README.md", "path", "docs/notes.md", "docs/plans/notes.md")
    ]


def test_the_files_searched_are_the_code_and_the_docs_or_all_but_the_locks(library: Repository) -> None:
    write(library, "bin/tool.py", "")
    write(library, "bin/notes.txt", "")
    names = [path.relative_to(library.root).as_posix() for path in _files(library, [])]
    assert names == [
        "src/strom/__init__.py",
        "src/strom/_runtime/routes.py",
        "src/strom/_runtime/shards.py",
        "bin/tool.py",
        "docs/notes.md",
        "docs/other_shards.py.md",
    ]
    everything = {path.relative_to(library.root).as_posix() for path in _files(library, [], everything=True)}
    assert everything == {*names, "bin/notes.txt"}
    assert _files(library, [library.root / "docs", library.root / "bin/notes.txt", library.root / "nope"]) == [
        library.root / "bin/notes.txt"
    ]


def test_a_rename_is_of_two_identifiers_or_a_move_of_a_file_to_a_free_path(library: Repository, tmp_path: Path) -> None:
    shards = library.root / "src/strom/_runtime/shards.py"
    assert rename_of(library, "fetch", "load") == IdentifierRename("fetch", "load")
    moved = library.root / "src/strom/shards.py"
    assert rename_of(library, str(shards), str(moved)) == FileMove(shards, moved)
    for old, new in [(library.root / "src/nope.py", library.root / "src/new.py"), (shards, tmp_path / "outside.py")]:
        with pytest.raises(ToolError, match="OLD and NEW must be identifiers, or a file"):
            rename_of(library, str(old), str(new))
    with pytest.raises(ToolError, match="NEW is taken"):
        rename_of(library, str(shards), str(library.root / "src/strom/_runtime/routes.py"))
    assert kinds_of_rename(IdentifierRename("a", "b")) == (HitKind.CODE, HitKind.COLLISION, HitKind.MENTION)
    assert kinds_of_rename(FileMove(shards, moved)) == (HitKind.PATH, HitKind.MODULE, HitKind.REVIEW)


def test_a_write_applies_the_written_kinds_and_refuses_collisions_unless_forced(library: Repository) -> None:
    with_makefile(library)
    path = write(library, "src/strom/a.py", "fetch = 1  # fetch it\nload = 2\n")
    rename = IdentifierRename("fetch", "load")
    found = hits(library, rename, [path])
    with pytest.raises(ToolError, match="collisions"):
        write_rename(library, rename, found, mentions=False, force=False)
    assert path.read_text() == "fetch = 1  # fetch it\nload = 2\n", "nothing written"
    assert write_rename(library, rename, found, mentions=False, force=True) == Written([path], "")
    assert path.read_text() == "load = 1  # fetch it\nload = 2\n", "a mention only on request"


def test_a_write_of_a_move_moves_the_file_and_names_it_at_its_new_path(library: Repository) -> None:
    with_makefile(library)
    old, new = library.root / "src/strom/_runtime/shards.py", library.root / "src/strom/_interpreters/shards.py"
    write(library, "src/strom/_runtime/shards.py", '"""`strom._runtime.shards`: shards."""\n')
    rename = FileMove(old, new)
    written = write_rename(library, rename, hits(library, rename, []), mentions=False, force=False)
    assert not old.exists() and new.read_text() == '"""`strom._interpreters.shards`: shards."""\n'
    assert new in written.changed and old not in written.changed, "the file that cites itself, at its new path"


def test_a_file_moves_in_the_working_tree_only(library: Repository) -> None:
    """Tracked or not, the index stays as it is: git finds the move by content once the user stages both paths."""
    write(library, "src/strom/_runtime/shards.py", "class Shard: ...\n\n# edited since the commit\n")
    git(library, "add", "src/strom/_runtime/shards.py")
    index = git(library, "ls-files", "--stage")
    write(library, "notes.txt", "untracked")
    _move(library.root / "src/strom/_runtime/shards.py", library.root / "src/strom/_new/_deeper/shards.py")
    _move(library.root / "notes.txt", library.root / "docs/notes.txt")
    assert not (library.root / "src/strom/_runtime/shards.py").exists()
    assert (library.root / "src/strom/_new/_deeper/shards.py").read_text().endswith("# edited since the commit\n")
    assert (library.root / "docs/notes.txt").read_text() == "untracked"
    assert git(library, "ls-files", "--stage") == index


def test_tidy_sorts_the_imports_of_the_changed_python_files_and_reports_long_lines(repository: Repository) -> None:
    with_makefile(repository)
    changed = [repository.root / "a.py", repository.root / "doc.md", repository.root / "b.py"]
    assert _tidy(repository, changed) == ""
    python = f"{repository.root / 'a.py'} {repository.root / 'b.py'}"
    assert make_calls(repository) == [
        f"fix FILES={python} ARGS=--select I",
        f"lint-python FILES={python} ARGS=--quiet --select E501 --output-format concise",
    ]
    write(repository, "lint-python.fails", "a.py:3:121: E501 Line too long\n")
    assert _tidy(repository, changed) == "a.py:3:121: E501 Line too long\n", "without make's line about the failure"
    assert _tidy(repository, [repository.root / "doc.md"]) == ""
    assert len(make_calls(repository)) == 4, "no Python file: no call"
