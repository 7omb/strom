# Stage repr

`<Stage 'name' (step: settings; ...)>`: the name and the settings that differ from the defaults (placement,
`concurrency`, `buffer_size`) of each step occurrence and combinator, in order (`display.settings`); Hypothesis prints
failing stages with it

**Rejected**

- the generated dataclass repr (internal kinds, focuses, function addresses: 573 characters for three steps)
- the name only (a failing generated stage would not show its placement and concurrency)
- a repr rebuilt from the structure (ignores names users give)
