# Retrospective – strom (2026-11-11)

Scope: the eight sessions with work since the retrospective of 2026-11-08, by `bin/sessions.py` (friction, prompts,
search) and the transcripts: what the user had to correct or ask twice, hand work a script would do, hook blocks and
tool errors with a common cause. Counts are per session id prefix. Delete this file once its findings are done or
rejected (rejections with their reason go to `docs/decisions.md`, Self-improvement). Open: S2, X1.

IDs: W the way of working, S scripts and commands, H hooks and checks, T the retrospective's own tools, X carried over.

## W. The way of working

### W1 to W5: implemented (2026-11-11)

- **W1**: the skill `validate-change` ends with a read of the whole diff for structure and simplicity (its step 7).
- **W2**, **W3**: two lines in `CLAUDE.md` (Process): a report ends with what is left, and a repository that is not in
  the state the user describes is said first.
- **W4**: the skill `review` recommends a session per group of findings (W4a); the Stop hook tells the user once per
  summary of the session's context (W4b: `at_stop` in `strom_tools.hooks.friction_notes`).
- **W5**: `.claude/rules/tooling.md`: nothing waits beside a background command.

## S. Scripts and commands

### S1, S3 and S4: implemented (2026-11-11)

- **S1**: `bin/ab.py --cpus CPUS` pins all runs, and after each run it says how many benchmarks it measured and how long
  the remaining runs take.
- **S3**: `bin/rename.py OLD NEW` with two paths moves a file and rewrites what cites it (its path, its dotted name, the
  imports); after every write ruff sorts the imports of the changed Python files and formats them, and the lines left
  over the limit are listed.
- **S4**: tests on 3.14t run with `tox -e 3.14t -- ARGS` (`CLAUDE.md`, Commands; `.claude/rules/tooling.md`).

### S2. The baseline of an uncommitted tree is made by hand

- **Evidence**: `git commit-tree` by hand four times in b5d6f469 and four times in 0837df3e: the second and later
  changes of a session start from a tree that is not committed. Two notes in `.claude/rules/tooling.md` hold the recipe.
- **Fix**: a script in `bin/` that prints the id of a dangling commit of the working tree (the files git sees, the index
  untouched); `validate-change` names it as REV for such a change, and the two notes go. Its place: a function of
  `strom_tools.change_checks.revisions` with a command of its own.

## H. Hooks and checks

### H1 and H2: implemented (2026-11-11)

- **H1**: at the end of a turn the Stop hook formats the changed Markdown files with mdformat and runs
  `bin/check_docs.py` on every doc (`strom_tools.hooks.docs_fixes`, through `make fix` and `make lint-docs`).
- **H2**: the skill `plan` says how a plan names a file that does not exist yet, and `bin/check_docs.py` prints the same
  hint with a reference it does not find.

## T. The retrospective's own tools

### T1 and T2: implemented (2026-11-11)

- **T1**: `bin/sessions.py friction --details` lists each piece of friction with its call and answer, and
  `--since-retro` takes the sessions and the friction since the last retrospective.
- **T2**: a line of the friction log counts what a session added since the log's last line about it or the last
  retrospective, so the lines add up; the calls an interrupt cancels are part of it (`docs/decisions.md`,
  Self-improvement).

## X. Carried over

### X1. The push gate inherits the heavy tail of the suite

- **Evidence**: since 2026-11-11 the pre-push hook runs `make check`. In the timed runs of that day one of 19 suite runs
  took 39 s and one of 18 took 232 s (generated examples whose fan-out multiplies; `docs/todo.md`, Tests and
  benchmarks).
- **Fix**: do that task next (bound the fan-out of a generated example), before a push waits for it.

## Looked at without a finding

- Five of the fifteen hook blocks were probe scripts in the scratchpad: the edit hook leaves files outside the
  repository alone since 2026-11-11.
- In-place `sed` edits of one or two repository files, against the agreement to use Edit: 6, 4, 1 and 0 in the last four
  sessions that changed code.
- Four Edit calls did not find their text after a formatter had run; one `rm -rf` was denied by the harness.
