# Stage repr

The repr of a stage is `<Stage 'name' (step: settings; ...)>`: its name and, for each step occurrence and combinator in
order, the settings that differ from the defaults (placement, `concurrency`, `buffer_size`; `display.settings`).
Hypothesis prints failing stages with it, so a failing generated stage shows its placement and concurrency.

**Rejected**

- the generated dataclass repr (internal kinds, focuses, function addresses: 573 characters for three steps)
- a repr rebuilt from the structure (ignores names users give)
