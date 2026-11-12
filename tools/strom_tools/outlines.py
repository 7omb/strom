"""The outline of a Python module: what it defines, where, with its signature and the first line of its docstring,
to find a definition and the range to read without reading the whole file (`bin/outline.py`)."""

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    line: int
    depth: int
    """0 at the top level, 1 in a class, and so on."""
    text: str
    """`def name(params) -> result`, `class Name(bases)`, `type Name = …` or `NAME: annotation = …`."""
    doc: str | None
    """The first line of its docstring, if it has one."""


def outline(source: str) -> list[Entry]:
    """The definitions of a module, at its top level and in its classes, in the order of their lines: functions,
    classes, type aliases and assignments (a class's fields too). Raises `SyntaxError` for a module that does not
    parse."""
    tree = ast.parse(source)
    return [*([Entry(1, 0, "module", first)] if (first := _first_line(tree)) else []), *_entries(tree.body, 0)]


def _entries(body: list[ast.stmt], depth: int) -> list[Entry]:
    entries: list[Entry] = []
    for node in body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                result = f" -> {ast.unparse(node.returns)}" if node.returns else ""
                signature = f"{prefix} {node.name}{_type_params(node)}({ast.unparse(node.args)}){result}"
                entries.append(Entry(node.lineno, depth, _decorated(node, signature), _first_line(node)))
            case ast.ClassDef():
                bases = ", ".join(ast.unparse(base) for base in [*node.bases, *node.keywords])
                text = _decorated(node, f"class {node.name}{_type_params(node)}" + (f"({bases})" if bases else ""))
                entries.append(Entry(node.lineno, depth, text, _first_line(node)))
                entries.extend(_entries(node.body, depth + 1))
            case ast.TypeAlias():
                entries.append(Entry(node.lineno, depth, f"type {ast.unparse(node.name)} = …", None))
            case ast.AnnAssign(target=ast.Name(id=name)):
                value = " = …" if node.value is not None else ""
                entries.append(Entry(node.lineno, depth, f"{name}: {ast.unparse(node.annotation)}{value}", None))
            case ast.Assign(targets=[ast.Name(id=name)]):
                entries.append(Entry(node.lineno, depth, f"{name} = …", None))
            case _:
                pass
    return entries


def _decorated(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, text: str) -> str:
    """`text` after the decorators of `node`, each as `@name` (without its arguments)."""
    names = [
        ast.unparse(decorator.func if isinstance(decorator, ast.Call) else decorator)
        for decorator in node.decorator_list
    ]
    return " ".join([*(f"@{name}" for name in names), text])


def _type_params(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    return f"[{', '.join(ast.unparse(param) for param in node.type_params)}]" if node.type_params else ""


def _first_line(node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str | None:
    doc = ast.get_docstring(node)
    return doc.strip().splitlines()[0] if doc and doc.strip() else None


def rendered(entry: Entry) -> str:
    """An entry as one line: its line number, indented by its depth, the definition and its docstring's first line."""
    doc = f"  # {entry.doc}" if entry.doc else ""
    return f"{entry.line:5}  {'  ' * entry.depth}{entry.text}{doc}"
