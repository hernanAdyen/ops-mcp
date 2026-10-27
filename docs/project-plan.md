# Project plan

Status and what comes next. Updated 2026-10-26. How it's built is in [architecture.md](architecture.md).
The earlier plan (2026-10-22) is in [archive/](archive/).

## Goal

MVP for Tuesday 2026-10-27 (end of day): the CheckoutProposal commands `/create-scope`, `/source-scope-answers` and
`/propose-solution`, each ending with the feedback form, on a shared data service (Postgres in Docker).

## Done

| Step | What | Notes |
|---|---|---|
| 1 | Project setup, settings and flags, health check | |
| 2 | Postgres in Docker, schema, migrations | Question bank, runs, review queue, graph tables |
| 3a | Loading the master bank from a CSV: dry run, apply, history | IDs are permanent; deactivate, don't delete |
| 3b | Tag query and topic matching with our model | Our model only adds from what the tags left out |
| 3c | `/create-scope` | Sections and groups, master filter kept, Suggested additions for topic gaps, call-notes prompt |
| 4 | `/source-scope-answers` | Answers from any merchant material, written into Project Scope; review in the sheet; jobs for slow runs; consent before sharing new questions |
| 4+ | Smaller `/create-scope` batch | No sort when the master is in order (the master is now sorted by subsection, priority, ID) |
| 5 | Project tracks | A scope has one or more tracks, named by the IM at the start of `/create-scope`, each with its own tags and its own tab (title = track name); the Introduction and Suggested additions in the first tab only; `/source-scope-answers` runs per tab; tracks kept on the opportunity (migration 0004); `im_scope_start` is a job (`im_scope_wait`) |
| 7 | `/propose-solution` (one track) | Answers picked per track (own wins, suggested flagged, rejected skipped); research brief from the graph; the IM's model drafts; the server checks the draft and the copy's outline and returns one Docs batch (tokens, Discovery, Features table, diagram, links, a second track block removed); record points a `source` at the document. 892 doc pages loaded; diagram loader built (`im_graph_load_diagrams`). Run end to end on the Northwind test sheet 2026-10-27: 60 requests, no tokens left |
| 6 | Embeddings and the doc page loader | `EmbeddingClient` (OpenAI-compatible `/embeddings`, called by the server with its own key; `EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY` fall back to the chat model's); `node.embedding` takes any size (migration 0005), each node records its model, no normalising, cosine distance, exact search; `im_graph_load_docs` reads the Adyen docs index (`DOCS_INDEX_URL`, `llms.txt`) and the rules file `data/graph/adyen-doc-pages.csv` (about 950 of 1,300 non-payment-method pages) and loads one asset node per page: link, title, one-line description, tags, embedding, never the content; dry run then apply, deprecate not delete, `ingestion_run` recorded; `nearest_assets` search. Not yet run against the live index with a real embedding model |

## Next

1. **The block for further tracks:** `im_proposal_plan` takes one track today. The owner's master keeps
   a second block ("2.2 {{Track}} - Scope", "3.2 {{Track}} - Proposed Solution") that the one-track plan
   removes; for several tracks it is the template to duplicate, by index, once per further track
   (headings, paragraphs, a table). Decide first whether 2.1/3.1 stay a project-level block or become
   track 1.
2. **Real diagrams:** the owner's curated folder, then the CSV (PNG, JPEG or GIF only: Docs can't insert
   SVG). Loader built and run with one stand-in.
3. **Ingest the reference proposals into the graph** (the owner brings them), so designs,
   considerations and their edges come from real proposals and the tool improves as more are added.
4. **Evals:** leave-one-out on the reference proposals; extraction checked against answered banks.

### Learned on the first real run (2026-10-27, Northwind test sheet)

- The Docs API refuses to delete the newline of the paragraph right before a table. Block removals and
  emptied placeholders keep their final newline; `FakeDoc` enforces the same rule.
- `insertInlineImage` with a width only keeps the aspect ratio (440 pt wide came out 286 pt high).
- `replaceAllText` also touches the stale table of contents, so the TOC shows old heading names until
  the IM refreshes it (the reply tells them).
- A `documents.get` of the master is 120 KB of JSON; the skill derives the outline (97 elements, 8 KB)
  and the server's contiguity and table checks accepted it first time.
- Docs can't insert SVG images: the diagram URLs must be PNG, JPEG or GIF.

## /propose-solution design (agreed so far, 2026-10-26)

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
- **One track block** for sections 2 and 3: `2.1 {{Track}} Scope` with 2.1.1 Discovery
  (`{{Discovery}}`) and 2.1.2 Features & Functionality (a table whose header row reads "Feature &
  Functionality" and "In Scope", with exactly one empty body row), and `3.1 {{Track}} Solution` with
  3.1.1 `{{Technical Considerations}}`, 3.1.2 `{{Integration Design}}`, 3.1.3 `{{Flow Diagrams}}`,
  3.1.4 `{{Documentation}}`. The server fills the block for the first track and regenerates it for
  each further track (2.2, 3.2, ...), writing the numbers and names itself. With one track the headings
  read "Project Scope" and "Project Solution". The grey placeholder images, the second block, the stray
  empty heading and the "Project Track Description" and "Focus Areas" lines are removed from the master
  (the last two become Discovery questions in the bank).
- 2.x.1 Discovery: question and answer, in sheet order, answered questions only (bold question, plain
  answer). Unanswered questions are left out.
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
draft, doc_plan, runs), `src/imcp/app/proposal_api.py`, the three tools, `skills/propose-solution/SKILL.md`,
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

## Backlog

- **Extraction misses.** In the Safelite test our model answered ID-0098 wrongly ("Other" instead of
  ERP) and missed ID-0139 and ID-0065. Tighten the prompt, or answer by section in parallel calls
  (also makes runs faster).
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
