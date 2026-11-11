"""The structure of `strom_tools` as its guide states it: what it imports, its layers, its entry points."""

import ast
import sys
from pathlib import Path

import package_imports
from package_imports import imports

import strom_tools
from strom_tools.workspace.repository import this_repository

PACKAGE = Path(strom_tools.__file__).parent
ROOT = this_repository().root
LAYERS = [
    {"tool_error", "json_objects"},
    {"workspace"},
    {"change_checks", "example_scripts", "docs_check", "renames", "sessions"},
    {"hooks", "commands"},
]
"""The parts of the package (modules and sub-packages), bottom-up: a part imports only from the layers above its
own (earlier here)."""
ORDER = {
    "workspace": [{"repository", "process_groups"}, {"git_files", "make_targets"}],
    "change_checks": [
        {"revisions", "line_diffs"},
        {"benchmark_comparison", "typing_diagnostics", "collected_ids", "mutants", "make_checks"},
    ],
    "sessions": [{"transcripts"}, {"friction"}],
    "hooks": [{"hook_events"}, {"python_fixes", "docs_fixes", "rules_loading", "friction_notes"}, {"dispatcher"}],
    "commands": [
        {"command_line", "snapshots"},
        {"ab", "check", "check_docs", "collect_ids", "mutant", "rename", "run_examples", "sessions", "typing_snapshot"},
    ],
}
"""The modules of each sub-package in groups: a module imports only from the groups before its own."""
ENTRY_POINTS = ("strom_tools.commands.", "strom_tools.hooks.dispatcher")
SCRIPT = '''"""`strom_tools.commands.{name}` as a script; its usage: `--help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from strom_tools.commands import {imports}  # noqa: E402

if __name__ == "__main__":
    sys.exit(command_line.run({name}.main))
'''
HOOK_COMMAND = '''"""The hook command of `.claude/settings.json`: a wrapper of `strom_tools.hooks.dispatcher`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from strom_tools.hooks import dispatcher  # noqa: E402

if __name__ == "__main__":
    sys.exit(dispatcher.main())
'''


def modules() -> dict[str, ast.Module]:
    return package_imports.modules(PACKAGE)


def own_imports(tree: ast.Module) -> set[tuple[str, ...]]:
    return package_imports.own_imports(tree, "strom_tools")


def test_the_package_imports_only_the_standard_library() -> None:
    """The hooks run on an interpreter without the venv, and a tool has to work while the library is broken."""
    for name, tree in modules().items():
        tops = {imported.split(".")[0] for imported in imports(tree)}
        assert tops <= {"strom_tools", *sys.stdlib_module_names}, name


def test_a_part_imports_only_from_the_layers_above_it() -> None:
    layer_of = {part: number for number, layer in enumerate(LAYERS) for part in layer}
    for name, tree in modules().items():
        if name == "strom_tools":
            continue
        part = name.split(".")[1]
        for imported in own_imports(tree):
            assert imported[0] == part or layer_of[imported[0]] < layer_of[part], f"{name} imports {imported}"


def test_a_module_imports_only_from_the_groups_before_it_in_its_package() -> None:
    names = modules()
    for package, groups in ORDER.items():
        group_of = {module: number for number, group in enumerate(groups) for module in group}
        in_package = {name.split(".")[2] for name in names if name.startswith(f"strom_tools.{package}.")}
        assert in_package == set(group_of), f"every module of {package} has its place in ORDER"
        for module in in_package:
            for imported in own_imports(names[f"strom_tools.{package}.{module}"]):
                if imported[0] == package and len(imported) > 1 and imported[1] in group_of:
                    assert group_of[imported[1]] < group_of[module], f"{package}.{module} imports {imported[1]}"


def test_only_the_entry_points_read_arguments_print_and_exit() -> None:
    for name, tree in modules().items():
        if name.startswith(ENTRY_POINTS):
            continue
        assert not any(imported.split(".")[0] == "argparse" for imported in imports(tree)), name
        for node in ast.walk(tree):
            match node:
                case ast.Call(func=ast.Name(id="print" | "exit")):
                    raise AssertionError(f"{name} prints or exits, line {node.lineno}")
                case ast.Attribute(value=ast.Name(id="sys"), attr="exit" | "argv" | "stdin"):
                    raise AssertionError(f"{name} uses sys.{node.attr}, line {node.lineno}")
                case _:
                    pass


def test_every_script_is_the_wrapper_of_its_command() -> None:
    shared = {"__init__", *ORDER["commands"][0]}
    commands = {path.stem for path in (PACKAGE / "commands").glob("*.py")} - shared
    scripts = {path.stem: path.read_text(encoding="utf-8") for path in (ROOT / "bin").glob("*.py")}
    assert set(scripts) == commands
    for name, text in scripts.items():
        assert text == SCRIPT.format(name=name, imports=", ".join(sorted([name, "command_line"]))), name


def test_the_hook_command_is_the_wrapper_of_the_dispatcher() -> None:
    assert (ROOT / ".claude" / "hooks" / "dispatch.py").read_text(encoding="utf-8") == HOOK_COMMAND
    assert [path.name for path in (ROOT / ".claude" / "hooks").glob("*.py")] == ["dispatch.py"]
