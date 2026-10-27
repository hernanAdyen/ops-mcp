# Evals

Repeatable measurements of what our model does, on fictional merchants with known right answers.
A change to a prompt or to the search shows up as a number here instead of in someone's eyeballing
of a sheet.

```
uv run python evals/run_extraction.py slice-street-pizza
```

Needs the app server running (`docker compose up`) with the model configured and the bank loaded;
it calls the real model. Nothing is recorded: the server saves a draft run and the sheet is described
in the request, so no Google access is needed. Results land in `evals/results/` (git-ignored).

## Cases

`evals/cases/<name>/case.json` plus the material file it names. Every merchant, person and domain in a
case is made up. A case has:

- `tabs`: one per track tab, with the question IDs in the tab (in sheet order) and `gold`, the expected
  answers by ID: `equals`, `contains`, `contains_any`, `not_contains` or `empty` (for questions the
  material leaves unanswered or undecided).
- `forbidden_words` per tab: words from the other track that must not appear in this tab's answers.
- `no_bank_additions_from` per tab: bank questions that belong to another track and must not be
  suggested as additions here.
- `covered_by_bank`: questions the material answers in prose; a new question with one of these as its
  closest bank question is a miss, not a find.

| Case | What it tests |
|---|---|
| `slice-street-pizza` | A two-track Gong summary (US online, FR in-store). Answers by ID per track, "not discussed" lines, undecided remarks, and prose notes that answer bank questions (offline processing, loyalty, token migration). |
