---
name: create-scope
description: Use when an implementation manager runs /create-scope or wants a scoping question sheet for a new merchant. Picks bank questions by tags and context, builds the sheet in Drive, and returns the link with a summary.
---

# /create-scope

Build a prefiltered scoping question sheet for one merchant from the IM question bank, and give the
IM the link and a short summary. The IM reviews and trims the questions in the sheet, not in chat.

**Needs:** the IM MCP (its tools are `im_scope_start`, `im_scope_sheet_plan` and `im_scope_record`;
their full names may carry a prefix, and they may have to be loaded with a tool search first), and the
Google Drive and Google Sheets connectors. If the IM MCP can't reach its app server, tell the IM to
check that `docker compose up` is running, and stop.

## 1. Gather the inputs

Use what the IM already gave (e.g. `/create-scope Acme, PFS + CAPITAL, migrating tokens`) and ask
only for what's missing.

- **Merchant name** (required). If it's missing, ask for it in one short chat message first.
- **Tags.** Ask with one question card (AskUserQuestion), all questions multi-select. Leave out any
  question the IM already answered. Put "All" first in every question.
  - Channels: All, ECOM, IPP, MOTO
  - Pillars: All, DIGITAL, PFS, UC
  - Subsections: All, Introduction, Discovery, Features & Functionality
  - Categories: All, Payments (PAYIN, PAYOUT), Platforms (KYC, PAYFAC, CASHOUT),
    Capital & reporting (CAPITAL, REPORTING_RECONCILIATION). Mention that exact categories can be
    typed in Other.
  - "All", or every option of a question selected, means no filter on that tag: pass an empty list.
    Each category group means all the categories in it.
  - Priorities and platforms aren't asked: don't filter on them, unless the IM gave them in the
    command (e.g. `/create-scope Acme, BALANCE, P1 only`).
  - Pass subsections as `introduction`, `discovery`, `features_functionality`, and priorities as 1, 2, 3.
- **Context.** After the card, unless the IM already gave it, ask in one short chat message for their
  notes on the merchant (e.g. "launching Capital for their sellers, migrating tokens from their current
  PSP"), or "none". A card can't ask this: a question needs at least two options to choose from.
  Pass the IM's own notes. If they paste a long call transcript, don't pass it: summarise the merchant's
  needs in a few sentences, without names or other personal details, and pass that.
- If the question card isn't available, ask for the tags and context in one short message instead.

## 2. Start the run

Call `im_scope_start` with the merchant name, the tags and the context. It returns a `draft_id`, counts
of the tag matches, the questions our model added by topic (each with a reason), topics no bank
question covers, and `master_sheet_url`. If it returns an error, tell the IM in one line and stop.

## 3. Confirm the questions added by topic

The tag matches need no review here. Show the IM, briefly:

- the number of tag matches, by subsection;
- each question added by topic: ID, question and the reason;
- topics from their notes that no bank question covers, each with the question our model drafted for it
  (`gap_questions`, IDs like NEW-0001). These go under **Suggested additions** at the end of the sheet,
  for the IM to review there;
- one line if topic matching was skipped (no context) or unavailable.

If there are additions or drafted questions, ask whether to create the sheet with them, noting that they
can drop any of them (by ID, including NEW- IDs) or add a bank question by ID. Remember what they drop
(`remove_ids`) and add (`add_ids`). If there are neither, go straight on.

## 4. Build the sheet

1. **Folder.** Search Drive for a folder titled `SolutionProposals` in My Drive
   (`title = 'SolutionProposals' and mimeType = 'application/vnd.google-apps.folder' and parentId = 'root'`).
   If there isn't one, create it there.
2. **Name.** `<merchant name> <YYYY-MM-DD HHmm>`, using the current date and time where the IM is.
3. **Copy** the master bank into that folder with that name. Its file ID is the part of
   `master_sheet_url` after `/d/`. Never edit the master itself.
4. **Read the copy's tabs** (fields `sheets.properties` and `sheets.basicFilter`) and note the
   `Project Scope` tab's `sheetId`, `gridProperties.columnCount` and its `basicFilter`, if it has one.
5. **Read column A** of the copy: `'Project Scope'!A:A`. Turn it into one string per row, starting
   with the `id` header, with `''` for an empty row. Also read the **header row**: `'Project Scope'!1:1`.
6. Call **`im_scope_sheet_plan`** with the `draft_id`, that `sheetId`, the column count, column A, the
   header row, the tab's `basicFilter` exactly as read (`basic_filter`; leave it out if there's none),
   and the IM's `remove_ids` and `add_ids`. If it refuses (for example an unknown ID), tell the IM and fix
   that before changing anything.
7. Send the returned **`requests` unchanged, in one Sheets batch update** on the copy. Don't edit,
   reorder, split or recalculate them, and never work out row numbers yourself.
8. **Read column A of the copy again**, the same way.
9. **Consent.** If `im_scope_start` said `review_queue_on` and the sheet has drafted questions (NEW- IDs),
   ask with one question card: "Share the N drafted questions with the question bank owner, so future IMs
   can use them? Only the question wording is shared: no answers, notes or merchant details." Options:
   "Yes, share them" and "No, keep them in my sheet only". Otherwise don't ask.
10. Call **`im_scope_record`** with the `draft_id`, the merchant name, the copy's file ID, its link
   (`https://docs.google.com/spreadsheets/d/<file ID>/edit`), the column A you just read, and
   `share_new_questions` true only if the IM said yes.

## 5. Reply

Keep it short:

- the sheet, as a link on its name;
- the number of questions, by section, and how they were found (tags, topic, added by you); the sheet
  is grouped by section, each with a collapsible group;
- if the plan's `filter` is `kept`: the sheet opens with the master's filter on (e.g. P1 only), and
  the IM can show the other rows from the filter on that column;
- that the `found_by` column says why each question is there, and the IM can delete rows they don't need;
- the Suggested additions at the end, if any: questions drafted for topics the bank doesn't cover. The IM
  keeps, edits or deletes them in the sheet;
- the **call-notes prompt** (`call_prompt.text`) in a code block, so the IM can copy it: after a call, they
  paste it into their call-notes tool (for example Gong's AI) and bring the output to
  `/source-scope-answers`, which then matches answers to questions by ID. Say it has the priority-1
  questions (`call_prompt.questions`); if they want all of them, call `im_scope_record` again with the same
  arguments and `call_prompt_priorities: []`, and show the new prompt;
- that `/source-scope-answers` fills the answers from merchant material (that output, notes, a call
  summary, emails) when they have some;
- any mismatch `im_scope_record` reports, and what it means;
- the feedback form link from `im_scope_record`, asking the IM to rate this run.

## Rules

- The IM's notes are only passed to `im_scope_start`. Never write them into the sheet or anywhere else.
- Only the copy is changed. Don't share it; it stays private to the IM until they share it.
- If something fails after the copy exists, say where things stand and give the copy's link. Don't
  trash files.
