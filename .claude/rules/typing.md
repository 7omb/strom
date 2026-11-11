---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "benchmarks/**/*.py"
  - "examples/**/*.py"
  - "tools/**/*.py"
---

# Typing – checker limitations (observed)

## False positives of one checker

The convention (`ARCHITECTURE.md`, Conventions): the code keeps the shape the other two checkers accept, and the one
that is wrong gets its own ignore comment on the line, with a dated entry here. Each checker has a comment of its own
and fails once it no longer needs one, so an ignore expires with its bug:

| Checker | Comment | What reports an unused one |
| -- | -- | -- |
| mypy | `# type: ignore[code]` | strict (`warn_unused_ignores`) |
| pyright | `# pyright: ignore[rule]` | `reportUnnecessaryTypeIgnoreComment` |
| ty | `# ty: ignore[rule]` | `unused-ignore-comment` as an error |

pyright does not read `# type: ignore` (`enableTypeIgnoreComments` is off), and ty only one without a code: a line that
all three reject on purpose carries three comments (`tests/test_init.py`).

Ignored now:

- ty 0.0.91 (2026-11-11): a generic function that may return None (`next_item[O](key) -> NextItem[O] | None`) as the
  argument of a generic `run(fn: Callable[[A], B], arg: A) -> B`: ty solves `B` to None ("Expected `(...) -> None`"), at
  most calls but not at all (five of seven in the probe `.checks/probes/p6_ty_generic_none.py`, whatever the result was
  used for; rerun it with a new ty: `ty check FILE`); mypy and pyright accept them.
  `# ty: ignore[invalid-argument-type]` at the calls it reports: `Offloader.streamed`
  (`strom._interpreters.offloaders`), `check_streaming_backend` (`strom.testing`),
  `tests/runtime/test_iterator_registry.py`, `tests/runtime/test_thread_backend.py`. When ty reports one of them as
  unused, remove it; when it reports another call of `next_item`, add one. The same with `partial(f, ...)` of such a
  function (2026-11-10).

## Limitations

- pyright and ty infer `Unknown` for `flatten()`'s `T`, lambdas in `stage`/`where` and the passed-through type of
  `first`/`second`/`left`/`right` unless annotated (mypy: `Never`); pyright rejects what a lambda does with its
  parameter then (`stage(lambda items: [sorted(items)])` after a typed stage: use a named function, 2026-11-11); pyright
  couldn't match a protocol method with its own type parameter; pyright and ty infer `Unknown` for type variables that
  no argument binds (e.g. `first_focus()`).
- `stream(stage, inputs, pools)`: a generic stage passed directly (`flatten()`, `duplicate()`, `identity()`, `first(f)`,
  `second(f)`, also at the head of a chain such as `duplicate() | product(...)`) gets no type from `inputs` in mypy
  ("Cannot infer value of type parameter", or `Never`; also with `inputs` first in the signature); pyright infers
  `duplicate()` and `first(f)` but not `flatten()`; ty infers all three (checked 2026-11-05). Annotate the stage
  (`pairs: Stage[int, tuple[int, int]] = duplicate()`); after a typed stage `|` gives the context.
- `loop`: all three reject a body whose `Left` can't feed back; ty infers `Unknown` for `B` (no type variable from a
  union argument); pyright `Unknown` for a body that never exits. Other signatures: no gain.
- mypy infers `list[object]` for a list literal of different event classes: annotate `list[Event]`.
- A Protocol (or callable Protocol) with a generic method `run[A, B]` is matched structurally by all three, also through
  wrapper dataclasses and closures returning a nested generic `def`; but ty 0.0.91 accepts a *non-generic*
  implementation (`run(fn: Callable[[int], int], arg: int) -> int`) that mypy and pyright reject (checked 2026-11-08);
  also as an override of an ABC's generic method (`PoolCalls.cpu`, checked 2026-11-10).
- mypy and pyright infer a PEP 695 type parameter that no field uses (a phantom, `IteratorKey[O]`) as invariant, so
  `IteratorKey[O]` is no `IteratorKey[object]`: key a dict by a plain field instead.
- `AsyncGenerator.aclose()` is typed `Coroutine[Any, Any, None]` (fails `--disallow-any-expr`): use
  `aclose_if_closable`.
- `multiprocessing` in typeshed: `ctx.SimpleQueue()` is `SimpleQueue[Any]` and `SimpleQueue(ctx=...)` takes `ctx: Any`,
  both failing `--disallow-any-expr` (`SimpleQueue[T](ctx=context)` took one `# type: ignore[misc]`). `select.select`
  returns lists of Any: use `select.poll()`. Slice assignment into a `RawArray(c_char, n)` is rejected: `ctypes.memmove`
  (2026-11-08). `Connection` is generic there (`Connection[Any, Any]` unsubscripted, and so `context.Pipe()`): name the
  ends `Connection[bytes, bytes]` and assign the pair to an annotated variable (2026-11-11).
- `pickle.loads` returns Any: assign it to an annotated variable (mypy exempts that from `--disallow-any-expr`, also for
  a type that only contains Any); a result typed by the caller's type variable needs no cast that way
  (`reply: tuple[B, BaseException | None, str]` in `strom._runtime.process_backend`, 2026-11-11).
- An except clause's name is deleted at its end: reusing it later in the function is an error in mypy ("Assignment to
  variable outside except: block"); name the other value differently (2026-11-11).
- `--disallow-any-expr` in the tools (`tools/`, 2026-11-11), where the standard library is typed with `Any`:
  - an attribute of `argparse.Namespace`, a group of `re.Match` (`str | Any`), `sys.stdin.read()` (`str | Any`), the
    parts of `re.split`: assign to an annotated variable (`runs: int = args.runs`); `match.expand(r"\g<file>")` gives a
    `str` directly, `re.finditer` with `expand` replaces `re.findall`;
  - `json.loads`: an annotated variable of a `TypedDict` for a format the tool trusts, else `object`, narrowed with
    `strom_tools.json_objects` (`isinstance(value, dict)` narrows `object` to `dict[Any, Any]`); `tomllib.loads` returns
    `dict[str, Any]`, which no `TypedDict` takes: `object` as well;
  - a list or dict literal passed to a parameter typed `Any` (`json.dumps`, `choices=` of argparse) is inferred with
    `Any`: assign it to a variable first; a lambda as `key=` of `sorted` likewise: a named function;
  - `functools.cache` as a decorator is an expression with `Any`; `x ** 0.5` is `Any` (`math.sqrt`).
- A line `# /// script` of its own makes a file a PEP 723 script for ty, also inside a string literal: ty then resolves
  the file's imports against no path of the project (2026-11-11: `tests/tools/test_example_scripts.py` builds the header
  it tests from a list of lines).
- ty has no `__name__` on a value typed `Callable[...]` (mypy and pyright have): `getattr(handler, "__name__", ...)`
  assigned to an annotated variable (`strom_tools.hooks.dispatcher`, 2026-11-11).
