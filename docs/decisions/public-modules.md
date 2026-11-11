# Public modules

The top level of `strom` holds what builds and runs pipelines. What only some users need is a public module beside it,
and a name is public in one place only (2026-11-11): `strom.metrics` (the recorder, the events, the statistics), like
`strom.testing` and `strom.backends`. Each has its guide in its own docstring, and the user guide a short section that
points there

**Rejected**

- the metrics names at the top level (until 2026-11-11: 17 of the 55 names of `__all__`, which only users of `recorder`
  need)
- `StatsRecorder` and `diagnose` at the top level as well (two import paths for them, or a metrics module without its
  two entry points)
