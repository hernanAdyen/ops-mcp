---
name: propose-solution
description: Use when an implementation manager runs /propose-solution or wants the solution proposal document written from their scope sheet. Picks the answers, gets a research brief from the knowledge graph, researches the Adyen docs, and fills a copy of the proposal master in Drive.
---

# /propose-solution

Write the solution proposal for one merchant from their scope sheet: a copy of the proposal master,
filled with the merchant's answers (Discovery and Features & Functionality), your researched solution
(Technical Considerations and Integration Design), a flow diagram and documentation links from our
knowledge graph. The IM reviews the document itself.

**Needs:** the IM MCP (its tools are `im_proposal_start`, `im_proposal_plan` and `im_proposal_record`; their
full names may carry a prefix, and they may have to be loaded with a tool search first), the Google Sheets
connector (to read the scope), and the Google Drive and Google Docs connectors (to copy and fill the
document). If the IM MCP can't reach its app server, tell the IM to check that `docker compose up` is
running, and stop.

## 1. Read the scope

- **The scope sheet.** Use the one from this chat, or a link the IM gives. If there's neither, ask for the
  link in one short message. Its file ID is the part of the link after `/d/`.
- **The track tabs.** Read the spreadsheet's tabs (fields `sheets.properties`). The track tabs are the ones
  whose row 1 starts with `id`. The proposal covers every track tab, in tab order: one block of sections
  per track in the document (2.1, 2.2, ... and 3.1, 3.2, ...). Don't ask which tab.
- **The columns.** For each track tab, read the header row (`'<tab>'!1:1`), column A (`'<tab>'!A:A`) and,
  by their header names, the `answer` column and, where the tab has them, `status`, `source` and
  `question`. Count columns from A (the 5th is E). Turn each into one string per row, starting with its
  header cell, with `''` for an empty cell. Never work out which rows are answered yourself.

## 2. Start the run

Call **`im_proposal_start`** with the sheet's file ID and `tabs`: one entry per track tab, in tab order,
with the tab's title (`name`), its column A (`id_column`) and `columns` (each column you read, keyed by its
header name, e.g. `{"answer": [...], "status": [...], "source": [...], "question": [...]}`). If the sheet
wasn't made by `/create-scope`, also pass `merchant_name`.

It returns a `draft_id`, the merchant, `master_doc_url`, the IM's `proposals_folder_url` if their MCP has
one configured, the introduction answers, and per track: the
Discovery answers, the Features table rows, the `suggested_used` IDs (answers found by
`/source-scope-answers` that the IM hasn't confirmed), the open priority-1 questions, and the **brief**:
the requirements, the nearest documentation pages (each with a `.md` link that is lighter to read), the
nearest flow diagrams, the designs the graph knows, what each section covers, and the `instructions`.
If it returns an error, tell the IM in one line and stop.

## 3. Research and draft

Follow the `instructions` in the result. For each track, from its own brief:

1. Read the brief's pages (use the `.md` links) and research the rest on the documentation site, starting
   from what the requirements need. Every statement about Adyen must come from a page you read.
2. Write **3.x.1 Technical Considerations** and **3.x.2 Integration Design** as lists of plain
   paragraphs: up to 8 each, up to 1,200 characters each, short sentences, no marketing, no merchant
   contact details or people's names. The `sections` in the brief say what each covers.
3. List the documentation `links` you used, best first: only links from the brief or pages under the
   documentation host. Anything else is refused.
4. Write **1.4 Project Background** and **1.5 Project Goals** from the introduction answers, one to three
   short paragraphs each. If the sheet has no answer for one, leave it empty: the server uses the sheet's
   text or leaves the heading for the IM.

The draft is `{introduction: {background: [...], goals: [...]}, tracks: [{name, technical_considerations:
[...], integration_design: [...], links: [...]}]}` with one entry per track, named exactly as its tab.

## 4. Make the document

1. **Folder.** If `im_proposal_start` returned `proposals_folder_url`, use that folder (its ID is the part
   after `/folders/`) without searching. Otherwise search Drive for a folder titled `SolutionProposals`
   in My Drive (`title = 'SolutionProposals' and mimeType = 'application/vnd.google-apps.folder' and
   parentId = 'root'`), and create it there if there isn't one.
2. **Copy** the master (`master_doc_url`; its file ID is the part after `/d/`) into that folder, named
   `<merchant name> - Solution Proposal`. Never edit the master itself.
3. **Read the copy** with the Docs connector. Take its body: `body.content` (if the document has tabs, the
   first tab's `documentTab.body.content`).
4. **Derive the outline**: one item per element of the body, in order, exactly as the API gives the
   indexes:
   - a paragraph: `{"s": startIndex, "e": endIndex, "text": ..., "style": paragraphStyle.namedStyleType}`.
     `text` is the paragraph's text (the `textRun` contents joined) without its final newline. For a
     paragraph that contains `{{`, give the full text; for any other, the first 40 characters are enough;
   - a table: `{"s", "e", "rows": [{"s", "e", "cells": [{"s", "e", "text"}]}]}` from its `tableRows` and
     `tableCells` (cell text = the text of its paragraphs, without final newlines);
   - anything else (a section break, the table of contents): `{"s", "e", "kind": "sectionBreak" | "toc"}`.
     The first section break has no `startIndex`: leave `s` out.
   Copy every `startIndex` and `endIndex` as given. The server checks that they line up and refuses the
   plan if they don't; it never guesses an index.

## 5. Plan and write

1. Call **`im_proposal_plan`** with the `draft_id`, the same `tabs` as at start, your `draft` and the
   `outline`. It checks the draft (sections, lengths, links) and the outline against the master's tokens,
   and returns the exact Docs batch `requests`, plus the `links` and `diagram` it chose. If it refuses,
   fix what it names (a link, a length, the outline) and call again. Never edit the document by hand.
2. Send the **`requests` unchanged, in one Docs batchUpdate** on the copy (`documentId` = the copy's
   file ID). Don't edit, reorder or split them, and never work out indexes yourself. If the batch fails,
   tell the IM what the API said and stop: nothing was written.
3. Call **`im_proposal_record`** with the `draft_id`, the copy's file ID (`doc_id`) and its link
   (`https://docs.google.com/document/d/<file ID>/edit`). Pass `leftover_tokens` only if you know a
   `{{token}}` is still in the document.

## 6. Reply

Keep it short:

- the document, as a link on its name;
- what was filled, per track: the Discovery and Features table rows, the two solution subsections, the
  diagram (or that none matched the track), the documentation links;
- one line on where the answers came from: how many were the IM's own and how many came from merchant
  material (`suggested_used`). Don't list the IDs and don't ask for confirmation: the IM changes anything
  by asking, or in the sheet or the document;
- the open priority-1 questions (up to 10, and how many in all): the proposal was written without them;
- that the Stakeholders table, the Timeframe and the Conclusion are theirs to fill, and that the table of
  contents is refreshed by clicking it in the document and choosing update;
- the feedback form link from `im_proposal_record`, asking the IM to rate this run.

## Rules

- The sheet's answers and your draft go only to the IM MCP tools and into the copy. Don't write them
  anywhere else or quote them back beyond the reply above.
- Documentation links in the document come only from the plan. Don't add links yourself.
- Only the copy is changed. Don't share it; it stays private to the IM until they share it. Don't trash
  files.
- If something fails after the copy exists, say where things stand and give the copy's link.
