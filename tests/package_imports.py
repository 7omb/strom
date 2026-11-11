"""What the modules of a package import, read from their source: for the tests of the import order of the library
(`test_packages.py`) and of the tools (`tools/test_structure.py`)."""

import ast
from pathlib import Path


def modules(package: Path) -> dict[str, ast.Module]:
    """The syntax tree of each module of the package in the directory `package`, by its dotted name (a package:
    that of its `__init__`)."""
    found: dict[str, ast.Module] = {}
    for path in sorted(package.rglob("*.py")):
        parts = path.relative_to(package.parent).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        found[name] = ast.parse(path.read_text(encoding="utf-8"))
    return found


def imports(tree: ast.Module) -> set[str]:
    """The modules a module imports, anywhere in it, also inside a function (`from a import b` as `a.b`: `b` may be
    a module or a name of `a`)."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None, "imports are by absolute names"
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def own_imports(tree: ast.Module, package: str) -> set[tuple[str, ...]]:
    """The imports from the package named `package`: the parts of each dotted name after it."""
    return {tuple(name.split(".")[1:]) for name in imports(tree) if name.split(".")[0] == package}
