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
| `/create-scope` | Picks the scoping questions for one merchant from the master question bank (by tags, plus our model matching the IM's notes) and builds a scope sheet in the IM's Drive, one tab per project track | Built |
| `/source-scope-answers` | Finds the answers in whatever the IM has from the merchant (notes, a call summary, a transcript, an email) and writes them into a track's tab of the scope sheet for the IM to review | Built |
| `/propose-solution` | Writes the solution proposal from the scope: the merchant's answers, a research brief from the knowledge graph, the IM's model's researched solution, a diagram and documentation links, into a copy of the proposal master | Built for one track; not yet run on a real document |

Each command is a **skill** (`skills/<name>/SKILL.md`): plain instructions Claude follows, calling our
tools and the IM's Google connectors.

## 2. The pieces

```
 IM's Claude (desktop)
   │  skills: /create-scope, /source-scope-answers
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
   that repeat a bank question are dropped.
5. **Privacy by default.** Merchant material and the answers found are never stored or logged. A run's
   trace keeps question IDs, counts and hashes. The IM's notes are sent to the model but never stored.
   The review queue gets only the generic wording of new questions, behind `FLAG_CANDIDATE_QUEUE` and
   the IM's consent.
6. **The master bank belongs to people.** Only a person edits it. It is loaded from a CSV download with
   a dry run first. Question IDs are permanent: never reused, never renumbered. Questions are
   deactivated, not deleted.
7. **The IM owns their sheet.** We only add: fill empty answers, add review columns, add rows at the
   end. We never overwrite the IM's answers; a different finding goes in a note. The IM reviews in the
   sheet, and the next run reads what they changed.
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
`/create-scope`, and each gets its own tags and its own tab in the scope sheet, titled with the track's
name. The default is one track, whose tab keeps the master's name, Project Scope. The two Introduction
questions and the Suggested additions go in the first tab only: there is one introduction per proposal.
The tracks and their tags are kept on the `opportunity` (`tracks`); the tab title is the track name
everywhere else. `/source-scope-answers` fills one tab per run; `/propose-solution` will write one
block of sections per track.

### /create-scope

1. The skill asks the IM for the merchant, the tracks (one short message; "one" is the usual answer),
   tags (one question card per track) and notes.
2. `im_scope_start` (a job: `im_scope_wait` until it's done): per track, the server selects questions
   by tags; our model adds questions for topics in the notes, told which track it is choosing for, and
   drafts a question for each topic the bank doesn't cover (once, for the project). A draft run is saved.
3. The skill copies the master bank into the IM's `SolutionProposals` folder and reads column A, the
   header row, the filter and every tab's sheetId.
4. `im_scope_sheet_plan`: the server returns one batch that renames Project Scope to the first track,
   duplicates it once per further track (before any row is touched, so each tab starts from the same
   rows), and in each tab deletes the rows not in that track, adds `found_by`, orders and groups the
   rows by section, adds **Suggested additions** at the end of the first tab, and keeps the master's filter.
5. The skill sends the batch, reads column A of every track tab back, asks consent if there are new
   questions, and calls `im_scope_record`: the read-back check per tab, the deal with its tracks, the
   review queue and a call-notes prompt grouped by track.

### /source-scope-answers

1. The skill gets the scope sheet, which track tabs the material covers (asked only when there are
   several) and the merchant material. Then, tab by tab, it reads the tab's ID, answer and review columns.
2. `im_answers_start` (a job: `im_answers_wait` until it's done), with the tab's title: our model
   answers that tab's questions and lists new ones; the server checks them and returns one batch that
   fills empty answers, adds `source`, `confidence`, `status` and `ai_note` columns, and adds Suggested
   additions to that tab.
3. The skill sends the batch, reads column A back, asks consent, and calls `im_answers_record`.

### /propose-solution

The one command where the IM's own model writes: the server makes no chat model call here.

1. The skill reads the track tab's ID, answer, status, source and question columns and calls
   `im_proposal_start`. The server picks the answers (the IM's own win, `suggested` ones are used but
   flagged, `rejected` are skipped), lists the open priority-1 questions, and builds the **research
   brief** from the graph: the requirements, the nearest doc pages and diagrams (`nearest_assets`,
   narrowed by the track's tags from `opportunity.tracks`), the designs the graph knows, and instructions.
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

One track per document for now. The master may carry a second block for a further track (a level-2
heading with `{{Track}}`); with one track the plan removes it whole, keeping the newline before the next
section's table because the Docs API won't delete it. Duplicating that block per further track is next.

## 5. Code map

| Path | What's there |
|---|---|
| `src/imcp/mcp_server.py` | The MCP tools. Thin: arguments, local files, HTTP calls |
| `src/imcp/config.py` | Settings from environment variables (`AppSettings`, `McpSettings`) |
| `src/imcp/llm.py` | The model client (OpenAI-compatible chat completions) and the embedding client (`/embeddings`, batches of 100) |
| `src/imcp/app/main.py` | The FastAPI app: routers, `/health`, the job store |
| `src/imcp/app/*_api.py` | HTTP endpoints, one router per command. No logic beyond calling `scope/` |
| `src/imcp/app/jobs.py` | Jobs for slow work, kept in memory |
| `src/imcp/bank/` | Parsing and loading the master bank CSV (dry run, apply, history) |
| `src/imcp/graph/docs_index.py` | Pure: parses the Adyen docs index (`llms.txt`) and the rules CSV (`data/graph/adyen-doc-pages.csv`, longest prefix wins) into the pages to load, with tags |
| `src/imcp/graph/assets.py` | Loads asset nodes (doc pages now, diagrams next): dry run or apply, embeds new and changed, deprecates what dropped out, records an `ingestion_run` |
| `src/imcp/graph/load_docs.py` | One doc page load: fetch the index from `DOCS_INDEX_URL`, apply the rules, load. The index is never stored |
| `src/imcp/graph/search.py` | `nearest_assets`: tags narrow (an asset with no value for a tag applies to everyone), the embedding ranks |
| `src/imcp/graph/diagrams.py` | The owner's flow diagrams CSV (title, url, description, tags) as `flow_diagram` asset nodes |
| `src/imcp/app/graph_api.py` | `POST /graph/loads/docs` and `/graph/loads/diagrams` as jobs, `GET /graph/jobs/{id}` |
| `src/imcp/proposal/answers.py` | Pure: which answers of a track go into the proposal, the Features table rows (tick, box or text) |
| `src/imcp/proposal/brief.py` | The research brief: requirements, `nearest_assets` for doc pages and diagrams, known designs, instructions |
| `src/imcp/proposal/outline.py` | The document outline the skill passes, and the checks that its indexes line up |
| `src/imcp/proposal/draft.py` | Checking the IM's model's draft: sections, lengths, links against asset nodes or the docs host |
| `src/imcp/proposal/doc_plan.py` | Pure: the Docs batch that fills a copy of the master (tokens, Discovery, Features table, diagram, links) |
| `src/imcp/proposal/runs.py` | `/propose-solution` start, plan and record |
| `src/imcp/app/proposal_api.py` | `POST /proposal/runs`, `/proposal/runs/{id}/doc-plan`, `/proposal/runs/{id}/record` |
| `src/imcp/db/` | Tables (`models.py`), enums and the session helpers. Migrations are in `migrations/` |
| `src/imcp/scope/candidates.py` | The tag query |
| `src/imcp/scope/topics.py` | Topic matching with our model |
| `src/imcp/scope/runs.py` | `/create-scope` start, plan and record, per track |
| `src/imcp/scope/sheet_plan.py` | The `/create-scope` Sheets batch: a tab per track, deletions, order, sections, groups, filter |
| `src/imcp/scope/extract.py` | Answer extraction with our model, and checking what it returns |
| `src/imcp/scope/answers.py` | `/source-scope-answers` start and record |
| `src/imcp/scope/answers_plan.py` | The `/source-scope-answers` Sheets batch |
| `src/imcp/scope/additions.py` | The Suggested additions section, shared by both commands |
| `src/imcp/scope/queue.py` | The review queue for new questions, and reading back what the IM did |
| `src/imcp/scope/call_prompt.py` | The call-notes prompt |
| `src/imcp/scope/text.py` | Text helpers: trimming, scrubbing, comparing questions |
| `skills/` | The commands, as skills |
| `tests/` | Tests. `tests/db/` need the Postgres test database. `fakes.py` has `FakeModel` and `FakeEmbedder`; `fake_doc.py` plays a Docs batch on an index model, like `FakeTab` for Sheets |

## 6. Data

| Table | Holds |
|---|---|
| `question`, `question_history`, `bank_load_run` | The loaded master bank, earlier versions of each question, and each load |
| `merchant`, `opportunity` | One deal per scope sheet (the sheet's ID is the opportunity's alias) |
| `generation` | One row per command run, with its trace and stage (draft, planned, recorded) |
| `source`, `instance`, `ingestion_run` | The review queue: a pointer to where a new question came from (never the material), the question and its review state |
| `node`, `edge`, `asset`, `asset_check`, `instance_link` | The proposals graph. Asset nodes (type `asset`, canonical key = URL) are loaded by `im_graph_load_docs`; `node.embedding` takes any size (migration 0005) and `embedding_model` says which model made it. Edges and the other node types are filled by ingestion, next |

## 7. Adding to it

- **A new command** follows the pattern above: logic in `src/imcp/scope/<command>.py` (and a
  `*_plan.py` if it edits a sheet), a router in `src/imcp/app/`, thin tools in `mcp_server.py`, a skill
  in `skills/<command>/SKILL.md`, and tests.
- **A schema change** is a new Alembic migration in `migrations/versions/`, never an edit to an old one.
- **Tests:** `tests/test_sheet_plan.py` has `FakeTab`, which plays a Sheets batch on a grid so plans can
  be checked without Google. `tests/fakes.py` has `FakeModel`. Tests never call the real model.
- **Skills and docs** are written in plain English: short sentences, everyday words, no jargon the IM
  wouldn't use.
