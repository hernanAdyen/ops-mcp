---
name: ops-create-scope
description: Use when an implementation manager runs /ops-create-scope or wants a scoping question sheet for a new merchant. Picks bank questions by tags and context, one tab per project track, builds the sheet in Drive, and returns the link with a summary.
---

# /ops-create-scope

Build a prefiltered scoping question sheet for one merchant from the IM question bank, and give the
IM the link and a short summary. The IM reviews and trims the questions in the sheet, not in chat.

A scope has one or more **project tracks**: parts of the project the IM wants to scope and propose
separately, for example "Ecommerce US" and "In-person payments UK". Each track gets its own tab in the
sheet, named after the track, with its own questions. Most scopes have one track; its tab is called
Project Scope.

**Needs:** the IM MCP (its tools are `im_scope_start`, `im_scope_wait`, `im_scope_sheet_plan` and
`im_scope_record`; their full names may carry a prefix, and they may have to be loaded with a tool search
first), and the Google Drive and Google Sheets connectors. If the IM MCP can't reach its app server, tell
the IM to check that `docker compose up` is running, and stop.

## 1. Gather the inputs

Use what the IM already gave (e.g. `/ops-create-scope Acme, PFS + CAPITAL, migrating tokens`) and ask
only for what's missing.

- **Merchant name** (required). If it's missing, ask for it in one short chat message first.
- **Tracks.** Ask in one short message: does the project have more than one track, for example online
  and in-store, or two countries? If so, what are they called? Say that one track is the usual answer.
  "One", "no" or no tracks named means one track, called Project Scope. Up to 6 tracks. A track name
  becomes a tab title, so it can't contain `[ ] * ? : / \`. Use the IM's names as they gave them.
- **Tags.** Ask with one question card (AskUserQuestion) **per track**, three multi-select questions:
  channels, pillars and categories. With several tracks, name the track in each question ("Channels for
  Ecommerce US?"). Leave out any question the IM already answered. Put "All" first in every question.
  - Channels: All, ECOM, IPP, MOTO
  - Pillars: All, DIGITAL, PFS, UC
  - Categories (the bank's `category` column; a card holds four options, so they come in groups):
    All, Payments (PAYIN, PAYOUT), Onboarding & payouts (KYC, PAYFAC, CASHOUT),
    Capital & reporting (CAPITAL, REPORTING_RECONCILIATION). Mention that exact categories can be
    typed in Other.
  - "All", or every option of a question selected, means no filter on that tag: pass an empty list.
    Each category group means all the categories in it.
  - Subsections, priorities and platforms aren't asked: don't filter on them, unless the IM gave them
    in the command (e.g. `/ops-create-scope Acme, BALANCE, P1 only`, or "discovery only"). Pass subsections
    as `introduction`, `discovery`, `features_functionality`, and priorities as 1, 2, 3.
- **Context.** After the cards, unless the IM already gave it, ask in one short chat message for their
  notes on the merchant (e.g. "launching Capital for their sellers, migrating tokens from their current
  PSP"), or "none". The notes cover the whole project; the server uses them for every track. A card
  can't ask this: a question needs at least two options to choose from.
  Pass the IM's own notes. If they paste a long call transcript, don't pass it: summarise the merchant's
  needs in a few sentences, without names or other personal details, and pass that.
- If the question card isn't available, ask for the tags and context in one short message instead.

## 2. Start the run

Call `im_scope_start` with the merchant name, the context and the tags: for one track, the tags
directly; for several, `tracks`, one entry per track with its name and its tags, and nothing in the
direct tags. If it returns `pending` with a `job_id` (our model is still working), call `im_scope_wait`
with that `job_id`, again if it is still pending, until you get the result. Never call `im_scope_start`
twice for the same scope.

It returns a `draft_id`, `master_sheet_url`, the IM's `proposals_folder_url` if their MCP has one
configured, and per track (`tracks`): counts of the tag matches, of the baseline questions (in every
scope whatever the tags, within the priorities and sections asked for), the
questions our model added by topic (each with a reason) and topics no bank question covers. The
`gap_questions` (IDs like NEW-0001) are drafted for topics no bank question covers; they go under
**Suggested additions** at the end of the first tab. If it returns an error, tell the IM in one line
and stop.

## 3. Confirm the questions added by topic

The tag matches need no review here. Show the IM, briefly, per track:

- the number of tag matches, by subsection, and the number of baseline questions (`baseline`);
- each question added by topic: ID, question and the reason;
- one line if topic matching was skipped (no context) or unavailable.

And once: the topics from their notes that no bank question covers, each with the question our model
drafted for it. These go under **Suggested additions** at the end of the first tab, for the IM to review
there.

If there are additions or drafted questions, ask whether to create the sheet with them, noting that they
can drop any of them (by ID, including NEW- IDs) or add a bank question by ID. Remember what they drop
(`remove_ids`) and add (`add_ids`). With several tracks, a change the IM ties to one track goes in
`tracks` (the track's name with its own `remove_ids` and `add_ids`); a change with no track named applies
to every track. If there are neither, go straight on.

## 4. Build the sheet

1. **Folder.** If `im_scope_start` returned `proposals_folder_url`, use that folder (its ID is the part
   after `/folders/`) without searching. Otherwise search Drive for a folder titled `SolutionProposals`
   in My Drive (`title = 'SolutionProposals' and mimeType = 'application/vnd.google-apps.folder' and
   parentId = 'root'`), and create it there if there isn't one.
2. **Name.** `<merchant name> <YYYY-MM-DD HHmm>`, using the current date and time where the IM is.
3. **Copy** the master bank into that folder with that name. Its file ID is the part of
   `master_sheet_url` after `/d/`. Never edit the master itself.
4. **Read the copy's tabs** (fields `sheets.properties` and `sheets.basicFilter`) and note the
   `Project Scope` tab's `sheetId`, `gridProperties.columnCount` and its `basicFilter`, if it has one.
   Also note every tab's `sheetId`, in tab order (`sheet_ids`).
5. **Read column A** of the copy: `'Project Scope'!A:A`. Turn it into one string per row, starting
   with the `id` header, with `''` for an empty row. Also read the **header row**: `'Project Scope'!1:1`.
6. Call **`im_scope_sheet_plan`** with the `draft_id`, that `sheetId`, the column count, column A, the
   header row, the tab's `basicFilter` exactly as read (`basic_filter`; leave it out if there's none),
   `sheet_ids`, and the IM's `remove_ids`, `add_ids` and `tracks` changes. If it refuses (for example an
   unknown ID), tell the IM and fix that before changing anything.
7. Send the returned **`requests` unchanged, in one Sheets batch update** on the copy. Don't edit,
   reorder, split or recalculate them, and never work out row numbers yourself. The batch renames the
   Project Scope tab to the first track and makes a tab per further track (`new_tabs` says which), then
   fills each tab from its own track.
8. **Read column A of every track's tab again**, the same way (`'<tab title>'!A:A`). The tab titles are
   the track names from the plan's `tracks`.
9. **Consent.** If `im_scope_start` said `review_queue_on` and the first tab has drafted questions
   (NEW- IDs), ask with one question card: "Share the N drafted questions with the question bank owner,
   so future IMs can use them? Only the question wording is shared: no answers, notes or merchant
   details." Options: "Yes, share them" and "No, keep them in my sheet only". Otherwise don't ask.
10. Call **`im_scope_record`** with the `draft_id`, the merchant name, the copy's file ID, its link
   (`https://docs.google.com/spreadsheets/d/<file ID>/edit`), `tabs` (each track tab's title with the
   column A you just read; for one track, `sheet_question_ids` alone is fine), and
   `share_new_questions` true only if the IM said yes.

## 5. Reply

Keep it short:

- the sheet, as a link on its name;
- the tabs: one per track, named after it (with one track, just Project Scope);
- per track, the number of questions, by section, and how they were found (tags, baseline, topic,
  added by you);
  each tab is grouped by section, each with a collapsible group;
- if the plan's `filter` is `kept`: the tabs open with the master's filter on (e.g. P1 only), and
  the IM can show the other rows from the filter on that column;
- that the `found_by` column says why each question is there, and the IM can delete rows they don't need;
- the Suggested additions at the end of the first tab, if any: questions drafted for topics the bank
  doesn't cover. The IM keeps, edits or deletes them in the sheet;
- that `/ops-answer-scope` fills the answers from merchant material (that output, notes, a call
  summary, emails) when they have some, one tab at a time;
- any mismatch `im_scope_record` reports (per track), and what it means;
- the feedback form link from `im_scope_record`, asking the IM to rate this run.

## 6. Offer the call-notes prompt

After the reply, and only then, ask in one short message: "Do you want a call-notes prompt to paste
into Gong after the call? It lists the scope's questions by ID: the priority-1 ones, or all of them."
If the IM says no, or doesn't answer, stop. If yes:

1. Call **`im_scope_call_prompt`** with the `draft_id`, `sheet_ids` (every tab's sheetId in the sheet
   now, in tab order: the ones you read earlier plus the plan's `new_tabs`) and `priorities` (`[1]`, or
   `[]` for all).
2. Send its **`requests` unchanged, in one Sheets batch update** on the sheet (nothing to send if
   `already_there`).
3. Reply with one line: **"Call prompt for Gong"** as a link on `url` (the sheet's `Call prompt` tab),
   and how many questions it holds (`questions`). After a call they copy it from that tab into their
   call-notes tool and bring the output to `/ops-answer-scope`, which matches answers by ID. Never
   print the prompt text in chat.

## Rules

- The IM's notes are only passed to `im_scope_start`. Never write them into the sheet or anywhere else.
- Only the copy is changed. Don't share it; it stays private to the IM until they share it.
- If something fails after the copy exists, say where things stand and give the copy's link. Don't
  trash files.
