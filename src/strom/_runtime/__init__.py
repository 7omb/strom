"""Where blocking functions run: the backends behind the pools, the worker side of `io_stage` and worker
handles. It knows no runs, steps or metrics: how a run uses the pools is `strom._interpreters.offloaders`.

By feature (`ARCHITECTURE.md`, Packages): a module or sub-package per backend with what only it needs; the
contract, the iterator registry and the handle core, which several features share, in modules of their own."""
