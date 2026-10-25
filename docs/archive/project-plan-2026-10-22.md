# Implementation MCP — Project Plan (v0.2, 2026-10-22 evening)

MVP target: **Monday 2026-10-26**. Nothing is built yet; this plan is for review before execution.

## 1. Scope for Monday

**In:** CheckoutProposal: `/create-scope`, `/source-scope-answers`, `/propose-solution`, a feedback step at the end of each command, the shared data service (Postgres in Docker), and **ingestion of the two reference proposals into the graph** (so we can show the tool improving as proposals are added).

**Out (decided 2026-10-22):** CheckoutLab and IM Researcher. They get design docs after Monday.
**Placeholders only:** CheckoutInvestigate, Local Main.
**To confirm:** CheckoutPost (skills over an existing Postman MCP): assumed out of Monday unless you say otherwise.
**Nice to have:** `/create-adyen-diagrams`.

## 2. Workstreams

| Workstream | Owner | Output | Depends on |
|---|---|---|---|
| A. Question bank cleanup | The owner's agents | Cleaned master bank (one question per row, fixed tag values, `question_id` column, typos fixed, change log) | — |
| B. Seed data | The owner's agents + review | Reviewed seed sheet; gaps filled (PAYFAC, CAPITAL, CASHOUT, diagrams, client-side options); answered question banks for the two reference proposals if they exist | `question_id` from A for tab 8 |
| C. Build | Claude | The IM MCP, Postgres service, ingestion, tests, evals | Contracts below |
| D. Design | The owner + Claude | Remaining decisions (section 5) | — |

## 3. Contracts

1. **Master question bank** (env var `QUESTION_BANK_MASTER_URL`): `question_id, question, priority, subsection, channels, pillars, category, platform`; comma-separated multi-values; blank = applies to everyone; fixed allowed values; loader validates and reports, never guesses.
2. **Seed sheet** (`SEED_SHEET_URL`): tab and column names as in the sheet; only `status = approved` is authoritative (drafts loadable only via a test flag).
3. **Master proposal doc** (`PROPOSAL_MASTER_URL`): the template lives in a tab of the doc. Filling rules (decided): **2.1.1 Discovery:** all bank questions with subsection = Discovery, each in the template's "question / Insert response" format. **2.1.2 Features & Functionality:** all questions with subsection = Features & Functionality, placed in the template table (scope = question, finding = answer). Same pattern for track sections. Solution sections are filled from the recommendation.
4. **AI-assisted answers sheet** (decided): same columns as the question bank, in the same order (`Question, Answer, priority, subsection, channels, pillars, category, platform`), so it reads the same. Proposed: provenance columns appended to the right (`question_id, source, status, confidence, note`) so the left side stays identical. To confirm.
5. **Proposal source for ingestion** (`PROPOSALS_SOURCE`): a local directory (for testing) or the Drive folder (live). Format of the local files to be confirmed. Only completed, shared proposals (naming convention) are ingested.
6. Agents A and B don't rename tabs or columns without updating this contract first.

## 4. Build order (vertical slices)

| Slice | Content | Notes |
|---|---|---|
| 1 | Project setup, config and feature flags, bank loader + validator, deterministic tag filter, tests | No Docker, no external access |
| 2 | Postgres in Docker (compose file, schema): question tables, seed tables, graph tables, trace and feedback tables; MCP tools to query | The owner runs `docker compose up`; auth deferred to v2 |
| 3 | `/create-scope` | Needs Sheets and Drive connectors; creates a Sheet in `SolutionProposals` and shares the link |
| 4 | `/source-scope-answers` | Pasted briefs and transcripts; flags for sanitization and the Gong path |
| 5 | `/propose-solution` | Fills a copy of the master per the rules above; curated recommendation first |
| 6 | **Ingestion of the two reference proposals into the graph** (derived edges, provenance, review queue) | The core v1 demo: ingest one, generate for the other's inputs, compare; ingest both, regenerate; later add a third |
| 7 | Feedback step on each command, recommendation trace | Survey fields still open |
| 8 | Evals, using leave-one-out on the two references | Scoring still open |
| 9 | `/create-adyen-diagrams` | Nice to have |

## 5. Design still open

**Update 2026-10-23:** design is now focused on the system behind `/create-scope` (app server, question bank store, proposals graph, jobs, entities, the "golden zone" goal). See `docs/design/system-design.md`. Other items below wait until the system and schemas are agreed.

**Order the owner set (2026-10-22):** (1) feedback fields and service, drafted in design 4.21; (2) evals, drafted in 4.22, and the knowledge graph primer (`docs/design/knowledge-graph-primer.md`); (3) privacy path for pasted transcripts: v2; (4) master doc details, with the proposal URL and source as environment variables so we can test on a local directory first; (5) which questions go to project vs track sections.

**Build/ingest order (proposal):** keep the slice order (commands first on the curated path, ingestion after), but **spike ingestion on one proposal early (Friday, right after the database exists)** to de-risk extraction quality, since ingestion is the centerpiece of the demo and the riskiest part. Ingestion needs the bank and seed loaded (to resolve mentions to canonical nodes), but it doesn't need the commands.

1. **Feedback survey:** which questions we ask in the Form and 1–10 step, and which fields we record automatically (command, proposal ID, tool version, flags, trace ID).
2. **Evals:** golden cases and scoring per command.
3. **Privacy path** for pasted transcripts and sanitization: what is obfuscated, when, and the review needed.
4. **Master doc filling details:** which questions go to project vs track sections; whether unanswered questions are shown or omitted; ordering (by priority?); how EN/CN/JP variants are handled.
5. **Ingestion design for v1:** extraction approach, the review queue, and the answered banks for the two references (do they exist?).
6. **Recommendation flag behaviour:** curated / graph / both, and how results are compared.

## 6. Schedule (proposed)

| When | Build | The owner's agents / design |
|---|---|---|
| Thu night | Review plan; no building until approved | Cleanup and seed review start |
| Fri | Slices 1–3 | Cleaned bank with `question_id`; design items 1, 3, 4 |
| Sat | Slices 4–5 | Seed review; design items 2, 5 |
| Sun | Slices 6–7, start 8 | Review drafts |
| Mon | Evals, README and install steps, demo | Approve seed rows |

## 7. Risks

- **Ingestion is the heaviest piece** and was moved into v1. With only two proposals, and both mostly about platforms, the graph will help platform-style deals far more than e-commerce or in-person ones.
- **Connector unknowns:** copying and filling the master doc, creating folders and sharing. Test early (slices 3 and 5).
- **Docker:** you have it; I can't run it from here, so the Postgres service is verified by you running `docker compose up`.
- **Data readiness:** if cleanup or the seed review slips, we build on drafts and quality isn't representative.
- **Privacy:** the Gong-sourcing path stays behind a flag until cleared.
