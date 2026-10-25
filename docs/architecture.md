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
| `/create-scope` | Picks the scoping questions for one merchant from the master question bank (by tags, plus our model matching the IM's notes) and builds a scope sheet in the IM's Drive | Built |
| `/source-scope-answers` | Finds the answers in whatever the IM has from the merchant (notes, a call summary, a transcript, an email) and writes them into the scope sheet for the IM to review | Built |
| `/propose-solution` | Writes the solution proposal from the scope | Next |

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
   └── Our model                                   any OpenAI-compatible chat API
```

- **Claude** holds the conversation, asks the IM for input, and moves data between our tools and
  Google. It never decides which rows to keep or where to write them.
- **The IM MCP server** is thin: it checks arguments, reads files from two local folders (`data/` for
  bank CSVs, `inputs/` for long merchant material) and forwards everything to the app server.
- **The app server** does the work: queries, our model calls, validation, and building the exact
  Sheets edits. It has no Google credentials.
- **Postgres** stores the question bank, every run (`generation`), the review queue and, later, the
  proposals graph.

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

## 4. How a command works

Each command follows the same shape: **start → (plan) → write → record**.

### /create-scope

1. The skill asks the IM for the merchant, tags (one question card) and notes.
2. `im_scope_start`: the server selects questions by tags; our model adds questions for topics in the
   notes and drafts a question for each topic the bank doesn't cover. A draft run is saved.
3. The skill copies the master bank into the IM's `SolutionProposals` folder and reads column A, the
   header row and the filter.
4. `im_scope_sheet_plan`: the server returns one batch that deletes the rows not in scope, adds
   `found_by`, orders and groups the rows by section, adds **Suggested additions** at the end, and keeps
   the master's filter.
5. The skill sends the batch, reads column A back, asks consent if there are new questions, and calls
   `im_scope_record`: the read-back check, the deal, the review queue and a call-notes prompt.

### /source-scope-answers

1. The skill gets the scope sheet and the merchant material, and reads the sheet's ID, answer and
   review columns.
2. `im_answers_start` (a job: `im_answers_wait` until it's done): our model answers the sheet's
   questions and lists new ones; the server checks them and returns one batch that fills empty answers,
   adds `source`, `confidence`, `status` and `ai_note` columns, and adds Suggested additions.
3. The skill sends the batch, reads column A back, asks consent, and calls `im_answers_record`.

## 5. Code map

| Path | What's there |
|---|---|
| `src/imcp/mcp_server.py` | The MCP tools. Thin: arguments, local files, HTTP calls |
| `src/imcp/config.py` | Settings from environment variables (`AppSettings`, `McpSettings`) |
| `src/imcp/llm.py` | The model client (OpenAI-compatible chat completions) |
| `src/imcp/app/main.py` | The FastAPI app: routers, `/health`, the job store |
| `src/imcp/app/*_api.py` | HTTP endpoints, one router per command. No logic beyond calling `scope/` |
| `src/imcp/app/jobs.py` | Jobs for slow work, kept in memory |
| `src/imcp/bank/` | Parsing and loading the master bank CSV (dry run, apply, history) |
| `src/imcp/db/` | Tables (`models.py`), enums and the session helpers. Migrations are in `migrations/` |
| `src/imcp/scope/candidates.py` | The tag query |
| `src/imcp/scope/topics.py` | Topic matching with our model |
| `src/imcp/scope/runs.py` | `/create-scope` start, plan and record |
| `src/imcp/scope/sheet_plan.py` | The `/create-scope` Sheets batch: deletions, order, sections, groups, filter |
| `src/imcp/scope/extract.py` | Answer extraction with our model, and checking what it returns |
| `src/imcp/scope/answers.py` | `/source-scope-answers` start and record |
| `src/imcp/scope/answers_plan.py` | The `/source-scope-answers` Sheets batch |
| `src/imcp/scope/additions.py` | The Suggested additions section, shared by both commands |
| `src/imcp/scope/queue.py` | The review queue for new questions, and reading back what the IM did |
| `src/imcp/scope/call_prompt.py` | The call-notes prompt |
| `src/imcp/scope/text.py` | Text helpers: trimming, scrubbing, comparing questions |
| `skills/` | The commands, as skills |
| `tests/` | Tests. `tests/db/` need the Postgres test database |

## 6. Data

| Table | Holds |
|---|---|
| `question`, `question_history`, `bank_load_run` | The loaded master bank, earlier versions of each question, and each load |
| `merchant`, `opportunity` | One deal per scope sheet (the sheet's ID is the opportunity's alias) |
| `generation` | One row per command run, with its trace and stage (draft, planned, recorded) |
| `source`, `instance`, `ingestion_run` | The review queue: a pointer to where a new question came from (never the material), the question and its review state |
| `node`, `edge`, `asset`, `asset_check`, `instance_link` | The proposals graph (schema ready, not filled yet) |

## 7. Adding to it

- **A new command** follows the pattern above: logic in `src/imcp/scope/<command>.py` (and a
  `*_plan.py` if it edits a sheet), a router in `src/imcp/app/`, thin tools in `mcp_server.py`, a skill
  in `skills/<command>/SKILL.md`, and tests.
- **A schema change** is a new Alembic migration in `migrations/versions/`, never an edit to an old one.
- **Tests:** `tests/test_sheet_plan.py` has `FakeTab`, which plays a Sheets batch on a grid so plans can
  be checked without Google. `tests/fakes.py` has `FakeModel`. Tests never call the real model.
- **Skills and docs** are written in plain English: short sentences, everyday words, no jargon the IM
  wouldn't use.
