"""The import order of the library's packages as `ARCHITECTURE.md` (Packages) and
`docs/decisions/module-structure.md` state it. Imports inside functions count: they are imports all the same."""

import ast
import sys
from pathlib import Path

import package_imports

import strom

PACKAGE = Path(strom.__file__).parent
LAYERS = ["_validation", "_closing", "_metrics", "_stages", "_runtime", "_interpreters", "_runners"]
"""The private packages by role, bottom-up: each imports only from those before it."""
PUBLIC = {"metrics", "testing", "backends"}
"""The public modules beside `strom` itself: on top of the private packages."""
RUNTIME = [
    {"backends", "iterator_registry", "pinning_pool", "worker_handles.handle_table", "worker_handles.process_handles"},
    {"executor_backend", "thread_backend", "process_backend"},
    {"pools"},
    {"worker_handles.worker_handle"},
]
"""The modules of `_runtime` in groups: what the backends share, a slice per backend, the pools on top of them,
and the worker handles users open on the pools. A module imports only from the groups before its own (the
shared ones also from each other)."""


def modules() -> dict[str, ast.Module]:
    return package_imports.modules(PACKAGE)


def own_imports(tree: ast.Module) -> set[tuple[str, ...]]:
    return package_imports.own_imports(tree, "strom")


def test_the_library_imports_only_the_standard_library() -> None:
    """No runtime dependencies."""
    for name, tree in modules().items():
        tops = {imported.split(".")[0] for imported in package_imports.imports(tree)}
        assert tops <= {"strom", *sys.stdlib_module_names}, name


def test_every_part_of_the_library_has_its_place() -> None:
    parts = {name.split(".")[1] for name in modules() if name != "strom"}
    assert parts == {*LAYERS, *PUBLIC}


def test_a_private_package_imports_only_from_those_below_it() -> None:
    position = {part: number for number, part in enumerate(LAYERS)}
    for name, tree in modules().items():
        part = name.split(".")[1] if name != "strom" else ""
        if part not in position:
            continue
        for imported in own_imports(tree):
            assert imported, f"{name} imports the package itself, which is above every private one"
            assert imported[0] in position, f"{name} imports the public module {imported[0]}"
            assert position[imported[0]] <= position[part], f"{name} imports {'.'.join(imported)}"


def test_the_runtime_knows_no_metrics() -> None:
    """Also not those below it: what a run measures of a pool task wraps the function it passes
    (`strom._interpreters.offloaders`)."""
    for name, tree in modules().items():
        if name.startswith("strom._runtime"):
            assert not {imported for imported in own_imports(tree) if imported[0] == "_metrics"}, name


def test_the_reference_semantics_imports_nothing_of_the_runtime() -> None:
    """A leaf's meaning does not depend on its resource."""
    imported = own_imports(modules()["strom._interpreters.reference"])
    assert not {name for name in imported if name[0] == "_runtime"}


def test_a_backend_imports_no_other_backend_and_nothing_built_on_them() -> None:
    names = modules()
    group_of = {module: number for number, group in enumerate(RUNTIME) for module in group}
    in_runtime = {name.removeprefix("strom._runtime.") for name in names if name.startswith("strom._runtime.")}
    # the sub-package itself holds only its docstring, so that its modules can be in different groups
    assert in_runtime - {"worker_handles"} == set(group_of), "every module of the runtime has its place in RUNTIME"
    assert own_imports(names["strom._runtime.worker_handles"]) == set()
    for module in group_of:
        for imported in own_imports(names[f"strom._runtime.{module}"]):
            if imported[0] != "_runtime":
                continue
            target = next(  # the longest module name: `from strom._runtime.pools import Pools` names the module `pools`
                ".".join(imported[1:end])
                for end in range(len(imported), 1, -1)
                if ".".join(imported[1:end]) in group_of
            )
            if target != module:
                shared = group_of[target] == group_of[module] == 0
                assert shared or group_of[target] < group_of[module], f"{module} imports {target}"
