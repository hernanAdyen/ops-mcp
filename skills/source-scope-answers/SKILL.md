---
name: source-scope-answers
description: Use when an implementation manager runs /source-scope-answers or wants answers from merchant material (notes, a call summary or transcript, emails, documents) filled into their scope sheet. Fills only empty answers in Project Scope and suggests additions for the IM to review in the sheet.
---

# /source-scope-answers

Find the answers to the scope sheet's questions in whatever the IM has from the merchant, write them
into the sheet's Project Scope tab, and suggest questions the scope doesn't have yet. The IM reviews
everything in the sheet itself.

**Needs:** the IM MCP (its tools are `im_answers_start`, `im_answers_wait`, `im_answers_record` and `im_inputs_list`; their
full names may carry a prefix, and they may have to be loaded with a tool search first), the Google
Sheets connector, and the Google Drive connector for doc links. If the IM MCP can't reach its app
server, tell the IM to check that `docker compose up` is running, and stop.

## 1. Gather the inputs

- **The scope sheet.** Use the one `/create-scope` made in this chat, or a link the IM gives. If there's
  neither, ask for the link in one short message. Its file ID is the part of the link after `/d/`.
- **The material.** Ask the IM to share whatever they have from the merchant: paste notes, a call summary,
  a transcript or an email, attach a file, or give a Google Doc link. Don't ask for a particular source or
  system. The output of the call-notes prompt from `/create-scope` works best, because it answers by ID.
  - Give each piece a short label the IM will recognise, e.g. "Call summary, Oct 24" or "Email from
    finance". Use what the IM calls it; ask only if it's unclear. No people's names in labels.
  - Give each piece its kind: `transcript`, `summary`, `notes`, `email` or `document`.
  - A Google Doc: read it with the Drive connector and pass its text. An attachment: read its text and
    pass that.
  - Long material (more than about 20,000 characters, such as a full call transcript): suggest the IM
    saves it as a .txt or .md file in the IM MCP's `inputs/` folder, then pass it as `files` instead of
    pasting it into the tool call. `im_inputs_list` shows what is there.
  - The material goes to the IM MCP server and our model for this run only and is never stored. Don't
    write it anywhere else.

## 2. Read the sheet

1. Read the spreadsheet's tabs (fields `sheets.properties` and `sheets.basicFilter`). Note the
   `Project Scope` tab's `sheetId`, `gridProperties.columnCount`, `gridProperties.rowCount` and its
   `basicFilter`, if it has one.
2. Read the header row: `'Project Scope'!1:1`.
3. Read column A: `'Project Scope'!A:A`. Turn it into one string per row, starting with the `id` header,
   with `''` for an empty row.
4. From the header, find the columns named `answer` and, if they are there, `source`, `confidence`,
   `status` and `ai_note`. Count from A (the 5th column is E, the 14th is N). Read each one the same way,
   e.g. `'Project Scope'!E:E`: one string per row, starting with its header cell.
5. If any ID in column A starts with `NEW-`, also read the `question` column and note each NEW- row's
   current question text.

## 3. Find the answers

Call **`im_answers_start`** with: the file ID (`sheet_id`); the tab's `sheetId`, column count and row
count; the header row; column A; `columns` (each column you read, by its header name, e.g.
`{"answer": [...], "status": [...]}`); `new_rows` (`[{id, question}]` for the NEW- rows); the
`basicFilter` exactly as read (leave it out if there's none); and the material: pasted text as
`material`, saved files as `files`. If the sheet wasn't made by `/create-scope`, also pass `merchant_name`.

It returns a `draft_id`, a `summary` and `requests`. If it returns `pending` with a `job_id` instead (our
model is still working), call **`im_answers_wait`** with that `job_id`, again if it is still pending,
until you get the result. Never call `im_answers_start` twice for the same material. If it refuses because something was passed wrongly,
fix that and call again. If our model is unavailable, tell the IM in one line and stop: nothing was
written.

## 4. Write to the sheet

1. Send the returned **`requests` unchanged, in one Sheets batch update** on the sheet. Don't edit,
   reorder, split or recalculate them, and never work out rows or cells yourself.
2. **Read column A again**, the same way.
3. **Consent.** If the summary says `review_queue_on` and there are `new_questions`, ask with one question
   card: "Share the N new questions with the question bank owner, so future IMs can use them? Only the
   question wording is shared: no answers, material or merchant details." Options: "Yes, share them" and
   "No, keep them in my sheet only". Otherwise don't ask.
4. Call **`im_answers_record`** with the `draft_id`, the sheet's link
   (`https://docs.google.com/spreadsheets/d/<file ID>/edit`), the column A you just read, and
   `share_new_questions` true only if the IM said yes.

## 5. Reply

Keep it short:

- the sheet, as a link on its name;
- how many answers were filled. Each filled answer is marked `suggested` in the `status` column, with
  its `source`, `confidence` and an `ai_note`. Their own answers were kept;
- each conflict: the question, their answer and what the material says. Their answer stays and the
  finding is in `ai_note`. Ask whether they want any of them changed;
- the **Suggested additions** at the end of the sheet, if any: bank questions the material answered that
  weren't in their scope, and new questions no bank question covers. They review them in the sheet:
  keep, edit or delete the rows, or set `status`;
- the open priority-1 questions from `im_answers_record` (up to 10, and how many in all), as the questions
  to ask on the next call;
- the feedback form link from `im_answers_record`, asking the IM to rate this run.

## Later changes

If the IM asks you to change an answer, a status or a suggested question, edit that cell in Project
Scope with the Sheets connector: find the row by its ID in column A and the column by its header. The
next run picks the change up. Don't change any other rows or columns.

## Rules

- The material is only passed to `im_answers_start`. Never write it into the sheet, a doc or a message,
  and don't quote it back.
- Only the sheet's Project Scope tab is changed: empty answers, the review columns and the additions at
  the end. Don't share the sheet, and don't trash files.
- If something fails after the batch, say where things stand and give the sheet's link.
