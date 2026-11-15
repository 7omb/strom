# Subagents

strom has two subagents, `reviewer` and `researcher`, because reviews and research read much and answer little: a review
turn in the session's context read 170 to 550 KB for an answer of 3 to 5 KB. A skill or `CLAUDE.md` names the step that
starts one, because Claude Code starts neither by itself here. What each does is in `.claude/agents/`, how many may run
in `CLAUDE.md` (Process).

Decided with it:

- `researcher` has a budget of tool calls, sources and report size, asks WebFetch a question before it downloads a page
  and runs on Sonnet, because a research run weighed up to 1.78M tokens (Measured).
- `reviewer` reads the code and the named files whole and the rest by hunk, once per change.
- What can be enforced of a definition is: `researcher` stops after `maxTurns` requests and starts without `CLAUDE.md`,
  and the Bash guard refuses both subagents what writes the repository (`strom_tools.hooks.command_guards`), because an
  instruction alone had not kept a run from 128 tool calls.
- The Stop hook says when a session's context reaches 250k tokens, because one session had reached 824k without a
  summary, and names a subagent whose run weighed 0.6M or more (`strom_tools.hooks.friction_notes`), because the runs of
  2026-11-14 were found only by a retrospective.
- The session orchestrates research by the skill `research`: it splits the question, briefs each `researcher` and writes
  the note, because the split and the merge are small and an agent between them summarises each finding a second time.
- A plan whose task is marked **API** is read by `reviewer` before it is handed over (skill `plan`), because a critique
  gains from a context that did not write the design.
- A subagent's tool calls run the hooks with the session's id. So the rules hook keeps what it added per context
  (`strom_tools.hooks.rules_loading`), and a session's friction includes that of its subagents. A probe had shown that a
  note the session had did not reach its subagent, and that one added in the subagent counted as loaded in the session.

**Measured** on the transcripts of 49 sessions, before the subagents (2026-11-14)

| What happened | How often |
| -- | -- |
| the author read their own diff | 6 times in 3 sessions; 1 comment fixed |
| the user then reviewed two of those changes | 9 findings |
| a session was opened only to review the one before | 7 sessions |
| research was asked for | about 17 sessions |
| research was answered without a web call | 4 sessions; their notes cite no source |
| one research turn in the session's context | 316 KB read, 7 KB answered |

**Measured**, the tokens of the three sessions that ran subagents (2026-11-15, `bin/sessions.py tokens`, weighted in
units of one input token)

| Run | Runs | Weight |
| -- | -- | -- |
| a review, with 13 to 21 findings | 3 | 0.93M to 1.26M each |
| a research run, with up to 128 tool calls | 9 | 0.34M to 1.78M each |
| five research runs started at once, for one note of 35 KB | 5 | 7.5M together |

The subagents took 28 to 48 % of a session, where web fetches had taken at most 11 % before. The Agent tool reports the
last context of a run as its tokens: 200k for the review that weighed 0.93M.

**Measured**, the first runs with the limits of the definitions (2026-11-15, the same weights)

| Run | Tool calls | Weight |
| -- | -- | -- |
| a research run on one topic, 5 sources, a report of 9 KB | 12 | 65k |
| a review of a change to eight docs, 10 findings | 11 | 78k |

Five quotes of the research report were compared with their page: all five stand there, so `researcher` stays on Sonnet.
A review of a change to `src/` under the limits is not measured yet (B33 in `docs/todo.md`).

**Rejected**

- the diff read by a subagent only when the user agrees (`diff-reviewer`: it never ran in the nine sessions after it was
  added, since nothing asked)
- a subagent that implements a group of findings (a session per group isolates the context as well and keeps the user in
  the loop: a subagent's edits show no diff, and it cannot ask)
- a subagent for the mechanical checks of a change (the scripts already answer in 0.3 to 0.7 KB per call)
- a subagent that reads past sessions (five of the eight sessions that read transcripts were retrospectives, whose task
  that is; what a session decided is in `docs/decisions/`)
- a reviewer per criterion, such as one for naming (the criterion is a line of the prompt of `reviewer`)
- a research agent per question, all in parallel (each repeats the fixed reading and the same searches)
- a smaller model for `reviewer` too (its findings need the judgement; three runs cost a third of the nine research
  runs)
- a subagent that probes a runtime claim (a probe needs the context of the suspicion)
- a subagent that orchestrates the researchers (one more context to pay for, and it cannot ask the user which topics
  matter or whether more than two may run)
- a subagent that designs or writes a plan (a design session is a dialogue, 17 prompts for the setup and teardown design
  of 2026-11-07, and a subagent cannot ask; its edits show no diff)
- the built-in Plan agent for designs (by Claude Code's docs, read 2026-11-15, it starts without `CLAUDE.md`)
- a subagent that checks the citations of a report (a report has at most 6 KB with pinpoints)
