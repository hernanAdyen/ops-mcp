# CheckoutProposal — Feature Design (discussion draft)

Status: **co-design in progress. No implementation decisions are made in this doc.** Where a section lists options, they are for discussion.
Owner: project owner · Started: 2026-10-22 · Part of the Implementation MCP (see DESIGN.md for the overview)

## 1. Purpose

Help an IM turn what they learned about a merchant (calls, emails, scoping answers) into an **integration solution proposal** that follows the standard template and proposes a technical solution that fits the scope, faster and with fewer gaps, by reusing what the team has already written.

Success looks like (to confirm with you):
- An IM gets a first draft that is mostly right and clearly marks what is missing.
- Every statement in the draft can be traced to a source (a call, an email, a prior proposal, a doc page).
- The more proposals the team writes, the better the next draft gets.

## 2. What we know

- A specific proposal **template** must be used.
- Each solution proposal has an associated **scoping question bank**. Its structure is still to be shared, and we'll use it to decide which questions a proposal must answer.
- Inputs: Gong transcripts and call data (not yet approved, so copy/paste for now), emails, Adyen docs.
- Prior proposals live in a shared Google Drive directory maintained by the implementation team, and new ones keep arriving.
- Reading Drive and pushing documents into our own store will be done by a skill.
- The team wants regular ingestion of the newest proposals so the tool improves organically.
- A knowledge graph is wanted as a **better search** feature.

## 3. What we don't know yet (blocking real design)

1. **Proposal structure**: sections, what is free text vs structured, how long, how they differ by merchant type.
2. **Scoping question bank**: format, how questions map to proposal sections, whether answers are recorded per proposal.
3. **How references work today**: how does an IM currently find and reuse a past proposal? What do they copy: sections, diagrams, risk wording, effort estimates?
4. **What "technical solution" means in practice**: architecture description, API flow, product list, effort, open risks?
5. **Drive layout**: one folder or many, naming, versions/drafts, mix of finished and in-progress proposals.
6. **Who reviews and approves** a proposal, and what do they check for?

### 3.1 What the template, question bank and two example proposals tell us (2026-10-22)

**One proposal = one Google Doc with tabs.** Instructions → Workshop Notes (Discovery, Deep Dive & Solutioning, Validation) → Integration Proposal Generator → Template (the merchant-facing output). The question bank is a separate Sheet copied into the merchant's folder under "Global Merchant Projects".

**Output structure (template):** 1 Introduction (overview, approach, background, stakeholders, goals) · 2 Scope (Project: Discovery + Features & Functionality; optional Tracks) · 3 Solution (Project and per-track: Technical Considerations, Integration Design, Flow Diagrams, Documentation) · 4 Timeframe · 5 Conclusion & Next Steps. Variants exist: EN, CN, JP (draft), and a "Drop-in Blueprint" with no pre-delivery.

**Tracks vary by deal.** In the two examples the tracks are journeys such as Onboarding, Account Holder Management, Fee & Commission Structure, Online Ordering/Reservations, In-Person Payments, Payouts, Sub-merchant reporting, Financial reporting. So the track list is something the IM decides, not fixed.

**Question bank (Project Scope tab, ~180 rows):** columns `Question, Answer, priority (1–3), subsection (Introduction / Discovery / Features & Functionality), channels (ECOM, IPP, MOTO), pillars (DIGITAL, PFS, UC), category (PAYIN, PAYOUT, KYC, PAYFAC, CAPITAL, CASHOUT, REPORTING_RECONCILIATION…), platform (PSP, BALANCE)`. A separate Project Solution tab has three rows (Technical Considerations, Integration Design, Documentation). Feature questions are TRUE/FALSE toggles; discovery questions are free text. The template says to fill Scope sections by filtering the bank by `subsection`. The metadata also suggests we can pre-select relevant questions by pillar/channel/category for a given deal.

**Workshop notes are where the real source material lives.** Free-hand notes per session, with patterns like "LOOK INTO:", "Questions: … Answer: …", attendee tables, high-level details (date, pillar focus, current PSP, estimated live date, decision date). Many questions and answers appear here that are **not** in the bank.

**Data-quality notes for ingestion:** some bank rows contain several questions in one cell, answer guidance embedded in the question text (e.g. network-specific warnings), a few duplicates (e.g. the LEM-version and KYC>25k questions each appear twice), and typos. Mapping answers back to questions will need care.

**A feedback form already exists** in the template ("provide your feedback here" links to a Google Form), so the feedback loop in 4.8 can build on it instead of starting from scratch.

**Answered question banks and proposals are the richest structured data:** each merchant folder holds an answered bank (question → answer, tagged by pillar/channel/category) next to the proposal text. That pairing is what makes "how did we answer X for similar merchants" possible.

## 4. Feature breakdown for discussion

### 4.1 Inputs
| Input | Interim way in | Later | Notes to discuss |
|---|---|---|---|
| Call transcripts | Paste into the conversation | Gong API when approved | Multiple calls per merchant; speaker labels; what metadata we keep |
| Emails | Gmail search by merchant/thread | — | Which threads count as requirements vs noise |
| Scoping question bank answers | ? | ? | Could be the backbone of requirements capture |
| Adyen docs | Live lookup with links | — | Which docs are authoritative for which products |

### 4.2 Requirements capture
Turn raw inputs into a structured set of answers to the scoping questions, each with its source and a status (answered / partially / unknown / contradicted). The gaps list becomes the IM's follow-up questions for the merchant. *Discuss: is the question bank the right backbone? Who owns it when it changes?*

### 4.3 Proposal drafting
Fill the template section by section from the captured requirements, drafting the technical solution from docs and prior proposals. Mark anything unsupported as *Needs confirmation* rather than guessing. *Discuss: one pass or section by section with IM review in between? Where should the IM stay in the driver's seat?*

### 4.4 References and citations
Each section should show where its content came from (call, email, prior proposal, doc). *Discuss: how detailed (per paragraph? per claim?), and how a reader checks a reference quickly.*

### 4.5 Search over past proposals
What the IM wants to ask the corpus decides what kind of search we need. Candidate questions, to be corrected by you:
- "Find proposals similar to this merchant" (vertical, region, model, volume).
- "Which proposals used marketplace + a given payment method in a given region?"
- "How did we answer scoping question X before, and what happened?"
- "Show me how we described the architecture for this integration type."
- "What risks did we flag in similar scopes?"

Search approaches are options to discuss, not decisions:
- Plain text and semantic search over documents and sections.
- A **knowledge graph** over entities and relationships extracted from proposals, which could improve questions that combine several facts and connect proposals to merchants, products, regions and questions. The schema depends on the questions above and the proposal structure.
- A mix of both.

*Discuss: which of the questions above matter most, and what you'd want the graph to make possible that plain search can't.*

### 4.6 Ingestion and the organic improvement loop
A skill reads the Drive folder and pushes documents to our store, regularly. *Discuss: how do we tell finished proposals from drafts, handle edits to already-ingested proposals, and handle merchant-confidential content (names, volumes, pricing)? Who can see what once it's ingested?*

### 4.7 Quality and evaluation
Idea: take past proposals, feed in only the inputs that existed before they were written, and compare our draft to the real one. *Discuss: do we have a few past proposals with their call notes/emails to test with?*

### 4.8 Feedback loop (new)
Goal: at the end of every proposal generation, capture how good the result was, collate it in a Google Sheet, and use it later to improve the tool.

Options to discuss:
| Option | Pros | Cons |
|---|---|---|
| A. Google Form link sent at the end | Richer answers; form responses land in a linked Sheet automatically, so IMs need no write access to the Sheet | More friction; lower response rate; the form can't know which sources or prior proposals drove the draft unless we pre-fill fields |
| B. In-conversation 1–10 rating by a skill step | One question, near-100% capture; the skill can attach what it knows (proposal id, sources used, prior proposals referenced, tool version, sections the IM changed); appended to the Sheet via the Sheets connector | Needs write access to the shared Sheet (or a service account); less detail |
| C. Both: quick 1–10 plus an optional "tell us more" form link | Best coverage | Two paths to maintain |

Notes:
- A skill step is more portable than a hook, since hooks depend on the client and on tool-call events; we can revisit if a hook proves useful.
- The most useful feedback is tied to *what produced the draft*. A 6/10 with the list of prior proposals and sources used is actionable; a bare 6 is not.
- Implicit signal: the final proposal lands in the shared Drive folder, so we could compare the generated draft with the final version to see what the IM changed. Worth discussing alongside ingestion (4.6).
- Keep merchant-confidential content out of the feedback Sheet: store a proposal id, not names or figures.

Questions: which fields do you want on the survey (score, what was missing, time saved, which sections needed rework)? Who owns the Sheet and reviews it? Should the rating be optional or always asked?

### 4.9 Questions asked that are not in the bank (new)
IMs will ask questions the bank doesn't have, and the examples show answers to such questions living in workshop notes. Options for how we use them, for discussion:

1. **Capture as candidates, never auto-edit the bank.** Pull Q&A pairs out of notes/transcripts, tag each with provenance (merchant, session, date, IM) and the same metadata as bank questions (pillar, channel, category, subsection) where we can infer it.
2. **Match before treating as new.** Compare against the bank to decide: same question reworded, a more specific version of an existing one, or genuinely new. Only the last two become candidates.
3. **Use them immediately in retrieval.** When scoping a similar merchant, surface "questions other IMs asked in similar deals" next to the bank questions, with the answers that were given. This works even before anything is promoted.
4. **Promote through a human.** Count how often a candidate recurs across proposals; show the frequent ones to whoever owns the bank, who accepts, edits or rejects. Accepted ones are added to the bank (and the proposal-facing question wording stays controlled).
5. **Feed the proposal draft.** An off-bank question that was answered in the notes can still support a section of the proposal, with the reference.

Open questions: who owns the question bank and its changes? Is there already a process for adding questions? Should candidate questions stay private to an IM until they've been seen more than once? Should their answers be reusable across merchants, given confidentiality?

### 4.10 Intake and scope reconciliation (new)
How IMs actually work: each IM copies the proposal doc and the question bank. The intended flow is bank first, then populate the proposal from it. In practice answers end up in the bank, in personal notes, directly in the proposal, in call transcripts and in emails, so **the bank cannot be assumed to be the source of truth**.

Implications to discuss:
- **Intake first.** The IM knows channel, pillar, category and platform when they start. Capture those (plus merchant name and any tracks already identified) up front. They drive which bank questions are relevant and in what priority.
- **Reconcile, don't just fill.** Gather answers from every place the IM points us at (their bank copy, notes, the proposal copy, pasted transcripts, emails), map each to a bank question or to a candidate question (4.9), and show a single view: question, answer, where it came from, conflicts between sources, and what is still unanswered.
- **IM confirms.** The IM accepts, edits or rejects each mapped answer before it flows into the proposal.
- **Tracks.** IMs discover and decide the tracks. The tool can suggest tracks from the scope (e.g. "this looks like Onboarding + Payouts + Reporting") but the IM decides.
- **Answers go into new AI-assisted tabs, not into the IM's existing tabs (decided).** The IM provides links to their own question bank and proposal; we add AI-assisted tabs (see 4.12) and leave everything else untouched. The assisted tabs are also the structured record that ingestion and feedback can use later, since they hold confirmed answers with sources.
- **Priority: pull scope from transcripts.** The IMs' biggest pain is that the scoping document is cumbersome and filled in by hand. So the highest-value capability is extracting answers to bank questions from call transcripts (pasted for now) into the assisted Sheet, with the transcript location as the source, for the IM to confirm.

### 4.11 The Solution component (new)
Scope is gathered from the merchant. The **solution is designed by the IM, and the template gives little guidance**, so it needs its own sources and its own workflow, separate from scope capture.

What the solution sections need and where it could come from (to discuss):
| Solution piece | Possible sources | Notes |
|---|---|---|
| Technical considerations | Current Adyen docs; version requirements; prior proposals for the same category/track | Version numbers go stale, so they should come from current docs, not copied from old proposals |
| Integration design | Prior proposals' solution sections for similar scope; docs; IM's own design | The recommendation tool would live here |
| Flow diagrams | A library extracted from prior proposals; diagrams the IM adds | Open: can we generate/adapt diagrams, and in what format? |
| Documentation links | Adyen docs mapped to each in-scope feature | Likely the most mechanical piece: scope feature → docs link |

Ideas:
- **Scope-to-solution traceability.** Each solution item points back to the scope items it satisfies, so gaps (scope with no solution) and orphans (solution with no scope) are visible.
- **Recommend a solution.** Given the confirmed scope, propose a solution based on similar past proposals (same pillar/channel/category and overlapping features), with references and the differences from those cases called out. The IM edits; this is a starting point, not an answer.
- **Different standard of evidence.** Scope answers come from the merchant; solution content is judgement, so it should always show what it was based on (prior proposal X, doc page Y) and be easy to override.

What we learned (2026-10-22):
- Many deals are fairly standard Adyen integrations (e.g. an e-commerce pay-in flow with cards and PayPal using Adyen Web). For these the solution is mostly "solve the scope with the right Adyen technical solution", so **current Adyen docs plus prior proposals are the main sources**. No other solution-design repositories were named.
- **Reference quality today = the two example proposals.** More will be collected and quality will be measured (see 4.13).
- **The biggest IM struggle is the scoping document, not the solution.** Solution generation matters, but transcript-to-scope extraction comes first.

Still open: are there Confluence playbooks or architecture pages worth including later? (Not now, per the above.)

### 4.12 AI-assisted tabs in the IM's own files (**superseded in part by 4.15**: the proposal is now a new copy of the master doc, not a tab in the IM's doc; AI-assisted answers still go into a new sheet in the question bank file)
The IM gives us the links to **their own copy of the question bank (Sheet) and the solution proposal (Google Doc)**. The tool adds **new AI-assisted tabs** to those same files. Existing tabs are never modified. The files stay where the IM keeps them (the merchant folder, per the team convention), and the final deliverable is that same Google Doc with the new tab. Providing the links is the permission, and we only add and fill our own tabs.

Feasibility check (connector tool definitions, 2026-10-22):
- **Sheets: looks fine.** The Sheets connector supports adding a sheet (tab), copying a sheet between spreadsheets, and writing values and formatting.
- **Docs: partly confirmed.** The Docs connector exposes the Docs batch-update API, and its text operations accept a tab ID, so reading and writing into a specific tab is supported. **Not yet confirmed: creating a new tab and copying the template's formatting into it.** The tool description I could see was truncated before listing every operation. Needs a test on a scratch doc before we rely on it. Fallback if tab creation isn't possible: the IM adds an empty tab (or duplicates the template tab) and we fill it.
- The Docs connector has a **suggest mode** (changes arrive as suggestions rather than direct edits). Could be a useful safety option for anything we write into an IM's doc.

Open: what happens if the IM doesn't have edit access, or the file is owned by someone else? How do we mark tabs as AI-assisted (name, colour, banner) so readers can tell? What if the IM later edits our tab: do we re-run over it or leave it alone?

### 4.14 Two commands: scope-creator and solution-generator (**superseded by the four-command spec in 4.15**; kept for history)
**`scope-creator`**
- Input: links to the IM's question bank and proposal doc; channel, pillar, category, platform; sources (pasted transcripts now, notes, emails, existing answers in the IM's own bank/proposal).
- Does: selects relevant bank questions from the tags and priority, extracts and reconciles answers from the sources (4.10), identifies candidate off-bank questions (4.9), and writes an AI-assisted **scope tab in the Sheet** (question, answer, source, status, confidence) and the scope sections in the proposal Doc's AI-assisted tab.
- Output state per question: answered / partial / unknown / conflicting / not applicable, with the IM confirming.
- Exit: a confirmed scope, plus a list of follow-up questions for the merchant.

**`solution-generator`**
- Precondition: a **fulfilled scope**. Proposed definition to discuss: every priority-1 question is answered or explicitly marked not applicable, and the IM has confirmed the scope. If not met, the command says exactly what is missing instead of generating; the IM may override with a visible warning in the output.
- Does: maps confirmed scope items to the Adyen technical solution (docs, prior proposals), drafts Technical Considerations, Integration Design, Flow Diagrams and Documentation per track, with traceability back to scope items and references to what each part was based on.
- Ends with the feedback step (1–10 rating plus form link, 4.8).

Why two commands: scoping and solutioning are different jobs with different data sources and different review points, and the scope is the input contract that makes the solution traceable.

Open: should `solution-generator` re-validate scope if the IM edited the confirmed scope after the first run? Do we want a single combined "run everything" convenience later? What are the right command names and invocation style for the team (slash commands, skills, or both)?

### 4.13 Measuring proposal quality (new, to design)
Today only two proposals are reference quality. As more proposals are collected we want to measure quality, so retrieval and recommendations can favour the good ones. Signals we could combine (for discussion):
| Signal | How we get it | Caveat |
|---|---|---|
| IM rating of the AI draft (1–10) and form feedback | Feedback loop (4.8) | Rates the tool's draft, not the final proposal's quality |
| Edit distance between AI draft and final proposal | Compare the assisted Doc with the final in Drive | Large edits can mean "bad draft" or "unusual deal" |
| Reviewer/peer rating of the final proposal | A short rubric (completeness, clarity, accuracy of solution, template adherence) | Needs a reviewer and agreed rubric |
| Outcome | Did the merchant sign / go live on the proposed timeline? | Slow, confounded by non-proposal factors |
| Curated "reference" flag | Maintainers mark proposals as reference quality | Starts with the two examples |

Questions: who decides what is reference quality? Should retrieval weight reference proposals above others, and how do we treat proposals with no quality signal yet (use with a label, but don't recommend from them)? Where is quality data stored (a column in the feedback Sheet, a registry Sheet keyed by proposal id, or in the store)? How do we handle quality changing over time?

### 4.15 Command specification v1 (decided 2026-10-22)

The MCP type is **IM MCP**. Commands below are the decided v1 behaviour; points marked **[to confirm]** are my questions or gaps, not decisions.

#### `/create-scope` — generate a prefiltered scoping bank
1. **Prompt the IM for:** merchant name; pillar (DIGITAL, PFS, UC; some or all); category (some or all); platform (PSP, BALANCE; all that apply); any other questions they want covered.
   - "Other questions" are found three ways: (a) deterministic search from the answers above, (b) semantic search across all bank questions, (c) assisted findings (e.g. a link to an Adyen public docs page to get up to speed on a topic).
2. **Fetch the latest question bank** with the Sheets connector. The master template is a hard-coded environment variable (it will not change).
3. **Build a local table** of the bank (rows with their tags).
4. **Filter:** deterministic query on the tags, then semantic search over questions using the extra information the IM gave.
5. **Create a new question bank Google Sheet** in the IM's Drive root under `SolutionProposals`, named `[merchant-name][timestamp]`, and **share the link in the chat**.

Notes / to confirm:
- The real category values in the bank include more than the four listed (PAYIN, PAYOUT, REPORTING_RECONCILIATION, KYC, PAYFAC, CAPITAL, CASHOUT, plus blanks), and the prompt lists PAYOUT twice. **[to confirm]** Derive the category list from the bank each time instead of hard-coding it.
- **Channel (ECOM, IPP, MOTO)** is also a bank tag and earlier you said IMs know it up front. **[to confirm]** Ask for it too?
- Tag cells are multi-valued ("DIGITAL, PFS, UC") and some are blank (e.g. Introduction rows, "What are the project focus areas?"). **[to confirm]** Match rule: a row is included if it overlaps any selected value; blank tag = applies to everyone. Introduction rows always included.
- The bank is only ~180 rows, so semantic search can be done by having the model rank the questions against the IM's request. No embedding model or vector store is needed for this command, which also avoids the embedding-approval question for now.
- ~~"Assisted findings" needs Confluence~~ **Decided: no Confluence.** Assisted findings come only from public Adyen docs, the previous-proposal knowledge graph and the IM's input.
- The `SolutionProposals` folder is created if it doesn't exist. **[to confirm]** The earlier idea was the merchant folder under Global Merchant Projects; this replaces it. Files are private to the IM until they share them.

#### `/source-scope-answers` — fill the bank from the sources
1. **Input:** link to the question bank (normally the one `/create-scope` made).
2. **Sources:**
   - *Manually entered answers* in the bank: read via the Sheets connector.
   - *Gong briefs:* the IM pastes them if no Gong MCP is present. Extract the question/answer and cross-reference with answers already in the sheet.
   - *Gong transcripts:* same input rule. Extract (a) questions that were asked but are not in the bank (e.g. token imports), and (b) answers to bank questions not yet captured, using the bank link as the list of questions to answer.
3. **Normalize and write** the result into a **new sheet (tab) in the provided question bank file** with AI-assisted answers. Existing tabs are untouched.
   - We **do not store the full transcript or brief**, only the extracted question answers.
   - **Feature flag: sanitization.** Optionally obfuscate PII and intellectual property in what is written.
   - **Feature flag: the command itself,** so it can be switched off (manual answering only, nothing from Gong) or marked experimental until the privacy team clears it.

Notes / to confirm:
- **Sanitization applies to what we write, not to what the model reads.** Pasted transcripts go into the conversation, so the privacy review should look at that path too, not only at the sheet. **[to confirm]**
- Each AI-assisted answer should carry its source (brief / transcript, and a pointer such as the call date), a status and a confidence, so the IM can confirm. **[to confirm]** columns.
- Candidate off-bank questions (4.9) land in the same AI-assisted sheet, marked as not from the bank.

#### `/propose-solution` — generate the proposal
1. **Input (required):** the question bank link. It should be as complete as possible, but this is not a hard gate: the output says the solution reflects the scope collected and the IM's inputs (co-creation). Optional extra context from the IM.
2. **Sources:** the bank, using the manually entered Project Scope tab and/or the AI-assisted tab (the IM may not have run `/source-scope-answers`), plus the IM's additional context. **[to confirm]** If a question has both a manual and an AI-assisted answer, which wins? Suggest: manual wins, AI-assisted shown as a note.
3. **Generate 2.0 Scope** from the bank.
4. **Generate the Solution:**
   - *Technical considerations:* from points called out in the scoping answers.
   - *Integration design:* Adyen technical docs; previous proposals as guidance; find an Adyen technical solution that solves the scope.
   - *Flow diagrams:* keep a labelled library of diagrams. Possibly link the right diagrams through the solution proposal knowledge graph, or use the diagram from the docs where one exists.
   - *Documentation:* find the matching doc links.
5. **Create a new solution proposal:** copy the hard-coded master solution proposal (Google Doc), prefill it, and reuse that same proposal for the rest of the chat unless the IM says otherwise.

Notes / to confirm:
- This **supersedes the earlier "new tab in the IM's own doc"** idea: the proposal is a new copy of the master. The copy keeps the master's tabs and formatting, and filling is done with Docs batch updates.
- "Previous proposals as guidance" needs those proposals to be readable somewhere. For the MVP that can be the two reference proposals read from Drive; ingesting more is later work.
- The knowledge graph's first concrete job could be linking diagrams to integration patterns and features. **[to confirm]** Keep it as a later feature?
- "Same proposal for the chat" implies session state (the created doc's ID). We'd keep it in the conversation and, if needed, a small local state file.
- The feedback step (1–10 rating plus form link, 4.8) was not listed here. **[to confirm]** Keep it at the end of `/propose-solution`?

#### `/create-adyen-diagrams` (nice to have)
Use the Figma MCP to locate a template flow diagram, copy it, and edit the copy. Not part of the Monday MVP unless time allows.

#### Dependencies
| Dependency | Used by | Status |
|---|---|---|
| Google Sheets connector | create-scope, source-scope-answers, propose-solution | Available |
| Google Drive connector (create folder/file, copy, share) | all | Available; folder creation and sharing to verify |
| Google Docs connector | propose-solution | Available; filling a copy of the master to verify (tables, formatting) |
| ~~Confluence connector~~ | — | Removed by decision; only public docs, the knowledge graph and IM input are used |
| Gong | source-scope-answers | Not available; manual paste for now; flagged experimental |
| Adyen docs (public web) | propose-solution | Available |
| Figma MCP | create-adyen-diagrams | Present in this workspace; not verified for copying templates |
| Config / feature flags (environment variables) | all | To design: template IDs, sanitization flag, command flag |
| A place for state (local table of the bank, session proposal ID) | create-scope, propose-solution | To decide |

### 4.16 Decisions on the open points, and the knowledge graph (2026-10-22, second round)

**Tags and the question table**
- `/create-scope` asks for **all** tag types, not only the three in the first draft: priority, subsection, channels, pillars, category, platform.
- **Match rule (decided):** a row is included if it overlaps any selected value; a blank tag means it applies to everyone.
- The bank is **normalized into a queryable table with a generated schema.** Multi-valued tag cells are split into one value per row/link. The allowed value sets are taken from the master bank and are fixed (they won't change).
- **Invalid values:** someone may enter a value that doesn't fit the schema. The master bank is locked down as much as possible, and the loader validates every row against the schema; rows with invalid values are reported in the summary (not silently dropped) and excluded from tag filtering until fixed.
- **Bank cleanup is a separate piece of work,** including an agent to find inconsistencies (duplicates, multi-question cells, typos, embedded guidance).
- One cleanup item to note now: toggle rows ship with `FALSE` pre-filled in the Answer column, so an unanswered toggle looks like a "no". Extraction must treat that default as *unanswered*, not as an answer.

**Semantic matching without an embedding model**
- **Both run, and their results are combined (decided).**
  1. **Tag query on the local question table:** deterministic, using the tags the IM selected (priority, subsection, channels, pillars, category, platform) and the match rule above. This gives the base set.
  2. **Model matching, no embeddings:** the full bank is given to the model as context. From the IM's free-text request it extracts a **structured query** (topics plus any tags it can infer), shows it back to the IM, and selects matching questions. This can add relevant questions the tag query missed (e.g. a topic like token migration that sits under a different tag) and can rank the combined list.
  3. **Combine:** the final list is the tag-query set plus the model-matched additions, with each question labelled by how it was found (tag match, topic match, or both) so the IM can see why it is there and remove it.
- No vector store or embedding model is used.

**Privacy:** agreed that sanitization covers what is written, and that the privacy review also covers pasted transcripts going into the conversation.

**Conflicts between manual and AI-assisted answers**
- Manual answers win; the AI-assisted answer is kept as a note.
- Beyond that, the IM gets a **link and a summary calling out inconsistencies.** When the tool finds an inconsistency, it **asks the IM what to do before generating**, then generates with their answer.

**Feedback:** a feedback step (1–10 rating plus form link, 4.8) goes at the end of **every** command, so we can curate feedback and improve the tool.

**Knowledge sources:** Confluence is out. The tool uses **public Adyen docs, the previous-proposal knowledge graph, and the IM's input**.

**Knowledge graph: in scope for v1** because it is key to generating solutions reliably. Beyond linking diagrams, it should link **questions, answers, integration design and documentation**.

Draft ontology, for discussion (not decided):
| Node | Examples |
|---|---|
| Question | A canonical bank question; candidate off-bank questions |
| Answer | An answer given in a specific proposal (with source and who confirmed it) |
| Scope item / feature | e.g. tokenization, 3DS, split payments, payout schedule |
| Integration design | e.g. Adyen Web integration with the Sessions flow; Terminal API with Adyen terminals; platform onboarding (matches the proposal's "Integration Design" wording) |
| Technical consideration | A point to call out in a proposal |
| Documentation link | A public Adyen docs page |
| Flow diagram | A labelled diagram in the library |
| Proposal / track | A prior proposal and its tracks, with a quality signal (4.13) |
| Tag values | Pillar, channel, category, platform, priority |

| Edge | Meaning |
|---|---|
| Proposal → Question (with Answer) | How this question was answered in that proposal |
| Answer → Scope item | What the answer means for scope |
| Scope item → Integration design | Which integration design solves it |
| Integration design → Documentation link / Flow diagram | Where to read about it / how it looks |
| Question or Answer → Technical consideration | When to call something out |
| Question ↔ Question | Related or dependent questions |
| Proposal → Integration design | What the proposal used, and how well it went |

Every edge records where it came from (curated by a person, or extracted from a proposal) and a confidence, so the generator can say what a recommendation is based on.

Questions the graph must answer for `/propose-solution`: given the confirmed scope, which integration patterns apply, which technical considerations to call out, which diagrams and docs to include, and which prior proposals are most similar.

Honest constraint: with two reference proposals, **learning relations from proposals alone gives a very thin graph.** The first version is mostly curated seed knowledge (pattern ↔ docs ↔ diagrams ↔ considerations for the common integrations), with proposal-derived edges added as more proposals are ingested.

Open questions: who curates the seed? Where is the graph stored (decide after the ontology is agreed)? How do edges get reviewed and retired when docs change? Which integration patterns and diagrams exist today, and in what form?

### 4.17 Knowledge graph: lifecycle, seeding and an honest assessment (2026-10-22, third round)

**Decided**
- Terminology: we say **integration design** (the proposal's own wording), not "integration pattern".
- **Links and IDs are environment variables** (master question bank, master proposal, feedback form, seed data, diagram library, etc.), since they may change.
- The graph is **stored locally**. It supports search; it does not depend on the question bank of the current deal (the IM's scope is the *query*, not graph content).
- Seed for now: the existing proposals plus the owner's knowledge. Integration design seed data may be generated from the limited proposals, edited by the owner, and the preferred ones stored, so the data set is built partly synthetically.

**A scope-to-design idea to build on.** Filled-in tags drive which integration designs to look at, and each tag can have *one, many or none* values. For example, channels ECOM + IPP + MOTO means the e-commerce, in-person and mail/telephone order integration designs are all candidates; a deal with no channel (e.g. a Capital deal) has no channel-specific design. Answers refine this: "credit card payments in scope = TRUE" with channel ECOM suggests the Adyen Web integration with the Sessions flow; channel IPP suggests a Terminal API integration with Adyen terminals. So the first-pass mapping is a deterministic rule from tags and answers to candidate integration designs, and the model then writes and adapts it.

**Lifecycle options (proposal, to discuss)**
Two layers with different costs:
| Layer | Contents | When built | Cost |
|---|---|---|---|
| Curated seed | Integration designs, their conditions, considerations, docs, diagrams, hand-written relations | Loaded at start from the seed (env-var-linked Sheet or file) | Trivial; milliseconds; deterministic |
| Derived layer | Relations extracted from ingested proposals and answered banks | Built by an ingest job, persisted locally, refreshed when stale | Heavy: model extraction per proposal, tokens, minutes, non-deterministic |

Recommendation: **don't rebuild the derived layer on every run.** Load the seed every time, keep the derived layer as a local file with a "last updated" stamp, and on start compare with the Drive folder's last-modified; refresh incrementally (only new or changed proposals) on demand or when stale. Rebuilding from scratch only when the schema changes.

Trade-offs of storing locally per IM:
- ✔ Simple, fast, works offline from the graph's perspective, no hosting or access approvals.
- ✘ Each IM's graph can differ depending on when they refreshed and what Drive access they have.
- ✘ Curation is duplicated or lost, since edits made on one laptop aren't shared.
- Middle path to consider: **a maintainer builds a versioned graph snapshot centrally (every so often); each IM's MCP downloads it and reads it locally.** Local reads, one source of truth.
- Confidentiality: a deal's in-progress answers should not enter the shared graph until the proposal is final and approved for reuse.

**Seed structure — "integration design card"** (one per integration design). Proposed home: a Google Sheet (tabs below) linked by an environment variable, so the owner can edit without touching code.
1. *Integration designs tab:* id; name; one-line summary; short description (3–6 sentences); status (draft / approved); owner; last reviewed.
2. *Applies-when rules tab:* integration design id; conditions on tags (channel, pillar, category, platform) and on specific questions/answers (e.g. question X = TRUE); rule type (required / suggested / modifier); notes. Example rows: channel includes ECOM and payment methods include cards → Adyen Web with Sessions flow; channel includes IPP → Terminal API with Adyen terminals.
3. *Considerations tab:* integration design id; consideration text; when it applies (condition); source link; "version-sensitive?" flag (so we check current docs instead of copying numbers).
4. *Documentation tab:* integration design id; public docs URL; what it is for (e.g. "implementation guide", "testing", "go-live").
5. *Diagrams tab:* integration design id; diagram id; location (file or Figma link); caption; which step of the flow it shows.
6. *Relations tab:* integration design A → relation (extends / requires / alternative to / often combined with) → B.
7. *References tab:* integration design id; proposal; section anchor where it was described; quality signal.

How the work could split: I draft the cards from the two reference proposals and the current public docs, marked **draft/unreviewed**; the owner edits and approves; only approved cards are used as authoritative. This avoids treating my own drafts as ground truth.

**What I'd need from the owner to start seeding**
- The list of integration designs the team most commonly proposes, even just names (aim for the 5–10 that cover most deals).
- The mapping from tag values (channel / pillar / category / platform) to those designs, in whatever form is quickest (a short list is fine).
- Your preferred flow diagrams (files or Figma links) and which design each belongs to.
- A review pass on the drafts I generate.

**Honest assessment**
- **Where a graph earns its keep:** the part of the problem that is structured and relational (scope answers → integration design → considerations → docs → diagrams) benefits from explicit, curated, traceable links. It makes recommendations consistent, explainable ("this design was suggested because channel = ECOM and cards are in scope") and reduces the risk of the model inventing doc links or diagrams.
- **Where it won't help much:** prose quality, and "find proposals with similar wording", which are better served by the model reading the proposals directly.
- **Key point:** the value is in the **ontology and the curated data, not in graph database technology.** For this size (tens of integration designs, a handful of proposals), a graph database isn't needed. Graph-shaped data in a small local store (or the seed Sheet loaded at start) gives the same benefits with far less to build and run. A graph database can come later if multi-hop queries become hard.
- **Will it pay off long term?** Likely yes, *if* three things hold: someone owns curation, every edge carries provenance and a review date so it can be retired when docs change, and feedback (4.8) and quality signals (4.13) feed back into which designs and relations get recommended. If those don't hold, it becomes stale and untrusted. It won't by itself make proposals sophisticated; accuracy comes from good scope capture, current docs, curated mappings and IM review, with the graph holding the mappings together.
- **Risk to the Monday MVP:** building automatic extraction from proposals now would yield a thin graph from two examples. A curated seed (the scope-to-design rules, docs, diagrams and considerations for the common designs) is the part that makes `/propose-solution` better on Monday.

### 4.18 Shared data service, curated + graph, and the seed sheet (2026-10-22, fourth round)

**Decided (supersedes the "stored locally" decision in 4.17)**
- **A shared service holds the data, so there is no drift between IMs.** It stores the **graph** and the **normalized question bank tables** (from the master bank that `/create-scope` normalizes). The MCP exposes **tools that query those tables and the graph**. For this project we **run the service in Docker locally to test**, and **host it ourselves later**.
- `/create-scope` seeds the question tables **periodically** from the master bank (it changes rarely); check last-updated and refresh when the master changes.
- **Curated mappings and the graph are both used,** because some integration designs are more complicated than others. They sit behind **one recommendation interface** with a **feature flag** to switch between *curated only*, *graph only*, and *both*, so we can test results side by side.
- **Curation:** The owner curates for now. Seeding starts from the existing proposals plus the owner's knowledge.
- **Seed sheet:** "IM MCP - Integration Design Seed" (Google Sheet) holds the curated mappings. Its link is an environment variable.

**Retiring links.** Recency naturally helps (newer relations and newer doc links outrank older ones), but it doesn't remove a link that has gone wrong. Cheap safeguards to add: a periodic check that doc URLs still resolve and when they last changed; prefer the latest `last_reviewed` / `last_checked`; and use feedback (4.8) to demote recommendations that IMs rate poorly. Manual retirement is then the exception.

**One store, two kinds of edges.** Curated rows from the seed sheet are loaded into the graph as *curated* edges (with who approved them and when). Relations extracted from proposals are added as *derived* edges. The feature flag decides whether derived edges are used. This keeps one store and one query interface.

**Scale.** Tens of proposals is small for any graph store (thousands of nodes and edges), so size isn't the constraint. The constraints are extraction cost and quality per proposal, and keeping edges trustworthy. Cross-proposal relationships (question ↔ answer ↔ integration design across many proposals) are a good reason to use a shared graph store rather than only a Sheet loaded at start.

**Open: choice of database and hosting.** Candidates: a graph database (e.g. Neo4j) or Postgres with relational/edge tables. Neo4j is more natural for cross-proposal traversals; Postgres is likely easier to host and approve internally. Keep all access behind the MCP's query tools so the database can be swapped. **Need to know Adyen's internal hosting and database standards.**

**Open: security of the shared service.** It will hold merchant-related content derived from proposals and banks. Needs access control, an agreed retention rule, and a rule that in-progress deal answers don't enter it until the proposal is final and approved for reuse.

**Monday MVP note.** With only two reference proposals the derived layer will be thin, so *curated* edges carry most of the value at first. Building both behind the flag is feasible; the comparison becomes meaningful as more proposals are ingested.

### 4.19 Graph in `/create-scope`, extraction quality, feedback propagation, database (2026-10-22, fifth round)

**Updated question bank received.** The prefilled `FALSE` answers are gone. Profile of the updated bank: **141 questions** (my earlier "~180" counted file lines, not questions), priorities 75 / 40 / 26 for 1 / 2 / 3, subsections Discovery 96, Features & Functionality 43, Introduction 2. Blank tags remain: channels blank on 67 rows, pillars on 1, category on 7+, platform on most rows (only 31 rows carry a platform). 15 questions still span multiple lines/questions in one cell. **There is no stable question ID column.** The graph, the Questions tab of the seed sheet and feedback all need stable IDs, so **cleanup should add a `question_id` column to the master bank** (never reused, never renumbered).

**Graph in `/create-scope` (decided in principle).** The IM's free-text context is also used to search the graph for questions that were asked before. Three channels now feed the question list, each labelled in the output:
1. Tag query on the question table (deterministic).
2. Model matching over the full bank (topics and inferred tags).
3. **Graph search:** (a) from the IM's context, likely integration designs → the questions linked to those designs (seed sheet tab "8 Questions"); (b) questions asked and answered in similar *completed* proposals (derived edges); (c) candidate off-bank questions seen before (4.9). Each result shows why it was suggested (e.g. "asked in 3 similar proposals").
Only completed proposals shared with merchants (by the naming convention) feed (b) and (c). With two reference proposals, (b) and (c) will be thin; (a) comes from the seed.

**Extraction cost and quality (how).** At this scale cost is small (tens of proposals, a few tens of thousands of tokens each). **Quality** is the problem. Proposed pipeline, run as a batch job, not at query time:
- **Only completed, shared proposals** are ingested (naming-convention gate).
- **Deterministic first.** The template is fixed, so split by section headings without a model; take answered question→answer pairs straight from the answered bank Sheet; take doc URLs with a pattern match; take tags from the bank.
- **Model only for what remains,** with a constrained output: a fixed schema, controlled vocabularies (question IDs, design IDs, doc URLs) and **evidence required** (every proposed edge must cite the section and text span it came from; edges with no evidence are rejected).
- **Resolve to existing nodes.** Mentions are matched to canonical nodes; anything that doesn't match goes to a **review queue** instead of creating new nodes automatically. This prevents near-duplicate nodes polluting the graph.
- **Provenance on every edge:** proposal, section, span, extractor version, run ID, confidence, status (auto / approved / rejected).
- **Incremental and cached:** content hash per proposal and section; re-extract only what changed. Runs are versioned so a bad run can be rolled back.
- **Evaluate the extractor:** hand-label the two reference proposals as a gold set; measure precision and recall; re-run on every extractor change.

**Scoring proposals at ingestion (agreed idea, to design).** Score each ingested proposal against a standard and store it on the Proposal node. Layers: *deterministic checks* (all template sections present, scope coverage, solution items traceable to scope, doc links resolve, a diagram present), a *model-graded rubric* (is the solution consistent with the scope), and a *human reference flag* (the two references today). Use model grading to prioritize review, not as ground truth; calibrate it against the two references.

**Feedback propagation (design).** The hard part is *credit assignment*: one overall rating mixes scope capture, solution quality, formatting and how unusual the deal was. Blindly demoting everything used in a poorly rated proposal would punish good designs for unrelated reasons. Proposed approach:
1. **Record a recommendation trace** for every generated proposal: which designs, rules, considerations, docs, diagrams and reference proposals were used, and for which scope items. (IDs only, no merchant content.) Without it, feedback can't be attributed.
2. **Two data flows, kept separate.** *Content flow:* final shared proposals → graph via ingestion. *Feedback flow:* ratings and edits on generated proposals → weights on the recommendations that were used. A generated proposal never enters the graph on its own.
3. **Ask what was weak when the rating is low.** If the overall score is below a threshold, one follow-up: which part was weakest (scope capture / integration design / considerations / diagrams / docs / other). That localizes blame to the right component.
4. **Item-level signal beats the 1–10.** When the final shared proposal is ingested, compare it with the generated draft: items kept = positive, items edited = neutral/weak negative, items removed or replaced = negative. This is the main learning signal; the rating mostly decides what to review first.
5. **Weights live on edges, not only on nodes.** Most failures are specific ("right design, wrong diagram for this variant" or "rule fired when it shouldn't"). Each edge keeps evidence counts (accepted / rejected, recency-decayed) on top of a prior (curated edges start high, derived lower), so one bad rating cannot flip a well-supported edge, and low evidence shows as low confidence.
6. **Condition on context.** Penalize the *rule* that fired in that context (tags + answers → design), not the design globally. A design rated poorly for an unusual merchant stays good elsewhere.
7. **Keep different quantities separate:** *confidence* (is this relation correct, from curation or extraction) versus *usefulness* (how recommendations built on it are rated). The recommendation score combines them with curation status and recency.
8. **A low rating with no component information changes no weights;** it puts the proposal and its trace in a review queue. Demotion needs repeated or item-level evidence.
9. **Automation can demote and flag; only humans retire.** Edges have a status (active / under review / retired) with a reason, who and when. Retired edges are never recommended but kept for audit. Curated edges can be **pinned** so automation can only flag them for review, never silently demote them. Doc-link health checks can set "under review".
10. **Versioned weights.** Snapshots allow rollback, and evals check that feedback updates don't degrade recommendation quality.

**Database.** Postgres can host the graph: nodes and edges as tables, recursive queries (`WITH RECURSIVE`) for traversals, JSONB for provenance, and extensions (e.g. Apache AGE adds openCypher; availability depends on the managed Postgres provider, so check Adyen's offering). At our size (thousands of nodes and edges) plain SQL is fine. Benefits: one database for the normalized question tables, the graph, recommendation traces, feedback and weights, with transactions. Cost: graph queries are more verbose than in a graph database. **Leaning Postgres** unless Adyen's platform standards say otherwise; access stays behind the MCP query tools so it can be swapped.

### 4.20 Decisions: Monday scope, filling the master proposal, answers sheet, ingestion (2026-10-22, sixth round)

- **Monday scope:** CheckoutLab and IM Researcher are dropped from the Monday MVP (design docs come later). CheckoutInvestigate and Local Main stay placeholders. CheckoutPost: to confirm.
- **Database:** Postgres in local Docker. Authentication deferred to v2.
- **Filling the master proposal copy (`/propose-solution`).** The template is in a tab of the doc and shows where to insert responses. *2.1.1 Discovery:* every bank question with subsection = Discovery goes in the template's format ("question" then "Insert response" with the answer). *2.1.2 Features & Functionality:* every question with subsection = Features & Functionality goes in the template table, scope = the question and finding = the answer. Same pattern for track sections. Open: which questions go to project vs track sections; unanswered questions shown or omitted; ordering.
- **AI-assisted answers sheet:** same columns as the question bank, same order, so it reads the same to the IM. Proposed: provenance columns appended on the right (question_id, source, status, confidence, note). To confirm.
- **Seeding the graph from proposals is v1.** It is important to show the tool improving as people add proposals. Two sources, loaded into the same graph: (1) *curated edges* from the seed sheet (mappings, docs, diagrams, considerations that can't be inferred from two proposals), (2) *derived edges* from ingested completed proposals. Demo: ingest one reference proposal, generate for the other's inputs and compare; ingest both and regenerate; later add a third. Ingestion follows the pipeline in 4.19 (deterministic parsing first, model extraction with evidence, resolution to existing nodes, review queue, provenance). Open: the answered question banks for the two references (do they exist?); with only two proposals, both mostly platform-style, derived edges help platform deals far more than e-commerce or in-person.
- **Feedback survey (open):** (a) what we ask the IM in the 1–10 step and the optional form, and (b) what we record automatically with each response (command, proposal ID, tool version, flags, recommendation trace ID). Suggested starting set to react to: overall 1–10; if low, which part was weakest; time saved; free text; whether it will be sent to the merchant.
- **Evals (open):** golden cases and scoring.

### 4.21 Feedback design (proposal for review, 2026-10-22)

**Two IDs, two different things.**
- **`generation_id`:** one run of a command (e.g. one `/propose-solution` output). Lives in the feedback and trace tables. **Not a graph node.** It records the Google Doc/Sheet we generated, the tool version, flags, and the recommendation trace.
- **Proposal node:** a *completed* proposal that was shared with a merchant and ingested into the graph. When the final proposal is ingested, link it to the generation(s) it came from (`derived_from`), using the doc ID, the naming convention, or the final link the IM gives us. That link enables the "what did the IM keep, edit or remove" learning signal.

**Recorded automatically with every feedback event:** generation_id, command, link to the generated proposal/sheet, tool version, feature flags on (curated / graph / both, sanitization), seed snapshot version and bank version, trace ID, timestamp, user (identifier to decide; may be hashed).

**At the end of each command (in chat):**
1. "How would you rate this 1–10?"
2. *Rating 8 or higher:* "Anything to add?" (optional free text), plus the form link.
3. *Rating below 8:* show a short numbered list of the key things we surfaced (up to about 8: the integration designs, considerations, diagrams, docs, and for scope commands the questions or answers) and ask "which of these were wrong, missing or not useful, and why?" The IM answers in plain language.
4. **Confirm the interpretation** before saving: "I understood: the diagram for X was wrong because Y. Is that right?" The model maps the text onto trace items; the IM confirms.
5. Each point is stored as: trace item (node or edge), polarity, **reason category** (`wrong`, `not applicable here`, `outdated or broken`, `missing`, `unclear`), free text. A `missing` point becomes a **candidate** new edge for curator review (nothing is added automatically).

**Optional form** (Google Form, link generated per run with fields pre-filled): generation_id, link to the generated proposal, command; overall 1–10 (if not already given); what worked well; what didn't; which sections needed rework; hours saved; will you send it to the merchant (yes / after edits / no); optional contact consent. Responses land in a linked Sheet and are imported into the feedback tables by a job.

**What happens to a score and the notes:** feedback events are stored in Postgres. A batch job ("apply feedback", run on demand or on a schedule) updates edge evidence per the rules in 4.19: a low rating with no item detail changes no weights and goes to a review queue; item-level negatives increment the rejected count on the *edge or rule that fired*; "outdated or broken" flags the doc node for a link check; "missing" creates a candidate. Weight changes are versioned so they can be rolled back, and the curator reviews the queue. The knowledge graph primer explains where weights live.

**Service.** For v1 (local Docker, no authentication) this is just tables in the same Postgres plus MCP tools (`feedback_submit`, `feedback_list`) and the apply job; no separate web service is needed yet. When the shared service is hosted, the same operations get an HTTP API (and the Form import job).

Open: user identity and whether feedback is anonymous; where the pre-filled Form link is built (needs the Form's field IDs); who reviews the queue and how often.

### 4.22 Evals (thoughts for discussion, 2026-10-22)

**Your idea** (a scoring function, decide the expected scores for specific proposals, check the code returns the same) is right for *part* of it. Three kinds of checks:
1. **Deterministic checks (exact):** the tag filter returns exactly the expected rows; the template has all sections; every solution item cites scope items; doc URLs resolve; unanswered questions stay unanswered; flags behave; weight updates follow the rules (one bad rating doesn't flip an edge, retired edges are never recommended). These are normal tests with exact expected results.
2. **Human-labelled gold sets:** ingestion extraction (hand-labelled nodes and edges for a reference proposal, measured by precision and recall), and scope extraction (a transcript or brief plus the answers a human gave in the answered bank).
3. **Model-graded rubrics:** quality scoring and the written parts of the solution. These won't return exactly the same number each run, so compare to your human scores by **rank and band** (good / ok / poor) and by agreement, not equality, and spot-check by a person.

**Per command**
- `/create-scope`: gold = questions the IM actually answered in the reference's bank. Measure recall of those questions and how many suggested questions weren't applicable. The deterministic tag path has exact tests.
- `/source-scope-answers`: for each bank question: correct, incorrect, missing, or invented; check unanswered stays unanswered; check manual answers win; check sanitization flag on/off.
- `/propose-solution`: **leave-one-out**. Remove proposal X from the graph, give the tool X's answered bank, and compare its recommended integration designs (precision and recall), docs, and template completeness with X. Then add proposals one at a time and plot the same metrics. That curve is also the demo that the tool improves as proposals are added.
- Ingestion: precision and recall against hand labels; run on every extractor change.
- Feedback processing: deterministic tests of the update rules.

**Caveats:** with four proposals (two platform-style references, plus the DIGITAL and UC ones coming) this is a smoke test, not statistics. Don't tune against the same cases you test on. Real transcripts are better than ones generated from the banks (which would be circular); do any exist?

Open: do answered question banks exist for the four proposals? Do real (redacted) transcripts or briefs exist? Who labels gold data? What pass threshold do we set for Monday?

### 4.23 Direction on privacy path and master doc (2026-10-22)
- **Privacy path for pasted transcripts: v2.** For Monday the paste path stays behind the feature flag (default off) as agreed, so nothing sensitive flows until it is cleared. To confirm.
- **Master proposal URL is an environment variable,** so we can test against a local directory of proposals before pointing at the live folder. The ingestion source is likewise configurable: a local directory first, then the Drive folder. Open: what format will the local directory hold (exports of Google Docs as .docx, .pdf or .md)?
- **Which questions go to project vs track sections:** discussed after the above.
- The next two reference proposals will be a **DIGITAL** one and a **UC** one, which will test whether ingestion generalizes beyond platform deals.

## 5. Questions for you (suggested order)

1. Share the **template** and the **scoping question bank** structure.
2. Walk me through how you build a proposal today, step by step, including where you look up past ones.
3. Which of the search questions in 4.5 would save you the most time? Which are missing?
4. What do you want a reference to look like in the output?
5. Where does merchant-confidential content stop, and do we need to redact on ingest?
6. Which two or three past proposals would make good test cases?

## 6. Decisions log

| Date | Decision | Notes |
|---|---|---|
| 2026-10-22 | A skill reads the Drive folder and pushes to our store | Agreed |
| 2026-10-22 | Gong is copy/paste until approved | Agreed |
| 2026-10-22 | Knowledge graph is a search feature; schema is not fixed yet | Depends on proposal structure and question bank |
| 2026-10-22 | End-of-proposal feedback: use both a quick 1–10 skill step and a Google Form link, collated in a Google Sheet | Agreed; an existing form is already linked from the template (4.8) |
| 2026-10-22 | The question bank is not the only source of scope answers; the tool reconciles answers from the bank, notes, proposal copy, transcripts and email | See 4.10 |
| 2026-10-22 | IM supplies channel, pillar, category, platform at the start | Used to select questions; assumed known |
| 2026-10-22 | Scope and Solution are separate components with different data sources | See 4.11 |
| 2026-10-22 | The IM provides links to their own question bank Sheet and proposal Doc; the tool adds new AI-assisted tabs to those same files and never modifies existing tabs | **Partly superseded** by the 2026-10-22 evening decisions below |
| 2026-10-22 | Two commands: `scope-creator` and `solution-generator`; the solution generator requires a fulfilled scope | **Superseded** by the four-command spec |
| 2026-10-22 | MCP type: IM MCP. Commands: `/create-scope`, `/source-scope-answers`, `/propose-solution`, `/create-adyen-diagrams` (nice to have) | See 4.15 |
| 2026-10-22 | `/create-scope` makes a new prefiltered question bank Sheet in the IM's Drive under `SolutionProposals/[merchant][timestamp]` and shares the link in chat; master bank ID in an environment variable | Replaces the Global Merchant Projects folder idea |
| 2026-10-22 | `/source-scope-answers` writes AI-assisted answers into a new sheet in the IM's question bank file; no full transcripts or briefs are stored | |
| 2026-10-22 | Feature flags: one for PII/IP sanitization, one for the Gong-sourcing command path (experimental until privacy clears it) | |
| 2026-10-22 | Gong: manual paste while there is no approved Gong MCP | |
| 2026-10-22 | `/propose-solution` creates a **new copy of the master proposal doc**, prefills it, and reuses it for the chat; question bank need not be complete (not a hard gate), output states it reflects the collected scope | Replaces the "fulfilled scope" gate and the tab-in-IM's-doc idea |
| 2026-10-22 | Solution sources for v1: current Adyen docs and prior proposals | Many deals are standard Adyen integrations |
| 2026-10-22 | Reference quality today = the two example proposals; quality measurement to be designed | See 4.13 |
| 2026-10-22 | First priority within CheckoutProposal: extract scope answers from transcripts into the assisted question bank | IMs' biggest pain is manual scoping |
| 2026-10-22 | `/create-scope` asks for all tag types (priority, subsection, channels, pillars, category, platform); a row is included if it overlaps any selected value; blank tag = applies to everyone | Table generated with a schema; invalid values reported; bank cleanup is separate work (4.16) |
| 2026-10-22 | Question matching uses both a deterministic tag query on the local table and model-based matching (no embeddings); results are combined and each question shows how it was found | See 4.16 |
| 2026-10-22 | Manual answers win over AI-assisted ones; inconsistencies are summarized with a link and the IM is asked before generation | |
| 2026-10-22 | Feedback step at the end of every command | |
| 2026-10-22 | Confluence removed; sources are public docs, the previous-proposal knowledge graph and the IM's input | |
| 2026-10-22 | Knowledge graph is in v1 scope (diagrams, patterns, docs, considerations, questions and answers) | Ontology in 4.16 is a draft |
| 2026-10-22 | Say "integration design", not "integration pattern" | Matches the proposal wording |
| 2026-10-22 | Links/IDs (question bank, master proposal, feedback form, seed, diagrams) are environment variables | |
| 2026-10-22 | ~~Knowledge graph stored locally~~ Shared data service (graph and normalized question bank tables), run in Docker locally for testing and hosted by us later; MCP tools query it | Supersedes the local-store decision; see 4.18 |
| 2026-10-22 | Seeded from existing proposals plus the owner's knowledge, partly synthetic and then edited; the owner curates | Lifecycle, structure and risks in 4.17 |
| 2026-10-22 | Curated mappings and the graph are both implemented behind one interface with a feature flag (curated / graph / both) to test results | See 4.18 |
| 2026-10-22 | Seed sheet "IM MCP - Integration Design Seed" is the curated-mapping source; link in an environment variable | Created 2026-10-22 |
| 2026-10-22 | `/create-scope` seeds the question tables periodically from the master bank | |
| 2026-10-22 | Graph search is a third source for `/create-scope` (design-linked questions, questions from similar completed proposals, candidate off-bank questions) | See 4.19 |
| 2026-10-22 | Only completed proposals shared with merchants (identified by naming convention) are ingested | |
| 2026-10-22 | Proposals are scored at ingestion against a standard; feedback updates edge weights via a recommendation trace; automation can demote/flag, only humans retire | Design in 4.19 |
| 2026-10-22 | Leaning Postgres for the shared service (question tables, graph, traces, feedback) | Subject to Adyen standards |
| 2026-10-22 | Cleanup of the master bank adds a stable `question_id` column | Dependency for graph, seed sheet and feedback |
| 2026-10-22 | The owner runs separate agents for bank cleanup and seed data; build can start | See docs/project-plan.md |
| 2026-10-22 | CheckoutLab and IM Researcher dropped from the Monday MVP | Design docs after Monday |
| 2026-10-22 | Postgres in local Docker; authentication in v2 | |
| 2026-10-22 | Master proposal filling: Discovery questions into 2.1.1, Features & Functionality questions into the 2.1.2 table (scope = question, finding = answer) | See 4.20 |
| 2026-10-22 | AI-assisted answers sheet uses the question bank's columns, same order | Provenance columns on the right proposed |
| 2026-10-22 | Seeding the graph from proposals (ingestion of the two references) is in v1, alongside the curated seed | See 4.20 |
| 2026-10-22 | Provenance columns (question_id, source, status, confidence, note) appended to the right of the AI-assisted answers sheet | Agreed |
| 2026-10-22 | A DIGITAL proposal and a UC proposal will be provided as further references | Tests generalization beyond platform deals |
| 2026-10-22 | `generation_id` (a generated draft) is separate from a Proposal node (a completed, shared, ingested proposal); linked later via `derived_from` | See 4.21 |
| 2026-10-22 | Feedback flow: 1–10 in chat, itemized follow-up on surfaced nodes when low, optional pre-filled Form, stored in Postgres; apply job updates edge evidence | Proposal in 4.21, for review |
| 2026-10-22 | Privacy path for pasted transcripts deferred to v2; paste path stays behind a flag (default off) for Monday | To confirm |
| 2026-10-22 | Master proposal URL and proposal source (local directory vs Drive folder) are environment variables so we can test locally first | See 4.23 |
| 2026-10-22 | Discussion order: feedback fields, evals and knowledge graph teaching, privacy (v2), master doc details, project-vs-track | |
| 2026-10-22 | Every core feature (CheckoutProposal, CheckoutLab, IM Researcher, etc.) ships with evals | Each feature design doc gets an Evals section; see 4.7 for the first ideas |
