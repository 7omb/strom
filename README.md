# strom

Typed, declarative stream processing on asyncio with shared worker pools.

A pipeline is built from stages that are plain, typed values: `Stage[A, B] | Stage[B, C]` is a `Stage[A, C]`, and the
type checker rejects stages that don't fit together. Each stage says where its function runs: on the event loop, in an
async function, in the IO thread pool or in the CPU pool (threads or processes). All steps share the pools, each step
limits its own concurrency, and bounded queues between steps provide backpressure. The backend behind each pool can be
swapped: threads, processes, any `concurrent.futures` executor, or a backend of your own (e.g. remote workers, see
`strom.backends`).

- No runtime dependencies; Python 3.14, also the free-threaded build (3.14t).
- Combinators from arrows: `first`, `second`, `product` (`***`), `route` (`+++`), plus `gather` and `loop`.
- A reference semantics: every stage also has a plain sequential meaning, and the tests check that concurrent runs
  produce the same items.
- Optional metrics (`strom.metrics`: `StatsRecorder`, `diagnose`) that cost nothing when they are off.
- Outputs form a bag: their order is not preserved.

## Installation

```
pip install strom
```

## Example

```python
import asyncio
from collections.abc import AsyncIterator, Iterator

from strom import Pools, Stage, async_stage, cpu_stage, io_stage, stream


async def fetch(n: int) -> AsyncIterator[str]:  # on the event loop
    await asyncio.sleep(0.01)
    yield f"record {n}"


def score(record: str) -> Iterator[int]:  # CPU-bound: in the cpu pool
    yield sum(map(ord, record))


def show(value: int) -> Iterator[int]:  # blocking IO: in the io pool
    print(value)
    yield value


PIPELINE: Stage[int, int] = async_stage(fetch, concurrency=8) | cpu_stage(score, concurrency=2) | io_stage(show)


async def main() -> None:
    async with (
        Pools.open(cpu_workers=2, io_workers=4) as pools,
        stream(PIPELINE, range(20), pools) as outputs,  # a run on the inputs 0..19
    ):
        print("total:", sum([out async for out in outputs]))


if __name__ == "__main__":
    asyncio.run(main())
```

A stage maps each input to zero or more outputs, so a 1:1 function yields its one result. `stream(stage, inputs, pools)`
runs a stage on each item of `inputs`, a sync or an async iterable, and gives its outputs as they come, as an async
iterator; what to do with them (a list, a sum, an effect per item) is the consumer's code. The user guide is the
docstring of the `strom` module (`python -m pydoc strom`); larger examples are in `examples/`, each a uv script
(`uv run --script examples/simple.py`).

## Development

The dev shell (`nix develop`, or direnv with `.envrc`) provides Python 3.14 and 3.14t, uv and the tools (ruff, pyright
and ty come from the dev shell only); `uv sync` installs the dev dependencies.

```
make check                         # lint, type, tests and examples; the other targets: Makefile
uv run tox                         # the same targets, the tests on 3.14 and 3.14t, the benchmarks' results
pre-commit install                 # the git hooks (direnv does it): lint and types at a commit, make check at a push
```

Contributing: start with `ARCHITECTURE.md`.

## License

MIT, see `LICENSE`.
