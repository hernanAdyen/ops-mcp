# Architecture

How the IM MCP is built, and the design rules that keep it that way. Read this before changing code.
What is built and what comes next is in [project-plan.md](project-plan.md). The graph's vocabulary is
explained in [knowledge-graph-primer.md](knowledge-graph-primer.md). Older design discussions are in
[archive/](archive/) for history only.

## 1. What it does

The IM MCP gives Adyen implementation managers (IMs) commands in Claude for scoping a merchant
integration and writing the solution proposal:

| Command | What it does | Status |
|---|---|---|
| `/ops-create-scope` | Picks the scoping questions for one merchant from the master question bank (by tags, the bank's baseline questions, plus our model matching the IM's notes) and builds a scope sheet in the IM's Drive, one tab per project track | Built |
| `/ops-answer-scope` | After each call: finds the answers in whatever the IM has from the merchant (notes, a call summary, a transcript, an email, each with its date) and writes them into a track's tab of the scope sheet for the IM to review. The scope builds up over meetings: an answer the material agrees with is confirmed, one it contradicts is marked as a conflict, and every change is logged in the sheet's Scope log tab | Built |
| `/ops-create-solution` | Writes the solution proposal from the scope: the merchant's answers, a research brief from the knowledge graph, the IM's model's researched solution, a diagram and documentation links, into a copy of the proposal master | Built; run on real documents with one and two tracks |

Each command is a **skill** (`skills/<name>/SKILL.md`): plain instructions Claude follows, calling our
tools and the IM's Google connectors.

## 2. The pieces

```
 IM's Claude (desktop)
   │  skills: /ops-create-scope, /ops-answer-scope
   │
   ├── Google Drive and Sheets connectors (the IM's own access)
   │
   │  MCP (stdio)
   ▼
 IM MCP server            src/imcp/mcp_server.py   runs on the IM's laptop: `uv run imcp-mcp`
   │  HTTP (localhost:8787)
   ▼
 App server               src/imcp/app/            FastAPI, in Docker
   ├── Postgres 18 + pgvector                      in Docker: question bank, runs, review queue, graph
   ├── Our model                                   any OpenAI-compatible chat API
   └── Our embeddings                              any OpenAI-compatible /embeddings (same host by default)
```

- **Claude** holds the conversation, asks the IM for input, and moves data between our tools and
  Google. It never decides which rows to keep or where to write them.
- **The IM MCP server** is thin: it checks arguments, reads files from two local folders (`data/` for
  bank CSVs and the graph's rules files, `inputs/` for long merchant material) and forwards everything
  to the app server.
- **The app server** does the work: queries, our model and embedding calls, validation, and building
  the exact Sheets edits. It has no Google credentials. The IM never gives us a key: the model and
  embedding keys are the server's own settings.
- **Postgres** stores the question bank, every run (`generation`), the review queue and the proposals
  graph (nodes with embeddings, edges, assets).

## 3. Design rules

These are deliberate. Changing one is a design decision to discuss first, not a refactor.

1. **The server decides, Claude relays.** Filtering, ordering, row positions and validation happen on
   the app server. It returns an exact Sheets `batchUpdate`, and the skill sends it unchanged. Claude
   never computes rows or cells.
2. **Keep what passes through Claude small.** Every character Claude relays costs time (it writes it
   out). Return summaries and counts, not lists; skip work that isn't needed (for example, no sort
   when the rows are already in order); read only the columns a step needs.
3. **No Google access on the server (for now).** All Drive and Sheets work goes through the IM's own
   connectors in their Claude session. Files stay private to the IM.
4. **Our model does the heavy reading, on the server, and is never trusted blindly.** Topic matching
   and answer extraction run on our model so Claude doesn't have to hold the whole bank. Everything it
   returns is checked: unknown IDs are dropped, answers are put in the question's format, new questions
   that repeat a bank question are dropped. The extraction reads twice: once for everything, then a
   narrow second call with only the sheet's still-unanswered questions and the material's prose, which
   can add answers for those questions and nothing else (skipped when the material is all ID lines).
5. **Privacy by default.** Merchant material and the answers found are never stored or logged. What our
   model found is scrubbed of email addresses, phone numbers, IBANs, card numbers and keys (`imcp.pii`,
   behind `FLAG_SANITIZE`) before it goes back to the chat and the sheet, and so is every page's title
   and description before it enters the graph. The skill sends Gong output as a file in `inputs/`, the
   one route that bypasses the chat model. A run's
   trace keeps question IDs, counts and hashes. The IM's notes are sent to the model but never stored.
   Call transcripts (material of kind `transcript`) are accepted only while `FLAG_TRANSCRIPTS` is on (the
   default); off, `/ops-answer-scope` refuses them and asks for a summary or notes.
   The review queue gets only the generic wording of new questions, behind `FLAG_CANDIDATE_QUEUE` and
   the IM's consent.
6. **The master bank belongs to people.** Only a person edits it. It is loaded from a CSV download with
   a dry run first. Question IDs are permanent: never reused, never renumbered. Questions are
   deactivated, not deleted: a row that leaves the master, or whose `status` says `retired`, is
   deactivated and keeps its history. Columns our model drafts (`purpose`, `baseline`) go to a CSV for
   the owner to review and paste in; nothing writes to the master.
7. **The IM owns their sheet.** We only add: fill empty answers, add review columns, add rows at the
   end, append to the Scope log. We never overwrite the IM's answers; a different finding goes in a
   note and marks the row `conflict`, a finding that agrees marks their answer `confirmed`. The IM
   reviews in the sheet, and the next run reads what they changed.
8. **Slow work is a job.** Calls through a remote bridge can be cut off at 60 seconds. Anything slow
   runs as a job on the app server; each call waits up to 40 seconds and returns a job ID to ask again.
9. **Every run is recorded.** Each command run is a `generation` row with a trace (what was asked and
   chosen, never free text) and ends with the feedback form link.
10. **Configuration only through environment variables.** Links, model settings and flags live in
    `.env` (see `.env.example`). Nothing is hard-coded, so we can point at test copies.
11. **The graph points, the IM's model reads.** An asset node (a doc page, a diagram) keeps only what
    points at it: link, title, one-line description, tags and the embedding of title + description.
    Never the page content. The graph finds the right pages for a track; the IM's own model follows the
    links and does the reading and research. Documentation links in a proposal only ever come from
    asset nodes, so they are always real.
12. **The embedding model is a setting, and each node records which model embedded it.** The
    `node.embedding` column has no fixed size (text-embedding-3-small is 1536 wide, qwen3-embedding-8b
    4096). Vectors are stored as the model made them, no normalising, compared by cosine distance, and a
    search only compares nodes embedded by the query's model. Changing model means re-embedding, which the
    loaders do on their next apply.

## 4. How a command works

Each command follows the same shape: **start → (plan) → write → record**.

### Project tracks

A scope has one or more **project tracks**: the parts of a project the IM wants to scope and propose
separately (e.g. "Ecommerce US" and "In-person payments UK"). The IM names them at the start of
`/ops-create-scope`, and each gets its own tags and its own tab in the scope sheet, titled with the track's
name. The default is one track, whose tab keeps the master's name, Project Scope. The two Introduction
questions and the Suggested additions go in the first tab only: there is one introduction per proposal.
The tracks and their tags are kept on the `opportunity` (`tracks`); the tab title is the track name
everywhere else. `/ops-answer-scope` fills one tab per run; `/ops-create-solution` will write one
block of sections per track.

### /ops-create-scope

1. The skill asks the IM for the merchant, the tracks (one short message; "one" is the usual answer),
   tags (one question card per track: channels, pillars, categories) and notes.
2. `im_scope_start` (a job: `im_scope_wait` until it's done): per track, the server selects questions
   by tags and adds the bank's baseline questions (in every scope, whatever the tags, within the
   priorities and sections asked for); our model adds questions for topics in the notes, told which
   track it is choosing for, and drafts a question for each topic the bank doesn't cover (once, for the
   project). A draft run is saved.
3. The skill copies the master bank into the IM's `SolutionProposals` folder and reads column A, the
   header row, the filter and every tab's sheetId.
4. `im_scope_sheet_plan`: the server returns one batch that renames Project Scope to the first track,
   duplicates it once per further track (before any row is touched, so each tab starts from the same
   rows), and in each tab deletes the rows not in that track, adds `found_by`, orders and groups the
   rows by section, adds **Suggested additions** at the end of the first tab, and keeps the master's filter.
5. The skill sends the batch, reads column A of every track tab back, asks consent if there are new
   questions, and calls `im_scope_record`: the read-back check per tab, the deal with its tracks and the
   review queue. The copy goes into the IM's own folder when their MCP config names one
   (`PROPOSALS_DRIVE_FOLDER_URL` in `McpSettings`, returned by the start tools as `proposals_folder_url`).
6. After the reply, the skill offers the call-notes prompt. On a yes, `im_scope_call_prompt` returns a
   small batch that adds a `Call prompt` tab with the prompt text, and the IM gets a link to that tab,
   so nothing long passes through chat. The offer comes after the sheet, never before.

### /ops-answer-scope

1. The skill gets the scope sheet, which track tabs the material covers (asked only when there are
   several) and the merchant material, each piece with a label, a kind and its date. Then, tab by tab,
   it reads the tab's ID, answer and review columns.
2. `im_answers_start` (a job: `im_answers_wait` until it's done), with the tab's title: the server
   first drops any piece already used on that tab (same text, by its hash in a recorded run) and
   refuses when nothing is left; our model answers that tab's questions and lists new ones; the server
   checks them (a second, narrow call reads the prose for the questions still unanswered) and returns
   one batch that fills empty answers (`source` = label and date), confirms
   the IM's answers the material agrees with, marks a different finding `conflict` with the finding in
   `ai_note`, adds the review columns and Suggested additions to that tab, and appends one line per
   change to the sheet's Scope log tab (added on the first run). The scope is built over several
   meetings this way; the IM resolves a conflict in the sheet.
3. The skill sends the batch, reads column A back, asks consent, and calls `im_answers_record`.

### /ops-create-solution

The one command where the IM's own model writes: the server makes no chat model call here.

1. The skill reads the track tab's ID, answer, status, source and question columns and calls
   `im_proposal_start`. The server picks the answers (the IM's own win, `suggested` and `conflict` ones
   are used as they stand but flagged, `rejected` are skipped), lists the open priority-1 questions, and
   builds the **research
   brief** from the graph: the requirements, the nearest doc pages (one search per requirement, merged,
   then the whole track to fill up; each page says which requirement IDs it is for) and diagrams, narrowed
   by the track's tags from `opportunity.tracks`, the designs the graph knows, and instructions.
2. The IM's model researches with its own tools (the brief's `.md` links first) and drafts 1.4, 1.5 and
   the track's Technical Considerations and Integration Design as structured JSON with the links it used.
3. The skill copies the proposal master into `SolutionProposals`, reads the copy and derives a compact
   **outline** (one item per structural element: indexes, text, style; tables with rows and cells). The
   document itself is too big to pass through Claude, so this is the one place a skill derives data;
   the server checks that every index lines up the way the Docs API lays a document out, and refuses
   the plan otherwise.
4. `im_proposal_plan`: the server checks the draft (known sections, lengths, every link an asset node or
   a page under the docs host), fills the documentation list from the brief up to `max_links`, picks the
   diagram, and returns one Docs `batchUpdate`: edits that use indexes are computed from the outline and
   ordered from the end of the document backwards, `replaceAllText` runs last. The Features table's one
   empty row is reused and further rows inserted below it, their cells filled by computed indexes.
5. The skill sends the batch unchanged and calls `im_proposal_record`, which records the run and a
   `source` row of type proposal pointing at the document, for ingestion later.

Tracks and blocks: the block whose level-2 heading carries `{{Track}}` is the template; any other block in
sections 2 and 3 (the master's project-level "2.1 Project Scope" block) is removed whole, keeping the
newline before the next section's table because the Docs API won't delete it. Track 1 fills the template
in place, with its headings renumbered to 2.1 and 3.1 and named after the track. Each further track gets
a block rebuilt from the template by index (`BlockWriter`: headings, paragraphs, tables, the image, the
links, written forwards from the empty paragraph that ends the template block), numbered 2.2, 3.2 and so
on. With one track the headings read "Project".

## 5. Code map

| Path | What's there |
|---|---|
| `src/imcp/mcp_server.py` | The MCP tools. Thin: arguments, local files, HTTP calls |
| `src/imcp/config.py` | Settings from environment variables (`AppSettings`, `McpSettings`) |
| `src/imcp/llm.py` | The model client (OpenAI-compatible chat completions) and the embedding client (`/embeddings`, batches of 100) |
| `src/imcp/app/main.py` | The FastAPI app: routers, `/health`, the job store |
| `src/imcp/app/*_api.py` | HTTP endpoints, one router per command. No logic beyond calling `scope/` |
| `src/imcp/app/jobs.py` | Jobs for slow work, kept in memory |
| `src/imcp/bank/` | Parsing and loading the master bank CSV (dry run, apply, history); `draft.py` asks our model for a `purpose` and `baseline` per question and prints a CSV for the owner (`python -m imcp.bank.draft` in the app container) |
| `src/imcp/graph/docs_index.py` | Pure: parses the Adyen docs index (`llms.txt`) and the rules CSV (`data/graph/adyen-doc-pages.csv`, longest prefix wins) into the pages to load, with tags |
| `src/imcp/graph/assets.py` | Loads asset nodes (doc pages now, diagrams next): dry run or apply, embeds new and changed, deprecates what dropped out, records an `ingestion_run` |
| `src/imcp/graph/load_docs.py` | One doc page load: fetch the index from `DOCS_INDEX_URL`, apply the rules, load. The index is never stored |
| `src/imcp/graph/search.py` | `nearest_assets` (one text) and `nearest_assets_for` (one search per requirement, merged, each page saying which requirements found it): tags narrow (an asset with no value for a tag applies to everyone), the embedding ranks |
| `src/imcp/graph/diagrams.py` | The owner's flow diagrams CSV (title, url, description, tags) as `flow_diagram` asset nodes |
| `src/imcp/app/graph_api.py` | `POST /graph/loads/docs` and `/graph/loads/diagrams` as jobs, `GET /graph/jobs/{id}` |
| `src/imcp/proposal/answers.py` | Pure: which answers of a track go into the proposal, the Features table rows (tick, box or text) |
| `src/imcp/proposal/brief.py` | The research brief: requirements, `nearest_assets` for doc pages and diagrams, known designs, instructions |
| `src/imcp/proposal/outline.py` | The document outline the skill passes, and the checks that its indexes line up |
| `src/imcp/proposal/draft.py` | Checking the IM's model's draft: sections, lengths, links against asset nodes or the docs host |
| `src/imcp/proposal/doc_plan.py` | Pure: the Docs batch that fills a copy of the master (tokens, the Discovery and Features tables, diagram, links), one block per track: the `{{Track}}` block is the template, other blocks are removed, further tracks are written from the template by index. A two-column table in the master (header row + one empty body row) is filled by reusing the empty row and inserting the rest below it |
| `src/imcp/proposal/runs.py` | `/ops-create-solution` start, plan and record |
| `src/imcp/app/proposal_api.py` | `POST /proposal/runs`, `/proposal/runs/{id}/doc-plan`, `/proposal/runs/{id}/record` |
| `src/imcp/db/` | Tables (`models.py`), enums and the session helpers. Migrations are in `migrations/` |
| `src/imcp/scope/candidates.py` | The tag query and the baseline questions (in every scope, within the IM's priorities and sections) |
| `src/imcp/scope/topics.py` | Topic matching with our model; each question line carries the bank's `purpose` |
| `src/imcp/scope/runs.py` | `/ops-create-scope` start, plan and record, per track |
| `src/imcp/scope/sheet_plan.py` | The `/ops-create-scope` Sheets batch: a tab per track, deletions, order, sections, groups, filter |
| `src/imcp/scope/extract.py` | Answer extraction with our model (each question line carries its `purpose` and, when the sheet already answers it, the current answer, which the model confirms with `same`), and checking and scrubbing what it returns |
| `src/imcp/scope/answers.py` | `/ops-answer-scope` start and record: the transcript flag, material already used on the tab (by hash), the dated `source`, the Scope log |
| `src/imcp/scope/answers_plan.py` | The `/ops-answer-scope` Sheets batch: the merge rules over meetings (`suggested`, `confirmed`, `conflict`) and the Scope log tab (`appendCells`, so no row arithmetic) |
| `src/imcp/scope/additions.py` | The Suggested additions section, shared by both commands |
| `src/imcp/scope/queue.py` | The review queue for new questions, and reading back what the IM did |
| `src/imcp/scope/call_prompt.py` | The call-notes prompt |
| `src/imcp/pii.py` | The scrub shared by the scope commands and the graph loaders: emails, phones, IBANs, Luhn-valid card numbers, keys; the merchant's name |
| `src/imcp/scope/text.py` | Text helpers: trimming, comparing questions (the scrub is re-exported from `pii.py`) |
| `skills/` | The commands, as skills |
| `evals/` | Fictional cases with known right answers and the runner that scores our model against them through the app server |
| `tests/` | Tests. `tests/db/` need the Postgres test database. `fakes.py` has `FakeModel` and `FakeEmbedder`; `fake_doc.py` plays a Docs batch on an index model, like `FakeTab` for Sheets |

## 6. Data

| Table | Holds |
|---|---|
| `question`, `question_history`, `bank_load_run` | The loaded master bank (with `purpose` and `baseline` since migration 0006), earlier versions of each question, and each load |
| `merchant`, `opportunity` | One deal per scope sheet (the sheet's ID is the opportunity's alias) |
| `generation` | One row per command run, with its trace and stage (draft, planned, recorded) |
| `source`, `instance`, `ingestion_run` | The review queue: a pointer to where a new question came from (never the material), the question and its review state |
| `node`, `edge`, `asset`, `asset_check`, `instance_link` | The proposals graph. Asset nodes (type `asset`, canonical key = URL) are loaded by `im_graph_load_docs`; `node.embedding` takes any size (migration 0005) and `embedding_model` says which model made it. Edges and the other node types are filled by ingestion, next |

## 7. Adding to it

- **A new command** follows the pattern above: logic in `src/imcp/scope/<command>.py` (and a
  `*_plan.py` if it edits a sheet), a router in `src/imcp/app/`, thin tools in `mcp_server.py`, a skill
  in `skills/<command>/SKILL.md`, and tests.
- **A schema change** is a new Alembic migration in `migrations/versions/`, never an edit to an old one.
- **A new bank column** is read by its header in `bank/parse.py`, stored by `bank/load.py` (add it to
  `CONTENT_FIELDS` so a change shows in the dry run and the history), a migration, and the owner adds
  it to the master. `bank/draft.py` is the pattern for a column our model drafts for the owner's review.
- **A flag** is a `FLAG_*` setting in `config.py`, listed in `describe_config` so `im_health` shows it,
  and documented in `.env.example` by the owner. Check it where the work starts, never deeper.
- **Text our model wrote** that goes back to the chat, a sheet or the graph passes through `imcp.pii`
  first; names have no shape, so the prompts tell the model to leave them out.
- **Tests:** `tests/test_sheet_plan.py` has `FakeTab`, which plays a Sheets batch on a grid so plans can
  be checked without Google. `tests/fakes.py` has `FakeModel`. Tests never call the real model.
- **Skills and docs** are written in plain English: short sentences, everyday words, no jargon the IM
  wouldn't use.
