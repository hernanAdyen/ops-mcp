# Project plan

Status and what comes next. Updated 2026-10-25. How it's built is in [architecture.md](architecture.md).
The earlier plan (2026-10-22) is in [archive/](archive/).

## Goal

MVP for Monday 2026-10-26: the CheckoutProposal commands `/create-scope`, `/source-scope-answers` and
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

## Next

1. **`/propose-solution`.** Design below, to review before building.
2. **Ingest the two reference proposals into the graph**, so we can show the tool improving as
   proposals are added.
3. **Evals:** leave-one-out on the reference proposals; extraction checked against answered banks.

## /propose-solution design (draft, to review)

Writes the solution proposal for one merchant from their scope sheet. Same shape as the other
commands: **start → (plan) → write → record**. Status: not built. Review these steps, then build.

### What the IM does

1. Runs `/propose-solution` (the scope sheet from the chat by default, or a link), and can add
   context ("they go live in March", "keep the plugin section short").
2. Answers at most one question card if there are conflicts to settle (see step 3 below).
3. Gets a link to the proposal doc in `SolutionProposals`, a short note on what's missing, and the
   feedback link.

### How it works

1. **Read the scope.** The skill reads the Project Scope tab (ID, answer and review columns only)
   and sends it to `im_proposal_start`.
2. **Pick the answers to use (server).**
   - An IM's own answer (no `source`, or `status` = confirmed) wins.
   - `suggested` answers are used but marked in the trace, and listed for the IM to check.
   - `rejected` answers are skipped.
   - An `ai_note` with a different answer is a **conflict**: the server lists them and the skill asks
     the IM which to use before anything is written.
3. **Coverage note, not a gate.** Open priority-1 questions are listed in the reply ("12 of 40
   P1 questions are still open"). The proposal is still written; open items say "To confirm".
4. **Recommend the solution (server, curated first).** Rules from the seed sheet
   ("IM MCP - Integration Design Seed") map tags and answers to integration designs, and each design
   to its technical considerations, documentation links and flow diagrams. `FLAG_RECOMMENDER=curated`
   uses only the seed; `graph` and `both` come later. **Documentation links come only from the seed,
   never from the model.**
5. **Draft the prose (our model, a job).** Our model writes the Introduction (from ID-0083 and
   ID-0084), and short text for each recommended section, from the chosen answers and the
   recommendation. Checked like extraction: only known section keys, no links that aren't in the
   seed, length limits.
6. **Make the doc (skill).** Copy `PROPOSAL_MASTER_URL` into `SolutionProposals`, named
   "<Merchant> - Solution Proposal".
7. **Fill the doc (server plans, skill sends).** The server returns an exact Docs `batchUpdate`,
   relayed unchanged (design rule 1):
   - Text sections: `replaceAllText` on placeholder tokens in the master (e.g. `{{introduction}}`).
   - 2.1.1 Discovery: question / response pairs, in scope-sheet order.
   - 2.1.2 Features & Functionality: a table, filled row by row.
   - Solution sections: technical considerations, integration design, flow diagrams, documentation.
8. **Record.** `im_proposal_record` reads back that no `{{` tokens are left, saves the generation
   with a recommendation trace (which rules fired, which answers were used, by ID; never the text),
   and returns the feedback link.

### Code (same pattern as the other commands)

| Path | What |
|---|---|
| `src/imcp/proposal/seed.py` | Loads the seed sheet CSV (from `data/`, dry run first, like the bank) |
| `src/imcp/proposal/recommend.py` | Curated rules: tags and answers → designs → considerations, docs, diagrams |
| `src/imcp/proposal/answers.py` | Picks the answers to use, finds conflicts and open P1s |
| `src/imcp/proposal/draft.py` | Our model's prose, and checking it |
| `src/imcp/proposal/doc_plan.py` | The Docs batch (pure function) |
| `src/imcp/proposal/runs.py` | start, plan, record |
| `src/imcp/app/proposal_api.py`, tools in `mcp_server.py` | Router and thin tools |
| `skills/propose-solution/SKILL.md` | The command |
| `tests/` | `FakeDoc` (plays a Docs batch on a text model, like `FakeTab`), rule tests, answer-picking tests |

A migration adds the seed tables (rule, design, consideration, doc link) if we keep the seed in
Postgres; otherwise it's loaded per run from the CSV.

### Open questions (decide before building)

1. **Placeholders:** add `{{tokens}}` to the master proposal (simplest and most reliable), or find
   sections by heading text? Recommended: tokens, added by a person to a copy first.
2. **The seed loader:** keep the seed in Postgres (versioned like the bank) or read the CSV each run?
3. **Project vs. track sections:** one proposal per merchant, or a section per track (e.g. online,
   in-person)?
4. **Unanswered questions** in 2.1.1: show them as "To confirm", or leave them out?
5. **Diagrams:** link to existing diagram files from the seed for now; generating them is
   `/create-adyen-diagrams` later.
6. **Long docs and the 60s bridge:** the draft is a job; the Docs batch may need splitting if it gets
   big.

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
