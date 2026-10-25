# System Design — Implementation MCP (draft v0.1, 2026-10-23)

Scope: the system behind `/create-scope` first. Other commands reuse it later. Nothing here is built.

## 1. Architecture (as described by the owner)

```
 IM's AI client (Claude + skills)
   │                              │
   │ MCP                          │ connectors (Drive, Sheets, Docs, later Gong)
   ▼                              ▼
 MCP server  ──HTTP──▶  App server  ──▶  Data sources
                          │                ├─ Question bank store (hosted, normalized)
                          │                └─ Proposals graph (hosted)
                          └─ Jobs: refresh question bank · ingest proposals + their answered banks ·
                                   apply feedback · check doc links · process candidate questions
```

Local Docker with Postgres for v1; hosted later; authentication in v2.

**Data sources:** (1) a hosted **question bank** we maintain, refreshed from the master; (2) a hosted **proposals graph** built from ingested completed proposals and their question banks. Gong briefs and transcripts are **not stored**: they stay in memory and the chat to build the proposal.

## 2. Two consequences to settle

1. **The app server's jobs can't use the AI client's connectors.** Connectors (Drive, Sheets) belong to the client session. For the server to refresh the bank or ingest proposals on a schedule, it needs its **own access** to those sources (e.g. a Google service account or OAuth credentials), or a v1 shortcut: a local directory / exported files (matches the "test on a local directory first" plan), or the client pushes data to the server.
2. **Where the MCP server lives.** Either a thin local MCP server that calls the app server over HTTP, or the app server itself exposes MCP. For v1 both run in local Docker, so this only needs deciding before we write the tool layer.

## 3. Gong data: process without storing

The skill reads the brief or transcript in the chat and builds the answers. It may also extract **candidate questions** worth keeping (e.g. a good question the IM asked that isn't in the bank). Only the candidate question text and minimal metadata (tags, a pointer to the source call, no transcript) is sent to a **review queue** on the server. A human reviews before anything updates the bank or graph. Needs privacy sign-off for what metadata is kept. Deferred privacy path: v2.

## 4. Entities (first pass, to react to — not a schema yet)

**Question bank side**
- **Question:** id, text, type (toggle / free text / choice), priority, subsection, status, version.
- **Tag dimensions:** channel, pillar, category, platform (many-to-many with Question; blank = applies to all).
- **Question relationship:** a dependency between questions with a condition (e.g. "ask B only if A = yes", "A implies B", "A and B are often asked together"). Where this lives (bank or graph) is open.
- **Decision (new idea):** the real choice a question elicits ("online payments channel?", "offload PCI to Adyen?", "multiple payment methods on one integration?"). A question helps settle one or more decisions; decisions have options; options point to designs and effort.
- **Bank version / change log.**

**Proposal graph side**
- **Proposal** (completed, shared), **Track**, **Merchant** (pseudonymous), **Answer** (proposal + question + value + evidence).
- **Integration design**, **Consideration**, **Doc link**, **Diagram**, **Rule** (conditions → design).
- Edges carry confidence, evidence counts, status and provenance (see the knowledge graph primer).

**Operational**
- **Generation** (one command run), **Recommendation trace**, **Feedback event**, **Candidate question** and **Review queue item**, **Ingestion run**, **Source document** (file reference + hash), **Seed snapshot**.

## 5. The goal: the "golden zone" of questions

The owner's definition: the **minimal set of questions to ask that leaves the least scope creep once the integration is implemented.** Too few questions → scope creep; too many → time and fatigue.

**Reframing.** This is an adaptive interview: at each step, choose the question whose answer most reduces uncertainty about the design and effort, given what is already known, and stop when the next question's value is lower than its cost. The example chain is the shape: *online channel? yes → offload PCI to Adyen? yes → multiple payment methods on one integration? yes → Drop-in.* Each answer removes options and unlocks the next question.

**What it needs**
1. **Question-to-question structure:** which questions depend on or imply others, with conditions.
2. **Decisions and their effect:** which answers change the design or effort (this is what makes a question valuable).
3. **A definition of scope creep we can measure.** Today we don't know of outcome data. If post-proposal change requests, scope changes or timeline overruns are recorded somewhere (kickoff to go-live), we could learn which *unasked* questions led to creep. Without it, the first version is expert-defined structure plus proxies (late additions, rework flagged in feedback).

**Stages**
- **A. Structure (rule-based):** dependency and implication edges with conditions, priorities, and "typical next questions" from the decision structure. Works with little data.
- **B. Suggestions from data:** "in similar proposals, when X was asked, Y was asked too" from the graph, to surface related questions the IM didn't know to ask.
- **C. Optimization:** score each remaining question by how much it would change the design/effort and its cost, and recommend a stopping point, calibrated on outcome data once we have it.

## 6. Open questions

1. How is scope creep recorded today, and where (YouTrack, Jira, kickoff notes)? Could we get it for past projects?
2. Do question relationships live in the question bank store (curated), the graph (learned), or both merged at query time?
3. Server access to Google for jobs (service account/OAuth) versus local directory/export for v1.
4. MCP server placement (thin local vs on the app server).
5. Who defines the decision structure for the first version (the owner with SMEs), and how is it captured (a sheet like the seed sheet)?
6. What fields may a candidate question keep from a call?

## 7. Next step (proposed)

Workshop the **entities** above (confirm the list, definitions, and what is a node vs a table), then design the **question bank schema** and the **graph schema** from them, with question relationships and decisions as the key new pieces. Only then update the `/create-scope` flow.
