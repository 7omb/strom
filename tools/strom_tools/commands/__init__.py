"""One module per script in `bin/`: its usage as the module docstring, and `main(argv) -> int`, which reads the
arguments, calls the tool, prints and returns the exit code: 0 or 1 for its outcome (`mutant` up to 3), and 4,
`command_line.DID_NOT_RUN`, when it could not run. Import order: `command_line` (what all commands
share) and `snapshots` (what those that compare lines share), then the commands, which import nothing of each
other."""
