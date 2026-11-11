---
paths:
  - "src/**/*.py"
  - "tools/**/*.py"
  - "tests/runtime/**"
---

# Typing – the standard library's stubs

- `AsyncGenerator.aclose()` is typed `Coroutine[Any, Any, None]` (fails `--disallow-any-expr`): use
  `aclose_if_closable`.
- `multiprocessing`: `ctx.SimpleQueue()` is `SimpleQueue[Any]` and `SimpleQueue(ctx=...)` takes `ctx: Any`, both failing
  `--disallow-any-expr` (`SimpleQueue[T](ctx=context)` took one `# type: ignore[misc]`). `Connection` is generic
  (`Connection[Any, Any]` unsubscripted, and so `context.Pipe()`): name the ends `Connection[bytes, bytes]` and assign
  the pair to an annotated variable (2026-11-11). Slice assignment into a `RawArray(c_char, n)` is rejected:
  `ctypes.memmove` (2026-11-08).
- `select.select` returns lists of Any: use `select.poll()`.
- `pickle.loads` returns Any: assign it to an annotated variable (mypy exempts that from `--disallow-any-expr`, also for
  a type that only contains Any); a result typed by the caller's type variable needs no cast that way
  (`strom._runtime.process_backend`, 2026-11-11).
- An except clause's name is deleted at its end: reusing it later in the function is an error in mypy ("Assignment to
  variable outside except: block"); name the other value differently (2026-11-11).
