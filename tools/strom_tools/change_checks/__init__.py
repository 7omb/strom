"""What validates a change (skill `validate-change`). Import order: `revisions`, `line_diffs`; then the checks,
which import nothing of each other: `benchmark_comparison`, `typing_diagnostics`, `collected_ids`, `mutants`,
`make_checks`."""
