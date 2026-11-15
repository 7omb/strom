# Writing the docs: plans, research notes, explanations, wording – strom

Research of 2026-11-15: which structure, wording and format make strom's docs easier to read, for the maintainer and for
the coding agents that load them. For: a review of the docs of that day, whose findings cite the numbers below.
Searched: templates and style guides of other projects, studies of reading and of learning, vendor documentation and
2025–2026 studies of agents and their context files. Five subagents read the sources, one per question; each entry under
Sources says how it was read, and the marks are theirs, not checked a second time.

## Answer

- **Plans.** The templates agree on one order: the outcome, the problem and goals, the result as its user sees it, the
  mechanism, the alternatives, the open questions, the steps. The skeleton of the skill `plan` has that order and lacks
  four parts: an outcome paragraph, an example of the result, what is not part of the plan, and a check per step. That
  requirements stay in one place and are updated in place is measured to help; no study compares plan formats.
- **Research notes.** A note should open with its answer and how well it is supported, order its findings by claim, mark
  each claim with a pinpoint into its source, and keep what the sources say apart from what is proposed: the design
  belongs in a plan. The evidence is indirect (summaries of health evidence, writing rules of other fields).
- **Explanations.** The best-supported device is a concrete instance beside each abstract statement: an input with the
  outputs it gives. That both stand side by side counts for more than their order. Two instances that differ in one
  respect, compared explicitly, teach more than one. Readers who know the domain learn as well or better from the terse
  form, so the notation stays. An analogy (the Haskell operators) serves only readers who know its other side. Almost
  all experiments are on students; three studies of developers and the docs of comparable libraries carry it over.
- **Sentences.** For expert readers the cost is structure, not length: lists run together with semicolons, numbers to
  compare spread through a sentence, a reason placed in a parenthesis or between subject and verb, a colon that stands
  for an unnamed relation, a reference whose antecedent is far away or elided. Brevity as such, dates and pointers in
  parentheses and pronouns for the current topic cost little. This rests on advice and on experiments with single
  sentences.
- **Docs that agents read.** Measured: an instruction in a context file is followed often, not reliably; what the
  repository does not show helps, overviews and duplicates only cost; adherence falls with the number of rules in force
  at once. File length, position inside a file and format made no detectable difference. So restructuring serves the
  human reader and the partial read, not adherence; nobody measured decision records with agents.

## Findings

### 1. Plans

**1.1 Every template opens with the outcome in one paragraph.** OpenAI's ExecPlans: "Purpose and intent come first",
what someone can do after the change "and how to see it working" [1]; the Rust template has a one-paragraph Summary [2],
a PEP an abstract of about 200 words [3]. For strom: an opening paragraph with the outcome, how it is observed and the
state of the plan; the plans already open with a dated status line.

**1.2 The result as its user sees it comes before the mechanism.** Rust replaced "Detailed design" by a guide-level
explanation, "largely in terms of examples", in front of the reference-level one, so that readers "understand how an RFC
will affect them sooner" [2, PR #2059]. Amazon writes the customer's view first and works back to "the minimum set of
technology requirements" [5]. For strom: the Design of the skill has no such part; for a change to the public API the
review is about the signature, a call and the sentences of the user guide.

**1.3 Requirements in one place, updated in place: measured.** A specification given at once against the same one spread
over about 60 turns: fidelity was higher on 16 of 20 tasks in Claude Code (mean gap 0.116, p = 0.0003); a state that
records "committed project facts rather than every proposal" recovered 90% of the gap; the agent's own tests did not
detect the loss [6]. For strom: supports the Requirements list and revisions that never mention earlier versions; the
last step should compare the result with the requirements. Limits: implementations of ML papers, synthetic dialogues.

**1.4 What is left out and what must not change belong with the requirements.** Non-goals are "things that could
reasonably be goals, but are explicitly chosen not to be" [4]; Claude Code's goal page asks for "anything that must not
change on the way there" [12]. For strom: no place for either today.

**1.5 "Done" is an observable end state with its check, per plan and per step.** Acceptance is "behavior a human can
verify", such as a test that "fails before the change and passes after" [1]; agents declared a project done early and
marked features complete without an end-to-end test [9]; 40 of 85 committed plan files have a testing section [8]. For
strom: "each step leaves `make check` green" is a constraint, not an end state.

**1.6 The state of the work lives in the plan; the executing session changes the state, not the specification.** A
progress checklist is mandatory in ExecPlans [1]; a progress file and the git log let a fresh session "quickly
understand the state of work" [9]. For strom: checkboxes on the steps; today "tick off steps" and "drop what is done"
are two rules for one thing. A separate progress section would hold the state twice.

**1.7 A step names what changes, where and its check, not the code; self-contained does not mean repeating the
repository.** Wrong details in a spec "would cascade into the downstream implementation" [10]; design docs "should
rarely contain code" [4]; agents follow what a file says (a tool was used 1.6 times per task when mentioned, under 0.01
times otherwise), and overviews did not shorten the way to the files to change [7]; spec-kit's files were "repetitive,
both with each other, and with the code that already existed" [11]. For strom: supports "only the details needed to
execute it" and citing code by name. A plan holds what is nowhere else: the user's requests, dated measurements, the
chosen design with what it rejects, the order of the steps.

**1.8 Open questions get a section that is empty before execution.** Rust has "Unresolved questions", a PEP "Open
Issues" [2] [3]; no source puts them first. For strom: the skill sends questions to the chat, which a later session does
not see.

**1.9 One skeleton for every size fails.** A workflow for all sizes turned a small bug into 4 user stories with 16
acceptance criteria [11]; a doc without trade-offs is an "implementation manual" and needs no design part [4]. Committed
plan files have 116 to 5,227 words (mean 876), and 78 of 85 were never revised [8]. For strom: its plans (580 to 1,170
words) are in the usual range; the skeleton should say what a plan without a trade-off omits.

### 2. Research notes

**2.1 Key results at the top are found faster and understood better.** Two small trials of Cochrane reviews with and
without a summary table: 93% against 44% and 87% against 11% correct answers, 90 seconds against 4 minutes to find a key
result [13]. The rule elsewhere: "bottom line up front" [18], "present a clear main analytic message up front" [19]; a
plain language summary opens with key messages, which "might be the only part of the summary that some people read"
[15]. Limit: summaries were easier to understand but made "little to no difference" to the use of the evidence in
decisions [17]. For strom: the answer moves from the end of a note to its top.

**2.2 What the sources say is kept apart from what is recommended.** Separating confidence in the evidence from the
strength of a recommendation "is the defining feature of GRADE" [16]; review authors "should not make recommendations"
[14]; an ADR's context is "value-neutral" [27]; Rust's "Prior art" is a section of its own [2]. For strom: a note holds
findings and options with their fit; signatures and pseudo-code are a plan's (`docs/research/ordering.md` and
`docs/research/grouping.md` hold both).

**2.3 Findings are ordered by claim, not by source; a matrix of short cells gives the view by source.** "A literature
review is concept-centric" [20]; PEP 695 closes its survey with a table of 12 languages by 6 properties in cells of one
or two words [3]. Advice; no study found. For strom: such a matrix fits the line limit, the detail goes into the finding
of its mechanism.

**2.4 How well a claim is supported is said per claim, beside it, with the reason.** GRADE rates per outcome [16];
Cochrane ties the verb to the certainty ("reduces", "probably reduces", "may reduce") and wants the rating "alongside
each result wherever it appears" [14]. For strom: "[unverified]" gives no reason and merges how a claim was read with
what kind of evidence it is; GRADE's four levels do not carry over (they rate a body of studies).

**2.5 A claim is checkable through a pinpoint, a quote where the wording counts, and saying where it was read.**
"Identify which part of a source is being cited", "say where you read it" [21]. 25.4% of the quotations in medical
journals were in error [22]; in answers of generative search engines 51.5% of the sentences were fully supported by
their citations [23]. In strom, four of about 17 research sessions answered without one web call
(`docs/decisions/subagents.md`), and the four notes hold no URL. For strom: a numbered source list with URLs and how
each was read, and the pinpoint at the claim as the mark of having read it.

**2.6 A snapshot says when and what was searched, and what was not found.** A Cochrane summary ends with "How up to date
is this evidence?" [15]; the handbook asks for the limits of the search and warns against taking "no evidence of an
effect" for "evidence of no effect" [14]. For strom: matches the snapshot rule; the notes have no place for what was
looked for and not found.

### 3. Explanations

**3.1 A rule needs an instance beside it.** Novices learn more from worked examples than from solving problems [24];
definitions with concrete examples improved recognising new instances (d = 0.30) [48]; developers "eagerly seek examples
in documentation pages, skipping over explanatory text", and the useful size is one usage pattern, not one call [25].
The itertools table has a column Example (`batched('ABCDEFG', n=3) → ABC DEF G`), Pekko's operator pages an example with
its logged output and a fixed box "emits / backpressures / completes", Trio the code, its printed output and a
walk-through [57]. For strom: in part 2 of the user guide only `loop` has a worked function; `first`, `second`,
`product`, `route` and `gather` show no input with its outputs, and the instance in the docstring of `product` is not in
the guide.

**3.2 Two instances that differ in one respect, with the comparison made explicit.** Transfer improves with at least two
examples per type [24]; of the readers told to compare two cases 42% stated the principle in full, against 13% of those
who read them one after the other [49]. For strom: `product(f, g)` against `first(f) | second(g)`, a branch without
outputs, and `route` against `product` are stated, not shown on one input.

**3.3 Both forms, linked; the terse one stays for readers who know the model.** Concrete first and then idealised gave
better transfer than either alone, evidence its authors call "still tentative" [50]; examples before or after a
definition performed alike [48, of Rawson et al. 2015]; guidance that helps a learner with little knowledge becomes
redundant and can hinder one with much [51]. For strom: instances beside the notation, not in its place.
`(a, c) -> (b, d)` reads as one pair per input; that there are 0..n is only in the words after it.

**3.4 An analogy serves readers who know its base, and needs its limits stated.** An analogy carries relations from a
domain the reader already knows [52]; an expert's intuition does not transfer as an analogy [52, Yorgey]; prior
knowledge of another API sometimes "interfered with my learning" [25]. For strom: the feature list of `README.md` shows
`***` and `+++` to every reader; the guide says a stage "is" conduit's `ConduitT`, although its outputs are unordered
and a stage sees one input at a time; `***` on plain functions gives one pair, `product` the Cartesian product.

**3.5 An explanation built on the known misconceptions shows what goes wrong.** Rust's book characterised the rules
accurately, but learners could not say what would go wrong without them; a chapter built on observed misconceptions,
with concrete counterexamples, raised test scores from 48% to 57% (N = 342) [53]. Trio shows the missing `await` with
its real warning [57]. For strom: its misconceptions are on record (`docs/decisions/product-name.md`: a name that "hid
that the input must be a pair and that outputs multiply"; a generic stage that gets no type from the inputs; a 1:1
function that must yield), and the guide states each as a rule.

**3.6 Diagrams for structure and timing, beside the text they belong to.** Words with graphics against words alone: a
median effect of d = 1.35, strongest for learners with little knowledge; from the author's own lab, on science lessons
[54]. The RxJS guide: "textual descriptions are often not enough", with ASCII marble strings in its tests [57]. For
strom: a plain-text docstring means ASCII; the two streams of `product`, the branches of `route`, the feedback of `loop`
and the shared pools are structure said in words.

**3.7 The split into tutorial, how-to, reference and explanation is argued, not tested.** Diátaxis cites no study [55].
An observation of 11 developers recommends organising by functionality "rather than using categories that signal the
type of information", and to "provide important information redundantly" [56]. Rust puts the guide-level explanation
first, and the reference-level one "should return to the examples given in the previous section" [2]. For strom: the
three parts fit. What `product` does is spread over part 2 and four sections of the reference, which follows aspects,
not combinators; part 1 holds reference detail (the pool tasks of `io_stage`, pickled openers); the laws of the
reference do not return to the instances of part 2.

**3.8 A newcomer needs the terms introduced.** Naming the main concepts first: an effect of 0.78, not for learners with
much knowledge [54]; Pekko's basics page starts with its core concepts and explains backpressure by two cases [57]. For
strom: the guide uses "step", "occurrence", "in flight" and "pool task" without introducing them; the difference between
stage and step is in `GLOSSARY.md` only, which `pydoc` does not show.

**3.9 Theory after the examples, each law with what it lets the reader do.** Pipes.Tutorial gives examples, then laws,
each followed by "This just says that …", and says that "category theory is not a prerequisite" [57]. For strom:
"Composition `|` is associative with identity() as neutral element" names no consequence; the bullet on laws and calls
already does.

**3.10 An example is complete, runs, and shows its output.** Examples must be "complete and ready to be used via copy
and paste" [56]; "They have to work, too!" [25]. For strom: the example of the quick start uses functions it does not
define and shows no output; an output shown must not depend on order.

### 4. Sentences and paragraphs

**4.1 Sentence length is a correlate of difficulty, not its cause.** "Long sentences need not be difficult to read"; a
sentence is too long "when it has more viable candidates for stress positions than there are stress positions available"
[36]. Of 36 rewriting studies 19 were positive, and readers with considerable knowledge "may profit little if any from
an easier style" [37]. The limits (GOV.UK 25 words, Simplified Technical English 20 and 25) are advice [44]. For strom:
no word limit; the long sentences that hurt are run-in lists and series of measurements.

**4.2 A run of independent items belongs in a vertical list; the semicolon itself is fine.** A semicolon makes a second
stress position if what precedes it could stand as a sentence; "a whole list, numbered and indented, can occupy the
stress position" [36]. "Embedded lists are a poor way to present technical information" [43]. Bullets improved the
recall of the items and lowered that of the text around them [47]. For strom: against paragraphs whose segments are
separate decisions; not for bulleting a chain of reasoning.

**4.3 Numbers that are compared go in a table, the conclusion in a sentence.** Figures to compare go close together and
in columns, rounded to two effective digits; an error measure attached to every reading is "visually obnoxious" [38]. A
run-in series against a table: "most readers find the second easier to interpret" [36]. For strom: rows of benchmark,
ratio and p have short cells.

**4.4 Subject, verb and complement stay together; a short clause as subject costs little.** What comes between subject
and verb "is read as an interruption, and therefore as something of lesser importance" [36]. Reading time at the verb
grew with the material between subject and verb, and nesting lowered the accuracy of answers from about 90% to about 76%
[39]. For strom: nothing against "What a tool reads leniently is parsed once"; against four numbers or a 14-word
parenthesis in front of the verb.

**4.5 Parentheses are cheap for asides and the wrong place for what must not be missed.** Lengthening an appositive
lowered naturalness from 6.1 to 5.9 of 7, a restrictive clause from 6.1 to 5.1: parentheticals are "processed
independently of the at-issue material" [40]. "Some readers skip parenthetical text" [43]. For strom: dates and pointers
in parentheses stay; a reason, which is the main content of a decision, does not go there. The evidence is weakest for a
Rejected bullet, whose closing parenthesis is the stress position.

**4.6 Less explicit text suits knowledgeable readers only for what they already know.** Readers with knowledge did
better on inferences after a text of low cohesion, "only if readers have the sufficient amount of background knowledge"
[41]; experts silently supply a missing connection, "other readers are left in the dark" [36]. For strom: terseness
about what the glossary and the code give is supported; leaving out what only the session knew is not. The maintainer
months later and an agent loading a file know the domain, not the case (an inference, not a source's).

**4.7 Causal and contrastive connectives pay; additive ones do not.** They raised comprehension, at every proficiency,
and additive ones lowered it [42]. For strom: a colon stands for "because", "see" and "the cause was" in one file
(`docs/decisions/worker-pool.md`); "also" and "furthermore" can go.

**4.8 A pronoun is right for the current topic and costly at a distance or with ellipsis.** Repeated names are read more
slowly than pronouns "when referring to the most salient referent" [45]; "if more than five words separate your noun
from your pronoun, consider repeating the noun" [43]. For strom: against "Decided with it:" four sentences after its
antecedent, and against elided verbs ("a test fixture the registry of the process").

**4.9 For the size of a paragraph there is only advice; the principle is one point per unit.** At most 150 words in
three to eight sentences [44]; each unit "should serve a single function or make a single point" [36]; the studies of
paragraph length are "inconsistent, inconclusive" [37].

**4.10 Prose linters count tokens, and none comes with evidence that it helps comprehension.** Vale's packages flag
sentences over 30 words, every semicolon and every parenthesis, as suggestions [46]. For strom: checks that count are
prompts for a look; subject and verb, the relation behind a colon and the antecedent of a pronoun need judgement.

### 5. Docs that agents read

**5.1 The structure of a file does not move adherence; the task and the session do.** 1,650 Claude Code sessions with
one rule in the instruction file: no detectable effect of the file's size (25 to 500 lines), of the rule's position, or
of further files; compliance was 45% to 84% by task and fell as the session went on [28]. Claude Code's docs: the file
is "context, not enforced configuration" [12]. For strom: supports enforcing before instructing
(`docs/decisions/agent-docs.md`). Limits: one trivial rule, one harness, a preprint of one author.

**5.2 What the repository does not show helps; overviews and duplicates cost.** Success with no context file, a
generated one and a developer-written one: 59.6%, 57.8% and 62.0% (the mean of four agents), neither significantly
different from none; cost rose by 20% to 23%; overviews did not shorten the way to the files to change [7]. Claude
Code's docs: keep what Claude "couldn't work out from the code" [12]. For strom: supports "delete what code, docstrings
or tests show at a glance"; speaks against the inventory parts of `ARCHITECTURE.md` as required reading. Limit: issue
resolution, not conventions.

**5.3 Adherence falls with the number of rules in force at once.** The share of answers meeting all of 10, 20, 40 and 80
rules: 0.94, 0.75, 0.24 and 0, with the same floor for four formats [29]; with 500 rules the best of 20 models met 68%
[30]. For strom: supports notes by trigger and one topic per note. These rules bound one output; strom's are mostly
conditional, and what it loads together is unmeasured.

**5.4 The top of a file matters through truncation and partial reads, not attention.** No effect of position [28]; the
U-shape of "Lost in the Middle" is a retrieval result on older models [31]. Harness facts: after a summary only the
first 5,000 tokens of a skill are kept, a skill's description is cut at 1,536 characters, Claude may preview a file with
`head -100` [12]. For strom: supports "a file's first sentence is the decision" for files read on demand.

**5.5 In a decision record the title or the first sentence carries the decision; not measured with agents.** Nygard's
title names the choice, and bullets are "not … an excuse for writing sentence fragments" [27]; MADR: "Chosen option: X,
because Y" [26]; a Y-statement is one sentence with context, concern, choice, neglected options, benefit and accepted
cost [32]; a PEP's Rejected Ideas prevent "people from bringing up the same rejected idea again" [3]; the anti-pattern
"Mega-ADR" [32]. For strom: supports decision and reason first and Rejected with a reason per bullet; speaks against
leads that are logs.

**5.6 Living or immutable records: no comparison found.** Agents "fight tooth and nail to apply an accepted decision
even when it is obsolete", so one author keeps "only its current text" [33]. Context files change by addition: a median
of 57 words added and under 15 deleted per commit [34]. For strom: supports files that state the current decision; the
growth by addition is what its largest decision files show.

**5.7 No format is followed or retrieved reliably better; tables cost the most tokens.** Differences between Markdown
lists, tables, plain lines and prose were at most 2.1 points with unstable sign; tokens relative to plain lines:
Markdown 1.26, prose 1.22, a table 1.37 [29]. For strom: nothing supports converting prose to bullets or tables for the
sake of adherence; "tables only for cells of a few words" fits the cost.

**5.8 Skills: compact beats comprehensive, and a skill says when it applies.** Curated skills raised success by 16.6
points; by length of the body: compact +19.0, detailed +14.5, comprehensive +0.7; 13 tasks got worse where a skill
prescribed one heavy procedure "without applicability boundaries" [35]. For strom: supports the short skills and the
"Which steps" table of the skill `validate-change`.

**5.9 On wording there is only advice.** Say what to do and give the reason ("Claude can generalize from the
explanation"), numbered steps where order counts, no capitals: "piling on emphasis mostly makes Claude over-apply the
rule" [12]. Whether an instruction should come before its mechanism in a note is not measured.

## Not found, not checked

- A controlled comparison of plan formats, or of answer-first against answer-last in design or research notes.
- A controlled study of example-first against definition-first in software docs, or of ASCII diagrams in plain-text
  docs; an empirical evaluation of Diátaxis.
- A measurement of how much of a design doc its reviewers read.
- A study of experts, or of agents, reading reference documentation in a compressed style; of chains of colons, elided
  verbs or round brackets; of a prose linter's effect on readers.
- A comparison of a rule with its reason against the bare rule, of instruction-first against explanation-first, or of
  fragments against full sentences in standing instructions; a measurement of capital-letter emphasis.
- A study of decision-record formats read by agents, or of immutable against living records.
- A measured basis for "under 200 lines" (an instruction file) and "under 500 lines" (a skill).
- No full text: McNamara et al. 1996, Kleijn et al. 2019, Jansen 2014, Rosenbaum et al. 2010, Petkovic et al. 2018,
  Jergas and Baethge 2015, Fyfe et al. 2014, Rawson et al. 2015 (publishers answer a fetch with a bot challenge or 403).
  Not read: Williams' "Style" beyond a list of its principles, Pinker's "The Sense of Style", the ASD-STE100
  specification.

## Sources

Read: "full", "sections" (those named), "abstract", "extract" (through the fetch tool's summary and quotes, not checked
against the page), "summary" (a search result or another author's description).

01. OpenAI. Using PLANS.md for multi-hour problem solving. Undated.
    https://cookbook.openai.com/articles/codex_exec_plans — full.
02. rust-lang/rfcs. The RFC template, and PR #2059 (2017). https://github.com/rust-lang/rfcs/pull/2059 — the template
    full; the PR's body, not its discussion.
03. Python. PEP 1, PEP 12, PEP 544, PEP 695. https://peps.python.org/pep-0001/ — sections.
04. Ubl. Design Docs at Google. 2020. https://www.industrialempathy.com/posts/design-docs-at-google/ — full.
05. Vogels. Working Backwards. 2006. https://www.allthingsdistributed.com/2006/11/working_backwards.html — full.
06. Yan, Chen, Zhang. When the Specification Emerges. 2026. https://arxiv.org/abs/2603.17104 — sections 1, 2, 4 to 7.
07. Gloaguen et al. Evaluating AGENTS.md. 2026. https://arxiv.org/abs/2602.11988 — sections 1, 4 to 6, Table 5.
08. Abubakar et al. An Exploratory Study of Agent Plans for Agentic AI Coding Tools. 2026.
    https://arxiv.org/abs/2608.04661 — full.
09. Young (Anthropic). Effective harnesses for long-running agents. 2025.
    https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents — full.
10. Rajasekaran (Anthropic). Harness design for long-running application development. 2026.
    https://www.anthropic.com/engineering/harness-design-long-running-apps — full.
11. Böckeler. Understanding Spec-Driven-Development: Kiro, spec-kit, and Tessl. 2025.
    https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html — full.
12. Anthropic. Claude Code docs: memory, best practices, goal, skills, tools reference; Prompting best practices.
    Fetched 2026-11-15. https://code.claude.com/docs/en/memory — sections; the skills page as extract.
13. Rosenbaum, Glenton, Oxman. Summary-of-findings tables in Cochrane reviews. 2010.
    https://doi.org/10.1016/j.jclinepi.2009.12.014 — abstract.
14. Cochrane Handbook for Systematic Reviews of Interventions, v6.5.
    https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-15 — sections of chapters III, 14,
    15\.
15. Pitcher, Mitchell, Hughes. Guidance for writing a Cochrane Plain language summary. 2022.
    https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/guidance-writing-cochrane-plain-language-summary.pdf
    — sections.
16. Schünemann et al. GRADE Handbook. 2013. https://gdt.gradepro.org/app/handbook/handbook.html — sections 1.2, 5,
    6.4.3.
17. Petkovic et al. Do evidence summaries increase health policy-makers' use of evidence? 2018.
    https://doi.org/10.4073/csr.2018.8 — abstract.
18. US Army. AR 25-50, Preparing and Managing Correspondence. 2020.
    https://www.maine.gov/dvem/policies/documents/AR%2025-50%20(10%20October%202020).pdf — sections.
19. ODNI. Intelligence Community Directive 203, Analytic Standards. 2015.
    https://www.dni.gov/files/documents/ICD/ICD-203.pdf — section D.6.e.
20. Webster, Watson. Analyzing the Past to Prepare for the Future. 2002.
    https://web.njit.edu/~egan/Writing_A_Literature_Review.pdf — one section.
21. Wikipedia. Citing sources. 2026-11-15. https://en.wikipedia.org/wiki/Wikipedia:Citing_sources — sections.
22. Jergas, Baethge. Quotation accuracy in medical journal articles. 2015. https://doi.org/10.7717/peerj.1364 —
    abstract.
23. Liu, Zhang, Liang. Evaluating Verifiability in Generative Search Engines. 2023. https://arxiv.org/abs/2304.09848 —
    abstract.
24. Atkinson, Derry, Renkl, Wortham. Learning from Examples: Instructional Principles from the Worked Examples Research.
    2000\. https://assess.ucr.edu/media/741/download — sections.
25. Robillard, DeLine. A field study of API learning obstacles. 2011.
    https://www.cs.mcgill.ca/~martin/papers/ese2011.pdf — section 5.
26. MADR 4.0.0. 2024. https://adr.github.io/madr/ — the templates full.
27. Nygard. Documenting Architecture Decisions. 2011.
    https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions — full.
28. McMillan. Instruction Adherence in Coding Agent Configuration Files. 2026. https://arxiv.org/abs/2605.10039 —
    sections.
29. Eliav. Prompt Design at Scale. 2026. https://arxiv.org/abs/2607.19257 — sections 4, 8, 9.
30. Jaroslawicz et al. How Many Instructions Can LLMs Follow at Once? 2025. https://arxiv.org/abs/2507.11538 — section
    4\.
31. Liu et al. Lost in the Middle. 2023. https://arxiv.org/abs/2307.03172 — sections 2 to 4.
32. Zimmermann. Architectural Decisions: The Making Of (2020); How to create ADRs, and how not to (2023).
    https://ozimmer.ch/practices/2023/04/03/ADRCreation.html — extract.
33. Davidson. Coding agents love decision records. 2026.
    https://www.oreilly.com/radar/coding-agents-love-decision-records/ — extract.
34. Chatlatanagulchai et al. Agent READMEs. 2026. https://arxiv.org/abs/2511.12884 — sections 4.1, 4.2.
35. Li et al. SkillsBench. 2026. https://arxiv.org/abs/2602.12670 — section 5, appendices D.6, F.
36. Gopen, Swan. The Science of Scientific Writing. 1990. https://cseweb.ucsd.edu/~swanson/papers/science-of-writing.pdf
    — full.
37. DuBay. The Principles of Readability. 2004. https://files.eric.ed.gov/fulltext/ED490073.pdf — sections; the studies
    it reports, summary.
38. Ehrenberg. Rudiments of Numeracy. 1977. https://worrydream.com/refs/Ehrenberg_1977_-_Rudiments_of_Numeracy.pdf —
    sections 1 to 3.
39. Grodner, Gibson. Consequences of the Serial Nature of Linguistic Input. 2005.
    https://www2.bcs.rochester.edu/sites/fjaeger/teaching/LabSyntax2006/readings/Grodner_Gibson_Cog_Sci_2005.pdf —
    abstract, Experiment 2.
40. Dillon, Clifton, Frazier. Pushed aside: parentheticals, memory and processing. 2014.
    https://pmc.ncbi.nlm.nih.gov/articles/PMC4010231 — extract of most of the text.
41. McNamara, Ozuru, Floyd. Comprehension challenges in the fourth grade. 2011.
    https://distantreader.org/stacks/journals/iejee/iejee-222.pdf — sections; McNamara et al. 1996 through it, summary.
42. Kleijn, Pander Maat, Sanders. Comprehension effects of connectives. 2019.
    https://research-portal.uu.nl/en/publications/comprehension-effects-of-connectives-across-texts-readers-and-coh/ —
    abstract.
43. Google. Technical Writing One; developer documentation style guide.
    https://developers.google.com/tech-writing/one/lists-and-tables — extract.
44. Federal Plain Language Guidelines. 2011. https://digital.gov/guides/plain-language/principles/short-simple —
    sections; GOV.UK's and STE's limits, extract.
45. Peters, Boiteau, Almor. 2016. https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2016.00214/full
    — extract of the introduction.
46. Vale, write-good, proselint. https://docs.vale.sh/checks/occurrence — the READMEs and rule files.
47. Jansen. How bulleted lists and enumerations in formatted paragraphs affect recall. 2014.
    https://www.jbe-platform.com/content/journals/10.1075/idj.21.2.06jan — summary.
48. Micallef, Newton. The Use of Concrete Examples Enhances the Learning of Abstract Concepts: A Replication Study.
    2022\. https://cronfa.swan.ac.uk/Record/cronfa59139/Download/59139__22554__6fc4e7a324b1408396691648b6a94d94.pdf —
    abstract, introduction; Rawson et al. 2015, abstract.
49. Gentner, Loewenstein, Thompson. Learning and Transfer: A General Role for Analogical Encoding. 2003.
    https://groups.psych.northwestern.edu/gentner/papers/GentnerLoewensteinThompson03.pdf — sections.
50. Fyfe, Nathan. Making "concreteness fading" more concrete as a theory of instruction. 2019.
    https://scholarworks.iu.edu/dspace/bitstreams/2c814639-f4c7-4091-a6eb-5e6e834bc546/download — sections; Fyfe et al.
    2014, abstract.
51. Kalyuga. Managing Cognitive Load in Adaptive ICT-Based Learning. 2009.
    https://www.iiisci.org/journal/PDV/sci/pdfs/XE225KW.pdf — sections.
52. Gentner. Structure-Mapping: A Theoretical Framework for Analogy. 1983.
    https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf — sections; Yorgey, the "monad tutorial
    fallacy", 2009, extract.
53. Crichton, Gray, Krishnamurthi. A Grounded Conceptual Model for Ownership Types in Rust. 2023.
    https://arxiv.org/abs/2309.04134 — abstract, introduction.
54. Mayer. Research-Based Principles for Designing Multimedia Instruction. 2023.
    https://www.unh.edu/teaching-learning-resource-hub/sites/default/files/media/2023-06/itow-research-based-principles-for-designing-multimedia-instruction-mayer.pdf
    — sections.
55. Procida. Diátaxis. https://diataxis.fr/reference-explanation/ — extract; the quotes of two pages checked in the
    page.
56. Meng, Steinhardt, Schubert. How Developers Use API Documentation: An Observation Study. 2019.
    https://mangold-international.com/resources/meng-et-al-how-developers-use-api-documentation-2019.pdf — one section.
57. Docs of libraries: Python's itertools, Pekko Streams, the Trio tutorial, Pipes.Tutorial, the RxJS guide.
    https://docs.python.org/3/library/itertools.html — extract, the quoted lines checked in the page.
