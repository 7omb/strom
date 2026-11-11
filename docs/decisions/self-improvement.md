# Self-improvement

From a retrospective of 24 sessions (2026-11-06): one hook dispatcher (`.claude/hooks/dispatch.py`) registered for every
event, so that hooks change without touching `.claude/settings.json` (Claude can't write it); the rules a Bash command
touches are loaded by a hook (half the reads were `cat`/`sed`, which Claude Code doesn't count; the user asked "are the
rules respected?" four times); friction logged per session in `.checks/friction.jsonl`, with the SessionStart hook
suggesting the skill `retro` past thresholds; agreements in `CLAUDE.md` to record gotchas and corrections as they occur;
the recurring requests as skills (`review`, `plan`); `bin/check_docs.py` in `make lint` (stale references were found by
hand in four sessions); the pyright LSP plugin off for this project (163 diagnostics attached, often stale, its
navigation never used). Retrospective of 8 sessions (2026-11-08): the skill `plan` keeps the user's requirements at the
top of a plan, checks runtime claims with a probe and ends writing and revising with a review pass (the user corrected
dropped requirements twice in one session and asked for another pass on the same plan four times); the jail has only
`python3.14t` of the free-threaded build on PATH (it reverses the package order, so `uv -p 3.14` picked 3.14t).
Retrospective of 8 sessions (2026-11-11): the skill `validate-change` ends with a read of the whole diff for structure
and simplicity (the user had to ask for that pass in four sessions); a report ends with what is left, and Claude says
first when the repository is not in the state the user describes (`CLAUDE.md`); findings are implemented a group per
session, and the Stop hook says when a session's context was summarised (one session reached 23 MB with two summaries
and two stops at the usage limit); the Stop hook formats the changed docs with mdformat and runs `bin/check_docs.py`
(`strom_tools.hooks.docs_fixes`; one session ran the formatter by hand twelve times); `bin/ab.py --cpus` pins a
comparison, and each of its runs says how long the rest takes; `bin/rename.py` moves a file with its imports and
citations; tests on 3.14t run through `tox -e 3.14t -- ARGS`; the retrospective reads its data with
`bin/sessions.py friction --since-retro --details` from a friction log whose lines are increments (the script's
docstring). Retrospective of 4 sessions with a review of Claude Code's documentation (2026-11-11): the notes by trigger,
the limits of the hook output and of a note, decisions a file per topic (`agent-docs.md`); gotchas said by the tools
where they happen: `bin/mutant.py` refuses `-x` with `-n`, `bin/ab.py` names a module the baseline lacks and, unpinned
on a hybrid CPU, the fast cores; deny rules for `git stash` push, pop, apply and drop; the retrospective checks each
note against what is enforced by now

**Rejected**

- formatting a doc after each edit (mdformat through pre-commit takes 0.6 s per call, and the file would change under
  the edits that follow in the turn)
- cumulative counts per session in the friction log, with every session's counts recorded at a retrospective as the base
  (2026-11-08: a session that ended again after a retrospective was summed with all it had before; the times in the
  transcript give the increments without a second record)
- an interrupt counted as a rejection per call it cancels (one interrupt of three pending edits made three of the four
  rejections that suggest a retrospective)
- a file per session for the note about a context summary (the transcript records each summary and each Stop)
- `bin/ab.py` pinned to the fast cores by default (the jail has no `/sys`, and `/proc/cpuinfo` tells the cores apart
  only where the fast ones have two threads each)
- moving the test module along with a module in `bin/rename.py` (it would have to know the test layout; a second call
  does it)
- setting `UV_PYTHON` in the jail alone (covers uv's default, not `-p 3.14` or other tools that search PATH)
- reversing `pythonVersions` for the jail (relies on how jail.nix orders PATH)
- only instructions in `CLAUDE.md` (already ignored: rules not loaded, scripts instead of Edit)
- a retrospective after every session (cost without friction)
- a scheduled cloud agent (can't read the local transcripts)
- mutmut-style generated checks for docs (the references are explicit, a plain existence check suffices)
