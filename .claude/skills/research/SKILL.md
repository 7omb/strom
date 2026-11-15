---
name: research
description: Research for strom in the literature and in established libraries, written as a note docs/research/<topic>.md - splitting the question into topics, briefing the subagent researcher, checking its report and writing the note from it. Use when asked to research, to compare strom with other libraries, or for best practices and pitfalls of an interface; not for a question the repository answers.
---

# Research

The session splits the question, briefs the readers and writes the note; the subagent `researcher` reads the sources
(`.claude/agents/researcher.md`). Why the session orchestrates and no agent does: `docs/decisions/subagents.md`.

1. **Scope**: word the questions and what strom needs the answers for. Read what strom has today: the code the questions
   concern, the decisions of the topic (`ls docs/decisions/`) and the notes in `docs/research/`. A note is a snapshot of
   its date, so a question that an older note answered gets a new note, which cites the older one.
2. **Split** by the topics, not by the questions:
   - A fact that one source settles is looked up by the session itself and cited where it is used (the plan, the chat);
     it gets no note, and the steps below do not apply.
   - One topic gets one `researcher`, with all its questions in one prompt.
   - Topics that do not need each other's findings get a `researcher` each, started in one message. How many may run is
     in `CLAUDE.md` (Process); when there are more topics, name them to the user and ask which come first.
   - A topic that builds on another one's findings runs after it, with those findings in its prompt.
3. **Brief** each `researcher`. It sees nothing of the conversation, so its prompt holds:
   - the questions, numbered, and what strom needs the answers for;
   - what to read first of the repository, and what to leave unread;
   - the sources to start from, where they are known;
   - the boundaries: what is not asked, and what another `researcher` covers;
   - what the user ruled out or asked for in the conversation;
   - another budget than its default, where the topic needs one. Its definition stops a run at `maxTurns` requests, with
     what it has as a partial report: resume it then (step 4).
4. **Check** the report before writing from it: compare the claims that the answer rests on with the source itself,
   first those with the mark of a lesser read, by asking the page for the passage. A report with a gap goes back to the
   same `researcher`, which keeps what it read (SendMessage, with the gap and a budget for it).
5. **Write** the note alone. It has the parts of the report in their order (`.claude/agents/researcher.md`; why:
   `docs/decisions/research-form.md`), and the session adds:
   - an opening paragraph: the date, the question, what it is for, what was searched and by how many subagents;
   - after the Answer, what strom has today;
   - after the Findings, the options for strom and their fit;
   - where several reports are merged, one numbering of the sources, and for reports that contradict each other both
     claims, each with its source;
   - at a claim the pinpoint and the mark of its report; a claim that step 4 found in the source loses the mark, and the
     entry under Sources says who read what.
6. **Report** in the chat: the answer, the options with a recommendation, and what was not checked. A decision the user
   takes from it goes to `docs/decisions/`, an open step to `docs/todo.md`.
