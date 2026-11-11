# Factories

Stages per placement (the user guide's factory table); stages are 1:0..n; no sinks, no `Void`, no source factories: an
effect is a stage returning nothing (or what it did) or the consumer's code; items made by a blocking or async function
come from a stage of it on one input or from async inputs

**Rejected**

- sinks (effects are consumer code or effect stages; their concurrency is consumers in a TaskGroup)
- source factories (a second way into a run)
- separate 1:1 and flat_map factories (a `Map` type and 1:1 special cases in steps, chains, lifting and `product`)
- a streaming `cpu_stage` (iterators can't cross processes)
