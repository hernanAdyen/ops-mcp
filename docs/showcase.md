# Showcase: ten minutes, three commands, two merchants

Talking points for a short demo. Everything shown is fictional: made-up merchants, made-up calls.

## The story in one line

An implementation manager scopes a merchant, fills the scope from the call, and gets a first solution
proposal, in Claude, with the team's question bank and documentation graph behind it, and nothing
copied by hand.

## The flow (about seven minutes)

1. **`/ops-create-scope Harbor Coffee`** (one minute). Two tracks, online and in-store. The sheet appears
   in Drive: one tab per track, grouped by section, each question tagged with why it is there (tags,
   baseline, or a topic from the notes), the master's filter kept. Say: the bank is the team's, the
   questions are the ones the tags and the notes call for, nothing is typed.
2. **`/ops-answer-scope`** with the call summary (two minutes). Point at a few filled rows: the answer
   in the question's format, the source with the call's date, a confidence, a note with the evidence.
   Open the **Scope log** tab: one line per change. Say: run it after every call; a later call that
   agrees confirms, one that disagrees marks a conflict for the IM to settle; nothing is overwritten.
3. **`/ops-create-solution`** (three minutes). Open the proposal: Discovery table and Features table per
   track from the sheet, Technical Considerations and Integration Design per track researched from the
   documentation, the flow diagram for the in-store track, documentation links that are real pages from
   the graph. Say: the IM reviews and edits; the first draft took a quarter of an hour, not a day.
4. **CourtSide Bookings** (one minute, if time): the same three commands on a platform with sub-merchants,
   KYC, split payments, weekly payouts and instant cashout. Different bank branch, same flow.

## The points that matter (three minutes)

- **Time.** Scope sheet in a minute; a call's answers in the time it takes to read them; a proposal draft
  in a quarter of an hour. The IM's time goes to judgement and the merchant.
- **One standard.** Every proposal from the same master; every answer tied to a bank question by its
  permanent ID; every link a real documentation page; every run recorded.
- **The scope lives across meetings.** Dated sources, confirmed and conflict states, a Scope log.
- **IM knowledge becomes an asset.** The bank carries what each question is for and which ones every
  project needs. The graph holds the documentation, the approved diagrams and, next, the team's own
  proposals, so a new IM's proposal draws on the designs the experienced ones used. The same graph is
  the base for recommending a design, spotting what a scope misses, seeing which questions decide effort.
- **Private by design.** Material goes to the team's own model for one run and is never stored; what
  comes back is scrubbed; the files stay in the IM's Drive; run records hold IDs and counts only.
- **Measurable.** Extraction is scored against fictional cases with known answers; a prompt or model
  change shows up as a number.

## What to say if asked

- *Does it replace the IM?* No. It does the copying and the first draft; the IM owns the review, the
  conversation and the design decisions. Suggested answers are marked as such until the IM confirms.
- *What about merchant data?* The material is used for one run by the team's model and never stored.
  Transcripts go in as files, never through the chat. There is a switch to refuse transcripts.
- *What does it need?* Docker or a local Postgres, a model key, and the Google connectors in Claude.
  Install is one page in the README.
- *What's next?* Reference proposals into the graph, real diagrams, then the graph starts to recommend.

## Links for the demo (test files in the IM's Drive, 2026-10-27)

- Harbor Coffee scope sheet: https://docs.google.com/spreadsheets/d/17JIHIY-0_nePtiSqqVCokvw4-cvyh8Vf7raIjUdmGDU/edit
- Harbor Coffee proposal: https://docs.google.com/document/d/139qURDRcT2vKG90_-kI-pfxiIklmVRkojTZKRf-5Z1c/edit
- CourtSide Bookings scope sheet: https://docs.google.com/spreadsheets/d/16RbMunxR796lQcKXfy247PkhyDCoicXmF2ukQHAfl_k/edit
- CourtSide Bookings proposal: https://docs.google.com/document/d/1bvrN1MqVHiH4JBENt4MxP6Zl7rzMAgEhY-XkWNi6zqw/edit
- Spare, scope and answers only: Bramble & Bay sheet https://docs.google.com/spreadsheets/d/1CmzSwxPokbgj6t-jTzeB1Tw5Gu4YQoA2mnKO12Qz_Ts/edit
- The call summaries used are in `inputs/` (fictional, git-ignored); the README section "Why it matters" has the business case.

Before the session: in each proposal, click the table of contents and choose update, so it shows the
track names.
