# Working on the IM MCP

Instructions for Codex (and people) working in this repo.

## Start here

1. Read [docs/architecture.md](docs/architecture.md): the pieces, the design rules, the code map and how a
   command works. Its design rules are deliberate. If a change would break one, stop and discuss it
   first.
2. Read [docs/project-plan.md](docs/project-plan.md) for what's done, what's next and the backlog. Update
   it when something is finished or the plan changes.
3. [README.md](README.md) explains setup, running and installing the MCP.
4. `docs/archive/` holds old design discussions. Use it for history, not as a spec.

## How we work

- **Review before building.** Propose the execution steps (what changes, where, and why) and wait for
  approval before writing code. Small fixes the owner asked for directly are fine.
- **Never read, print or edit `.env`.** The owner edits it. Secrets (API keys, passwords, internal
  URLs) live only there. `.env.example` documents every variable without real values.
- **Don't run system or network commands you weren't asked to** (`netstat`, `lsof`, `docker inspect`,
  ...). Ask first.
- **Never edit the master question bank** from code or a command. Only people edit it. Load changes
  with `im_bank_load`: dry run first, apply only after the owner confirms.
- **Question IDs are permanent.** Never renumber or reuse them.
- **Never delete files you weren't asked to delete.**
- **Don't put merchant material, answers or people's names** in the database, logs, traces, tests or
  docs. Use made-up examples.

## Code patterns

- **Logic lives in `src/imcp/scope/` (and `bank/`), not in the MCP server or the routers.** The MCP
  server only checks arguments, reads `data/` and `inputs/`, and calls the app server. Routers only
  call `scope/` functions and turn `RunError` into HTTP errors.
- **A command is start → (plan) → write → record.** Start saves a `generation` draft; the plan returns
  an exact Sheets batch; the skill sends it unchanged and reads column A back; record checks it and
  finishes the run.
- **Plans are pure functions where possible** (`sheet_plan.py`, `answers_plan.py`), tested with
  `FakeTab` in `tests/test_sheet_plan.py`, which plays a batch on a grid.
- **Our model's output is always checked** against the bank: IDs, types and options. Use `FakeModel`
  (`tests/fakes.py`) in tests; tests never call a real model.
- **Slow work is a job** (`src/imcp/app/jobs.py`), waited on in calls of at most 40 seconds.
- **Schema changes are new Alembic migrations**, never edits to old ones.
- **Settings come from environment variables** through `src/imcp/config.py`. No hard-coded links.

## Tests

```
docker compose up -d postgres     # the test database (imcp_test) is created with the app's
uv run pytest -q                  # tests/db/ are skipped if the database isn't reachable
```

## Writing style

Skills, docs and messages are plain English: short sentences, everyday words, no jargon an IM wouldn't
use. Say what happened and what to do next.
