# Plan form

A plan opens with its state and outcome and shows the result as its user sees it before the design, because a reviewer
judges the result and a later session needs the state of the work. The parts and their order are in the skill `plan`;
the evidence is in `docs/research/docs-writing.md` (1.1 to 1.9).

Why the parts are as they are:

- The requirements are one list, because a specification kept in one place was measured to be followed more faithfully
  than one spread over a conversation.
- A step names its check, because an agent's own tests did not detect what it had lost of a specification.
- Open questions are a section of the plan, because the chat is not there for a later session.
- A plan without a trade-off has no Design, because one skeleton for every size made small changes large.

**Rejected**

- a progress section beside the steps (the same state in two places)
- a log of decisions, surprises and changes in the plan, as OpenAI's ExecPlans have it (a revision is self-contained;
  decisions go to `docs/decisions/`, gotchas to their note, and git has the history)
- a plan a novice can follow without any other doc (it repeats the repository: a later session gets `CLAUDE.md`,
  `ARCHITECTURE.md` and the notes by path; a plan holds what is nowhere else)
- the open questions first (no template has them there; the opening paragraph says that the plan waits for them)
- the progress as a JSON file (the reviewer reads Markdown)
