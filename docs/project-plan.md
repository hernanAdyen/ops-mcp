# Project plan

Status and what comes next. Updated 2026-10-26. How it's built is in [architecture.md](architecture.md).
The earlier plan (2026-10-22) is in [archive/](archive/).

## Goal

MVP for Tuesday 2026-10-27 (end of day): the CheckoutProposal commands `/ops-create-scope`, `/ops-answer-scope` and
`/ops-create-solution`, each ending with the feedback form, on a shared data service (Postgres in Docker).

## Done

| Step | What | Notes |
|---|---|---|
| 1 | Project setup, settings and flags, health check | |
| 2 | Postgres in Docker, schema, migrations | Question bank, runs, review queue, graph tables |
| 3a | Loading the master bank from a CSV: dry run, apply, history | IDs are permanent; deactivate, don't delete |
| 3b | Tag query and topic matching with our model | Our model only adds from what the tags left out |
| 3c | `/ops-create-scope` | Sections and groups, master filter kept, Suggested additions for topic gaps, call-notes prompt |
| 4 | `/ops-answer-scope` | Answers from any merchant material, written into Project Scope; review in the sheet; jobs for slow runs; consent before sharing new questions |
| 4+ | Smaller `/ops-create-scope` batch | No sort when the master is in order (the master is now sorted by subsection, priority, ID) |
| 5 | Project tracks | A scope has one or more tracks, named by the IM at the start of `/ops-create-scope`, each with its own tags and its own tab (title = track name); the Introduction and Suggested additions in the first tab only; `/ops-answer-scope` runs per tab; tracks kept on the opportunity (migration 0004); `im_scope_start` is a job (`im_scope_wait`) |
| 7 | `/ops-create-solution` | Answers picked per track (own wins, suggested flagged, rejected skipped); research brief from the graph; the IM's model drafts; the server checks the draft and the copy's outline and returns one Docs batch (tokens, Discovery, Features table, diagram, links, a second track block removed); record points a `source` at the document. 892 doc pages loaded; diagram loader built (`im_graph_load_diagrams`). Run end to end on the Northwind test sheet 2026-10-27: 60 requests, no tokens left. Several tracks (one block each, built from the `{{Track}}` template) run twice on the Pepper Pies test sheet (US + FR) the same day: 230 requests, clean document. End-to-end pass on a fresh two-track sheet (Slice Street Pizza, US online + FR in-store) 2026-10-27: scope, answers, proposal (201 requests), each track's Discovery table carries its own answers only |
| 8 | Bank columns `purpose`, `baseline`, `status` (2026-10-27) | From the comparison with the coworker's Solution_Proposal_MCP: `purpose` goes into the extraction and topic-matching prompts; `baseline` questions join every scope within the IM's priorities and sections (`found_by` "baseline"); `status` `retired` deactivates a row in place. Migration 0006. `python -m imcp.bank.draft` drafts the two columns with our model into a CSV for the owner; the master stays theirs. Loaded as bank v4 the same day: 144 questions with a purpose, 7 baseline (background, goals, regions, payment methods, currencies, sales channels, user platforms); the model also offered submerchant count and websites, left out as platform- and online-only Tags from their 66-entry dictionary and the alias pre-pass were left out on purpose (the model's topic matching covers it; revisit if an eval shows keyword misses) |
| 9 | Scope over meetings (2026-10-27) | `/ops-answer-scope` after each call: a `date` per piece of material goes into `source` ("Call summary, 2026-10-24"); a finding that agrees with the IM's own answer sets `confirmed`, a different one sets `conflict` with the finding in `ai_note` (resolved in the sheet, no supersede flag); a Scope log tab, added on the first run and appended with `appendCells`, holds one line per change (time, track, question, change, answer, source, confidence, note); material already used on a tab (hash in a recorded run) is skipped, or refused when nothing else is passed; the proposal uses a `conflict` answer as it stands, flagged. From the coworker's design, without their Meetings tab and speaker roles |
| 10 | Transcript flag (2026-10-27) | `FLAG_TRANSCRIPTS`, on by default, shown in the health flags; off, `/ops-answer-scope` refuses material of kind `transcript` before anything reaches our model and asks for a summary or notes. Gong is cleared with Privacy; the flag is the switch the owner asked for |
| 11 | PII scrub (2026-10-27) | One module, `imcp.pii`, behind `FLAG_SANITIZE`: emails, phones, IBANs, Luhn-valid card numbers and keys replaced by bracketed words. Callers: the extraction (answers, evidence, new questions and reasons, on the way back to the chat and sheet; it already scrubbed emails and phones), the review queue wording, and the graph's asset loader (title and description of every page before it is stored or embedded, the gate the reference proposals will pass through). The skill sends Gong output as a file in `inputs/`, the only route that bypasses the chat model. Names still need the model: later, with the reference proposals |
| 12 | Install without Docker, data files in git (2026-10-27) | `uv run imcp-app` runs the app server; the app reads `.env` itself and takes the `APP_DB_*` names Docker uses, with `DB_HOST` defaulting to the machine; the Docker init SQL doubles as the local set-up. `data/graph/` (doc page rules, diagram registry) is tracked; the bank CSV stays a download from the master. Diagram images are published in the team's shared Drive folder with "anyone with the link", and the loader turns a share link into the direct image link Docs fetches |
| 6 | Embeddings and the doc page loader | `EmbeddingClient` (OpenAI-compatible `/embeddings`, called by the server with its own key; `EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY` fall back to the chat model's); `node.embedding` takes any size (migration 0005), each node records its model, no normalising, cosine distance, exact search; `im_graph_load_docs` reads the Adyen docs index (`DOCS_INDEX_URL`, `llms.txt`) and the rules file `data/graph/adyen-doc-pages.csv` (about 950 of 1,300 non-payment-method pages) and loads one asset node per page: link, title, one-line description, tags, embedding, never the content; dry run then apply, deprecate not delete, `ingestion_run` recorded; `nearest_assets` search. Not yet run against the live index with a real embedding model |

## Next

Agreed with the coworker's implementation in view (2026-10-27): one question bank, on our IDs; the
Docker setup stays until the backend is hosted; Gong material is fine (cleared) but behind a flag; the
scope lives across meetings; the diagram registry is decided later. In order:

1. **Real diagrams:** the owner's curated folder, then the CSV (PNG, JPEG or GIF only: Docs can't insert
   SVG). Loader built and run with one stand-in.
2. **Ingest the reference proposals into the graph** (the owner brings them), so designs,
   considerations and their edges come from real proposals and the tool improves as more are added.
3. **Evals:** a second extraction case for the two prose misses (token migration, loyalty) and for the
   spurious NEW- question seen on the end-to-end pass (below); leave-one-out on the reference proposals.
4. **Documentation link titles:** a page the graph doesn't know is listed by its bare URL (seen with
   the reconciliation page). Load the missing docs sections or let the server fetch a title.
5. **Master fixes, by the owner:** the 2.2.1 Discovery table header still reads "Question | In Scope"
   (the plan requires "Answer"), and the empty paragraph before the "3.0 Solution" title table still
   carries direct formatting (15 pt, grey), which a further track's Discovery table inherits. Both were
   patched by hand in the copy on every run so far.

Commands renamed 2026-10-27: `/create-scope` → `/ops-create-scope`, `/source-scope-answers` →
`/ops-answer-scope`, `/propose-solution` → `/ops-create-solution`. New runs are recorded under the new
names; `/ops-answer-scope` still finds earlier runs recorded under the old one.

### Learned on the first real run (2026-10-27, Northwind test sheet)

- One track-level query found overview pages and checklists; the useful pages (the plugin, the token
  import) turned up only in the research. The brief now searches once per requirement and merges.
- Everything the IM is told to confirm is noise when all answers came from material: the reply now
  gives counts only. The call-notes prompt is offered after the sheet, as a tab, never printed.

- The Docs API refuses to delete the newline of the paragraph right before a table. Block removals and
  emptied placeholders keep their final newline; `FakeDoc` enforces the same rule.
- `insertInlineImage` with a width only keeps the aspect ratio (440 pt wide came out 286 pt high).
- `replaceAllText` also touches the stale table of contents, so the TOC shows old heading names until
  the IM refreshes it (the reply tells them).
- A `documents.get` of the master is 120 KB of JSON; the skill derives the outline (97 elements, 8 KB)
  and the server's contiguity and table checks accepted it first time.
- Docs can't insert SVG images: the diagram URLs must be PNG, JPEG or GIF.

### Learned on the first two-track run (2026-10-27, Pepper Pies test sheet, US + FR)

- The owner's master keeps a `{{Discovery}}` paragraph next to each Discovery table. The plan now
  empties that paragraph when it fills the table, and a further track's block writes the answers once,
  in the table, never as paragraphs as well.
- `insertTable` adds its own newline, so an empty template paragraph before a table isn't written
  again; nor is the empty paragraph that ends the template block (the insertion point stays as the
  separator). A removed block followed by a paragraph is deleted whole, newline included; only a block
  followed by a table (a section title) leaves one empty paragraph behind.
- A sheet checkbox writes TRUE/FALSE on NEW- rows too; those now read Yes/No in the document.
- The 302-request batch (two tables of 18 and 4 rows built from scratch, an image, two bullet lists,
  two block removals) was accepted first time: the computed table geometry matches the live API.
- The master's 2.2.1 Discovery table header read "Question | In Scope"; the plan requires "Answer".
  Fixed in the copy by hand for this run; the master needs the same fix.
- The template solution block has no 3.x.1 heading, so neither does any track's block: the
  considerations follow the block heading. Adding "3.2.1 Technical Considerations" to the master's
  template block fixes it for every run (done by the owner the same day).

### Learned on the end-to-end pass (2026-10-27, Slice Street Pizza test sheet, US online + FR in-store)

- `/ops-create-scope` (47 and 56 questions), `/ops-answer-scope` on both tabs from one Gong summary
  (13 and 17 answers) and `/ops-create-solution` (201 requests) ran clean, with no code changes. The
  mixed-track answers seen on the Pepper Pies sheet came from the extraction run before the per-track
  prompt fix: on the fresh sheet each tab holds only its own track's facts.
- With the master's look in its named styles (Normal, Heading 2, Heading 3), a block built from scratch
  renders like the master's own block. Tables built from scratch use the Normal size, where the master's
  tables carry 10 pt as direct formatting; the owner prefers it that way.
- Extraction wrote a NEW- question (offline sync) on the in-store tab while the bank question that covers
  it (ID-0070, Offline Processing) stayed empty: the closest-question rule missed. The proposal shows
  the NEW- row's Yes; the eval needs a case for this.
- Two online questions (websites, API credentials) reach the in-store tab through the tag filter and
  show up among its open priority-1 questions. A tag or channel on those bank questions would keep
  them out.

### Learned on the live check of the scope over meetings (2026-10-27, Slice Street test sheet, US tab)

- A second, dated call summary on the US tab: 6 answers filled with `source` "Follow-up call summary,
  2026-10-27", 2 rows marked `conflict`, the Scope log tab added with sheetId 1002 (1001 was already the
  FR tab) and 8 lines appended; the same material again was refused with the date of the first use.
  `addSheet` + `appendCells` behave on the real API as on `FakeBook`.
- **A false conflict:** the model wrote "USD only" where the sheet says "USD", so the row became a
  conflict. `same_answer` compares words, and the model never sees the sheet's current answer. The fix
  to measure with the next eval case: show the model the current answer of each answered question and
  have it return `same` when the material agrees, so a conflict means a real difference. A looser text
  match is the wrong fix: "USD" against "USD and EUR" must stay a conflict.
- `feedback_url` in the record result is whatever `FEEDBACK_FORM_URL` holds; on this machine it points
  at the question bank sheet, so the form link in `.env` wants checking.

### Learned on the showcase runs (2026-10-27, Harbor Coffee and CourtSide Bookings test sheets)

- Three scopes, four answer tabs and two proposals in one evening with no code changes. The baseline
  questions, the dated sources and the Scope log all showed up as designed.
- **Spurious new questions on an in-store tab:** the Harbor Coffee In-store NL run filled 44 answers
  correctly and then added 8 NEW- rows that reword questions it had just answered (offline processing,
  refunds at another store, store ID in reporting, tipping, standalone terminals, tap to pay). The
  "covered by a bank question" check only fires when the model names the closest ID, and the wording
  check compares words. A fix to measure: before a new question is kept, compare it with the questions
  answered in the same run by meaning (the model can be asked, in the second pass, which listed question
  each proposed new question repeats), and drop it when one matches. Add the case to the evals.
- `im_answers_start` results run to 70 to 90 KB for a 50-row tab, mostly the Scope log lines repeated
  in the batch. Claude Desktop handles it; a smaller batch (one `appendCells` row per change is already
  minimal) would need the log to carry less text, which is a design choice for later.

## /ops-create-solution design (agreed so far, 2026-10-26)

Writes the solution proposal for one merchant from their scope sheet. Same shape as the other
commands: **start → (plan) → write → record**. Status: not built. Two points are still open (see the end).

### The document

A copy of the proposal master (`PROPOSAL_MASTER_URL`), filled by replacing `{{tokens}}`. The master is
a single-tab Google Doc (the Docs API can't delete tabs, so the multi-tab template library can't be the
master) that a person prepares from the EN template:

- `{{Merchant Name}}` on the cover and in the header, as now.
- 1.1 to 1.3 stay boilerplate; the Stakeholders table is left for the IM.
- 1.4 `{{Project Background}}` and 1.5 `{{Project Goals}}`: our model writes them from the two
  Introduction questions (ID-0083, ID-0084). One introduction per proposal.
- **The track blocks** for sections 2 and 3: `2.1 Project Scope` with 2.1.1 Discovery (a table whose
  header row reads "Question" and "Answer", with exactly one empty body row; a `{{Discovery}}`
  paragraph still works) and 2.1.2 Features & Functionality (a table whose header row reads "Feature &
  Functionality" and "In Scope", with exactly one empty body row), and `3.1 Project Solution` with
  3.1.1 `{{Technical Considerations}}`, 3.1.2 `{{Integration Design}}`, 3.1.3 `{{Flow Diagrams}}`,
  3.1.4 `{{Documentation}}`. The owner's master (2026-10-27) also keeps a second block, `2.2 {{Track}} -
  Scope` and `3.2 {{Track}} - Proposed Solution`, with the same parts: with one track the server removes
  it whole; with several it is the template to duplicate (next). The "Project Track Description" and
  "Focus Areas" lines became Discovery questions in the bank.
- 2.x.1 Discovery: one table row per answered question, in sheet order (question | answer; toggles
  read Yes/No). Unanswered questions are left out.
- 2.x.2 Features & Functionality: answered questions only. Toggles get a check mark in "In Scope" when
  yes; other types get the answer text. The bank's F&F questions that should be toggles are to be fixed
  in the master bank and reloaded (15 of 42 aren't toggles today).
- Sections 4 (Timeframe) and 5 (Conclusion) keep their boilerplate untouched.
- The table of contents can't be refreshed by the API: the reply tells the IM to update it.

Each track tab of the scope sheet gives one 2.x and one 3.x block, in tab order.

### How it works

1. **Read the scope.** The skill reads every track tab (ID, answer and review columns only) and sends
   them to `im_proposal_start`, with the tab titles.
2. **Pick the answers to use (server).**
   - An IM's own answer (no `source`, or `status` = confirmed) wins.
   - `suggested` answers are used but marked in the trace, and listed for the IM to check.
   - `rejected` answers are skipped.
3. **Coverage note, not a gate.** Open priority-1 questions are listed in the reply. The proposal is
   still written.
4. **Build the research brief (server).** Decided 2026-10-26: no curated seed. The server turns the
   track's answers into requirements, walks the graph (designs, considerations and their edges, as the
   ingested proposals filled them) and runs `nearest_assets` over the doc pages and diagrams, narrowed by
   the track's tags. It returns, per solution subsection, the links with their titles and descriptions
   (plus each page's `.md` link, which is lighter to read), the known designs and considerations, and
   instructions on how to research what is missing on docs.adyen.com. Documentation links never come
   from a model: only from asset nodes.
5. **Research and draft (the IM's own model, in their harness).** The IM's model follows the links,
   reads the pages and drafts section 3 and 1.4/1.5. Better models make this better; the graph is
   what we add. The draft comes back to the server, which checks it: only known section keys, every
   link is an asset node (or a page under the docs host), length limits. The checked draft is later
   ingestion material, so each proposal grows the graph. This changes design rule 4's "our model does
   the reading" for the proposal's research step; the server still owns the document.
6. **Make the doc (skill).** Copy `PROPOSAL_MASTER_URL` into `SolutionProposals`, named
   "<Merchant> - Solution Proposal".
7. **Fill the doc (server plans, skill sends).** The skill reads the copy and passes a compact outline
   (one line per paragraph or table: start index, end index, first words). The server checks the outline
   against the tokens it expects and refuses if anything doesn't line up, then returns an exact Docs
   `batchUpdate`, edits ordered back to front, relayed unchanged: token replacements, the Discovery
   paragraphs, the F&F table rows, and the regenerated blocks for further tracks. Chunked per section
   if it gets big.
8. **Record.** `im_proposal_record` reads back that no `{{` tokens are left, saves the generation
   with a recommendation trace (which rules or graph nodes fired, which answers were used, by ID; never
   the text), and returns the feedback link.

### Code

Built 2026-10-26; see the code map in architecture.md. `src/imcp/proposal/` (answers, brief, outline,
draft, doc_plan, runs), `src/imcp/app/proposal_api.py`, the three tools, `skills/ops-create-solution/SKILL.md`,
and `tests/fake_doc.py` (plays a Docs batch on an index model). One track per document so far.

### Decided 2026-10-26

1. **No curated seed.** The graph is filled by ingestion only: the Adyen docs index (done, row 6), the
   owner's diagrams (next) and the reference proposals (the owner brings them). The IM's own model does
   the live research, equipped with the graph's links and the known designs and considerations.
2. **Flow diagrams** go into the asset table with a title, description and tags, embedded, and are picked
   per track by `nearest_assets`. Not links, not tag matching. Waiting on the curated folder.
3. **Features & Functionality table:** every answered F&F row goes in. A toggle shows a ticked box when
   yes and an empty box when no (the row stays even when toggled off); a written answer shows its text.
   Unanswered questions are left out.
4. **Embedding model:** text-embedding-3-small now for testing (1536 wide), qwen3-embedding-8b (4096)
   later, no normalising in either case. The column takes any size; switching model re-embeds on the
   next load.

## Evals (started 2026-10-27)

`evals/` holds fictional cases with known right answers and `run_extraction.py`, which sends a case's
tabs to the app server as the skill would and scores the result: gold answers by ID, track leaks,
cross-track bank additions, spurious new questions. See `evals/README.md`. First case:
`slice-street-pizza`, a two-track Gong summary.

Baseline (before the fixes): US 7/18 gold checks, 9 leaks, 5 cross-track additions, 2 spurious new
questions; FR 8/20, 6 leaks, 1 cross-track, 3 spurious. The extraction mixed both tracks into every
answer, missed answers given by ID, and wrote new questions for topics the bank already asks.

Fixes made against it: the extraction prompt names the tab's track and tells the model to use that
track's section only; a "new" question whose nearest bank question covers it becomes that question's
answer when the formats fit (a toggle's yes/no, a free-text question takes the model's reason), and is
dropped when it has no answer and the sheet already asks the bank question; undecided, "to be confirmed",
"not discussed" and "not applicable" are no answer for any type; a toggle answered with a sentence that
starts with yes or no counts.

After the fixes (same case, same model): US 17/18 gold checks, FR 19/20, no leaks, no cross-track
additions, no spurious new questions. The two misses left are prose remarks the model didn't tie to
their bank questions (token migration ID-0057 on US, loyalty ID-0072 on FR).

Second case, `slice-street-follow-up` (2026-10-27): a later call on the US tab with the tab's current
answers, scoring `agrees` and `conflict` as well as fills. Baseline, before the model saw the current
answers: 13/16 gold checks; the material restating "USD" as "USD only" and "United States" as "US only"
came back as two false conflicts, and one prose remark (expired cards, ID-0079) was missed. Fix: the
extraction prompt shows each answered question's current answer and the model answers `same` when the
material agrees; the server then uses the sheet's own wording, so the merge sees an agreement. After,
three runs each: 13/16, 13/16, 14/16. The "USD only" conflict is gone; a shorter restatement of the
regions answer ("US only" against "United States only for online track") is still read as a change
in two runs of three, and the two prose remarks stay missed.

Two prompt rules were tried the same day for the prose misses and the restatement, with examples: the
follow-up case went to 16/16, 15/16, 15/16, but the first case fell from 17/18 and 19/20 to 15/18
and 18/20, stably, because the model started copying remarks word for word instead of picking the
question's options. Without the examples the first case came back (17, 16, 16 of 18; 18/20) and the
follow-up lost the prose hits again. The lesson: with this model, a rule aimed at prose matching
trades against option formatting, so the prompt keeps only the `same` rule, and the prose misses need
a targeted step rather than another prompt line: after the ID-based extraction, a second call that
takes the sheet's unanswered questions and the material's prose paragraphs only and asks which of
those questions the prose answers. Built the same day (`_prose_pass` in `extract.py`, skipped when the
material has fewer than two lines that aren't ID answers; a failure keeps the first pass; counts in the
trace under `prose_pass`). The FR tab's offline-processing remark (ID-0070) is a third instance of the
same miss.

With the second pass, three runs each (2026-10-27, gpt-4.1-mini):

| Case | Before the day | With the second pass |
|---|---|---|
| `slice-street-pizza` US | 17/18 | 15, 17, 17 of 18 |
| `slice-street-pizza` FR | 19/20 | 19, 18, 18 of 20 |
| `slice-street-follow-up` | 13/16 (two false conflicts) | 15, 15, 15 of 16 |

What the second pass fixed: the follow-up's prose remarks (custom UI, expired cards) are found every
run, the US token-migration remark now and then, the FR offline-processing remark once in three; the
false "USD only" conflict is gone. What it cost at first: FALSE on toggles the call never mentioned,
fixed by letting a toggle from prose be TRUE only. What is left: ID-0077 on US comes back as a sentence
instead of the CardOnFile option in every run (a first-pass formatting wobble that started with the
`same` rule's line in the prompt and survived its rewording), ID-0098 once in three, FR loyalty
(ID-0072) every run, and the follow-up's regions restatement ("US only" against "United States only for
online track") read as a conflict every run. Fixed the same evening (deterministic, no model): a choice option is found by its core words (the text
outside its parentheses, or the letters inside them in any spacing or case, never after "no"/"not"),
once an option is named the leftover words go to the note instead of the answer, and for free text a
finding that repeats part of the current answer counts as agreement. The second pass is told that
notes under no track apply. Three runs each: first case US 17, 17, 18 of 18 (the card-on-file row now
names the option, with the leftover words appended until the note fix, which is deterministic), FR
18, 19, 18 of 20; follow-up 16/16 three times. Left: FR loyalty (ID-0072) every run and FR offline
processing (ID-0070) two runs in three, both prose remarks the second pass doesn't tie to the FR tab.

## Backlog

- **Extraction misses.** Measured by the eval above; earlier seen as ID-0098 answered "Other" instead of
  ERP and ID-0139 and ID-0065 missed. Answering by section in parallel calls would also make runs faster.
- **A curator step for the review queue** (`/review-questions`): you approve, edit or reject queued
  questions and approved ones are added to the master with the next free IDs.
- **Server-side Google access** (a service account), so batches don't pass through Claude. Needs a
  decision on who owns the files, and approval.
- **Jobs that survive an app restart** (they are in memory now), and MCP progress updates once clients
  support them.
- **Topic matching sometimes calls a covered topic "uncovered"** (seen with token migration).
- **A loader guard:** refuse a CSV that has a `found_by` column (a scope sheet, not the master) or
  that would deactivate more than about 20% of the bank.
- **Privacy sign-off** on what a queued question keeps, before turning the queue on for everyone.
- **Later features:** CheckoutLab, IM Researcher, CheckoutPost, `/create-adyen-diagrams`.
- **From the coworker's Solution_Proposal_MCP, left out for now** (comparison 2026-10-27): the
  66-entry tag dictionary with aliases and a deterministic alias pre-pass in scope start; an Initial
  Call agenda tab with follow-up probes; `[Draft]`/`[Completed]` naming, a deviations note and update
  runs that keep the engineer's edits; a write plan shown before every write (our server already plans
  every write exactly). A local project folder, BM25 ranking and the fresh-sheet build are not wanted.

## Working on more than one machine

The repo holds code, skills and docs only. Each machine keeps its own settings, and none of them
move between laptops:

| On each machine | Where | Work laptop | Personal machine |
|---|---|---|---|
| `.env` | repo folder, git-ignored | internal images, mirror and model | blank images and index (public), an OpenAI key |
| Package index for `uv` | your user's uv settings | the internal mirror | nothing (public PyPI) |
| `uv.lock` | repo folder, git-ignored | made from the mirror | made from PyPI |
| Claude desktop MCP settings | Claude's config file | path to your clone | path to your clone |
| `data/` (bank CSVs), `inputs/` (merchant material) | repo folder, git-ignored | | |

The exact versions of every package are pinned in `pyproject.toml`, so both machines install the
same versions from their own index. Merchant material and work sheets stay on the work laptop.
