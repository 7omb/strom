---
paths:
  - "tools/**"
  - "tests/tools/**"
---

# Typing – the tools

`--disallow-any-expr` holds in the tools too (2026-11-11), where the standard library is typed with `Any`:

- an attribute of `argparse.Namespace`, a group of `re.Match` (`str | Any`), `sys.stdin.read()`, the parts of
  `re.split`: assign to an annotated variable (`runs: int = args.runs`); `match.expand(r"\g<file>")` gives a `str`,
  `re.finditer` with `expand` replaces `re.findall`;
- `json.loads`: an annotated variable of a `TypedDict` for a format the tool trusts, else `object`, narrowed with
  `strom_tools.json_objects` (`isinstance(value, dict)` narrows `object` to `dict[Any, Any]`); `tomllib.loads` returns
  `dict[str, Any]`, which no `TypedDict` takes: `object` as well;
- a list or dict literal passed to a parameter typed `Any` (`json.dumps`, `choices=` of argparse) is inferred with
  `Any`: assign it to a variable first; a lambda as `key=` of `sorted` likewise: a named function;
- `functools.cache` as a decorator is an expression with `Any`; `x ** 0.5` is `Any` (`math.sqrt`).

Besides:

- A line `# /// script` of its own makes a file a PEP 723 script for ty, also inside a string literal: ty then resolves
  the file's imports against no path of the project (`tests/tools/test_example_scripts.py` builds the header from a list
  of lines, 2026-11-11).
- ty has no `__name__` on a value typed `Callable[...]`: `getattr(handler, "__name__", ...)` assigned to an annotated
  variable (`strom_tools.hooks.dispatcher`, 2026-11-11).
