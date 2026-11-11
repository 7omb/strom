from pathlib import Path

import strom_tools
from strom_tools.workspace.repository import SOURCE_ROOTS, Repository, shown, state_dir, this_repository


def test_this_repository_holds_the_package_in_its_source_root() -> None:
    root = this_repository().root
    assert Path(strom_tools.__file__) == root / SOURCE_ROOTS["strom_tools"] / "strom_tools" / "__init__.py"
    assert (root / "pyproject.toml").is_file()


def test_the_state_directory_is_in_the_repository(tmp_path: Path) -> None:
    assert state_dir(Repository(tmp_path)) == tmp_path / ".checks"


def test_a_path_is_shown_from_the_root_if_it_is_inside(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "repository")
    assert shown(repository, tmp_path / "repository" / "docs" / "a.md") == "docs/a.md"
    assert shown(repository, tmp_path / "elsewhere.md") == str(tmp_path / "elsewhere.md")
