"""Helpers shared by the scripts in `bin/`: the repository, revisions, snapshots, detached subprocesses.

Not a script itself (the `_`): the scripts import it from their own directory."""

import contextlib
import importlib.util
import io
import os
import shutil
import signal
import subprocess
import sys
import tarfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from subprocess import PIPE

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / ".checks"
"""Where `collect_ids.py` and `typing_snapshot.py` keep their snapshots (not versioned)."""
WORKING_TREE = "."
"""The revision name of the working tree (uncommitted changes included)."""
INDEX = ":index"
"""The revision name of the index (the staged changes): a state to compare against without a commit (the jail
has no git identity, so `git commit-tree` fails there)."""


def require_modules(*names: str) -> None:
    """Exits unless this interpreter has the modules: a missing one would look like failing tests (exit code 1)."""
    missing = [name for name in names if importlib.util.find_spec(name) is None]
    if missing:
        sys.exit(f"{', '.join(missing)} not installed for {sys.executable}: run with `uv run --frozen python bin/...`")


def split_passthrough(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """The script's own arguments and those after `--` (passed on to pytest)."""
    if "--" not in argv:
        return list(argv), []
    at = list(argv).index("--")
    return list(argv[:at]), list(argv[at + 1 :])


def export(revision: str, paths: Sequence[str], dest: Path) -> None:
    """Writes the files under `paths` (relative to the repository root) of `revision` into `dest`.

    For the working tree, the files git would see: tracked ones and untracked ones that are not ignored."""
    dest.mkdir(parents=True, exist_ok=True)
    if revision == WORKING_TREE:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *paths],
            cwd=ROOT,
            stdout=PIPE,
            check=True,
        ).stdout
        for name in listed.decode().split("\0"):
            if name and (ROOT / name).exists():  # a deleted tracked file is still listed
                (dest / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, dest / name)
        return
    if revision == INDEX:
        staged = subprocess.run(["git", "ls-files", "-z", "--cached", "--", *paths], cwd=ROOT, stdout=PIPE, check=True)
        subprocess.run(
            ["git", "checkout-index", "-z", "--stdin", f"--prefix={dest}/"], cwd=ROOT, input=staged.stdout, check=True
        )
        return
    archive = subprocess.run(
        ["git", "archive", "--format=tar", revision, "--", *paths], cwd=ROOT, stdout=PIPE, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")


def library_copy(revision: str, dest: Path) -> Path:
    """Exports `src/` of `revision` into `dest`; its path, checked to be what `import strom` finds with it
    first on PYTHONPATH (see `python_path_env`), not the venv's editable install.

    The package is found without importing it: a copy with an injected bug may hang on import."""
    export(revision, ["src"], dest)
    src = dest / "src"
    found = subprocess.run(
        [sys.executable, "-c", "import importlib.util; print(importlib.util.find_spec('strom').origin)"],
        env=python_path_env(src),
        stdout=PIPE,
        text=True,
        check=True,
    ).stdout.strip()
    if not Path(found).is_relative_to(src):
        sys.exit(f"`import strom` finds {found}, not the copy of {revision} in {src}")
    return src


def python_path_env(src: Path) -> dict[str, str]:
    """The environment with `src` first on PYTHONPATH: it precedes the editable install's `.pth` entry."""
    return {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(src), os.environ.get("PYTHONPATH")]))}


def run_detached(
    command: Sequence[str], *, cwd: Path, timeout: float, env: Mapping[str, str] | None = None
) -> tuple[int | None, str, str]:
    """Runs `command` in its own process group; its exit code (None after a timeout), stdout and stderr.

    After a timeout, and when this process is interrupted (the group is in its own session, so Ctrl-C does
    not reach it), the whole group is killed, pool workers included. POSIX only (`start_new_session`, `killpg`)."""
    with subprocess.Popen(
        list(command), cwd=cwd, env=env, stdout=PIPE, stderr=PIPE, text=True, start_new_session=True
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(process.pid)
            stdout, stderr = process.communicate()
            return None, stdout, stderr
        except BaseException:
            _kill_group(process.pid)
            raise
    return process.returncode, stdout, stderr


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):  # every process of the group has ended already
        os.killpg(pid, signal.SIGKILL)


def save_or_diff(
    action: str, snapshot: Path, current: list[str], what: str, compared: Callable[[str], bool] | None = None
) -> int:
    """`save`: writes the lines `current` (`what` they are) into `snapshot`. `diff`: prints the lines removed
    (`-`) and added (`+`) since, compared as multisets, only saved lines that are `compared`; 1 if any differ."""
    name = snapshot.relative_to(ROOT)
    if action == "save":
        snapshot.parent.mkdir(exist_ok=True)
        snapshot.write_text("".join(f"{line}\n" for line in sorted(current)))
        print(f"{len(current)} {what} saved in {name}")
        return 0
    if not snapshot.exists():
        sys.exit(f"no snapshot {name}: run `save` with the same --name first")
    saved = [line for line in snapshot.read_text().splitlines() if compared is None or compared(line)]
    return diff(saved, current, what, "saved")


def diff(before: list[str], current: list[str], what: str, label: str) -> int:
    """Prints the lines removed (`-`) and added (`+`) from `before` (`label`: saved, in REV) to `current`,
    compared as multisets; 1 if any differ."""
    then, now = Counter(before), Counter(current)
    removed, added = sorted((then - now).elements()), sorted((now - then).elements())
    for line in removed:
        print(f"- {line}")
    for line in added:
        print(f"+ {line}")
    print(f"{then.total()} {what} {label}, {now.total()} now: {len(removed)} removed, {len(added)} added")
    return 1 if removed or added else 0


CHECKED = ["src", "tests", "benchmarks", "examples", "bin", "pyproject.toml"]
"""The paths the type checkers and pytest read (`pyproject.toml`)."""


def checkout(revision: str, dest: Path) -> Path:
    """Exports the `CHECKED` paths of `revision` (those it has) into `dest`, with this repository's venv linked as
    `.venv` (where `pyproject.toml` points pyright and ty); `dest`, to run the checkers or pytest in."""
    if revision not in (WORKING_TREE, INDEX) and _git_fails(
        "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"
    ):
        sys.exit(f"no revision {revision}")
    export(revision, [path for path in CHECKED if _has(revision, path)], dest)
    (dest / ".venv").symlink_to(ROOT / ".venv")
    return dest


def _has(revision: str, path: str) -> bool:
    if revision == WORKING_TREE:
        return (ROOT / path).exists()
    if revision == INDEX:
        return bool(subprocess.run(["git", "ls-files", "--cached", "--", path], cwd=ROOT, stdout=PIPE).stdout)
    return not _git_fails("cat-file", "-e", f"{revision}:{path}")


def _git_fails(*args: str) -> bool:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True).returncode != 0
