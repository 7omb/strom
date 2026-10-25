"""Worker handles: setup and teardown per process for blocking functions (what they mean: `worker_handle`).

The handle core every backend with handles shares (and implementers through `strom.backends`): a backend
whose workers are other processes runs its closes in them (`strom._runtime.process_backend`). Bottom-up:
`handle_table` and `process_handles` below the backends, `worker_handle` above `pools`; this file imports
nothing, so neither group pulls in the other."""
