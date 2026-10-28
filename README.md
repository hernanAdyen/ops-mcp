# IM MCP

Tools in Claude for Adyen implementation managers: build a merchant's scoping sheet from the question
bank, fill it from call notes, and write the solution proposal.

| Command | What it does |
|---|---|
| `/ops-create-scope` | Picks the scoping questions for a merchant and builds a scope sheet in your Drive |
| `/ops-answer-scope` | Finds the answers in your merchant notes, call summaries or emails and writes them into the sheet for you to review |
| `/ops-create-solution` | Writes the solution proposal from the scope sheet into a copy of the proposal master: the merchant's answers, a researched solution per track, a diagram and documentation links |

How it's built: [docs/architecture.md](docs/architecture.md). Status and next steps:
[docs/project-plan.md](docs/project-plan.md).

## What you need

- **Docker** (Docker Desktop or similar)
- **uv** ([install guide](https://docs.astral.sh/uv/getting-started/installation/)), which also installs Python 3.13
- **Claude desktop**, with the Google Drive and Google Sheets connectors connected
- **A model:** any OpenAI-compatible chat API. At Adyen, the internal model (needs the VPN). On a
  personal machine, an OpenAI API key works.

## 1. Get the code and settings

```
git clone <this repo> implementation-mcp
cd implementation-mcp
cp .env.example .env
```

Fill in `.env`. Every variable is explained in `.env.example`. The ones you must set:

| Variable | What |
|---|---|
| `POSTGRES_ADMIN_PASSWORD`, `APP_DB_PASSWORD` | Passwords for the local database (make them up) |
| `QUESTION_BANK_URL` | Link to the master question bank sheet |
| `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_API_KEY` | Your model. OpenAI: `https://api.openai.com/v1`, e.g. `gpt-4.1-mini`, your key |
| `EMBEDDING_MODEL` | The embedding model for the graph, e.g. `text-embedding-3-small`. Called at `MODEL_BASE_URL` + `/embeddings` with `MODEL_API_KEY`, unless `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` are set |
| `DOCS_INDEX_URL` | The Adyen docs index the doc page loader reads: `https://docs.adyen.com/llms.txt` |
| `FEEDBACK_FORM_URL` | The feedback form (optional) |

**Images and packages.** Leave `PYTHON_IMAGE`, `POSTGRES_IMAGE` and `UV_DEFAULT_INDEX` blank to use the
public ones (Docker Hub and PyPI). On an Adyen laptop those are blocked, so set the internal registry
images and package mirror instead.

## 2. Start the app server

```
docker compose up -d --build
```

This starts Postgres, brings the database up to date, and starts the app server on
`http://localhost:8787`. Check it: `curl http://localhost:8787/health` should say `"status": "ok"`.
After pulling new code, run the same command again.

## 3. Add the IM MCP to Claude desktop

The MCP server runs on your machine with uv. First let uv set it up (this also creates `uv.lock`
from your package index):

```
uv sync
```

On an Adyen laptop, tell uv to use the internal mirror first, once, in your user settings (not in the
repo), in `~/.config/uv/uv.toml`:

```toml
native-tls = true

[[index]]
url = "<internal PyPI mirror URL>"
default = true
```

Then open Claude desktop's MCP settings file (Settings → Developer → Edit Config, which opens
`claude_desktop_config.json`) and add:

```json
{
  "mcpServers": {
    "implementation-mcp": {
      "command": "/full/path/to/uv",
      "args": ["--directory", "/full/path/to/implementation-mcp", "run", "imcp-mcp"]
    }
  }
}
```

Use full paths: `which uv` shows uv's. Restart Claude desktop. In a chat, ask Claude to run the IM
MCP health check: it should reach the app server and the database.

Optional settings for the MCP go in an `"env"` block next to `"args"`: `APP_SERVER_URL` (default
`http://localhost:8787`), `IMCP_DATA_DIR` and `IMCP_INPUTS_DIR` (default the repo's `data/` and
`inputs/`), and `PROPOSALS_DRIVE_FOLDER_URL`, the link to your own Drive folder for scope sheets and
proposals (the skills copy straight into it; without it they look for a `SolutionProposals` folder in
My Drive and create one if needed).

## 4. Add the skills

The commands are the skills in `skills/` (one folder each, with a `SKILL.md`). Add them to your Claude
account, for example by asking Claude in a chat to save the skills in `skills/` as your skills. Once
saved, `/ops-create-scope` and `/ops-answer-scope` appear as commands.

## 5. Load the question bank

1. Open the master question bank and download the **Project Scope** tab as CSV
   (File → Download → Comma-separated values).
2. Save it in the repo's `data/` folder (git-ignored).
3. Ask Claude to load the question bank. It shows a dry run first (new, changed, deactivated, retired,
   invalid questions) and loads it only after you confirm.

Do this again whenever the master changes.

Optional columns in the master, found by their header: `purpose` (one line on what the answer
accomplishes; our model sees it when it looks for answers), `baseline` (Y: the question is in every
scope, whatever the tags) and `status` (`retired` deactivates the question and keeps its row; clear
it to bring the question back). To get a first draft of `purpose` and `baseline` from our model for
every loaded question, run from the repo:

```bash
mkdir -p data/drafts && docker compose exec -T app python -m imcp.bank.draft > data/drafts/bank-columns.csv
```

Review the CSV, paste the two columns into the master by ID, and load the bank again.

## Using it

- `/ops-create-scope Acme`: answer the question card (channels, pillars, sections, categories), add notes
  if you have them, and you get a sheet in `SolutionProposals` in your Drive, plus a prompt you can
  paste into your call-notes tool after calls.
- `/ops-answer-scope`, after each call: share what you have from the merchant (paste notes, an email
  or that prompt's output; save Gong transcripts and call summaries as a `.txt` file in `inputs/` and
  say so, so they never pass through the chat). Say which day each piece is from. Answers are filled
  into the sheet as `suggested` with their source and date; your own answers are never overwritten:
  one the material agrees with becomes `confirmed`, one it contradicts becomes `conflict` with the
  finding in `ai_note`, for you to settle in the sheet. The **Scope log** tab keeps one line per change.
  Material you already ran on a tab is skipped.
- Flags in `.env`: `FLAG_SANITIZE` scrubs email addresses, phone numbers, IBANs, card numbers and keys
  from what our model found (on by default); `FLAG_TRANSCRIPTS` lets `/ops-answer-scope` take call
  transcripts (on by default; off, it asks for a summary or notes instead). `im_health` shows them.

## Development

- Tests: `docker compose up -d postgres`, then `uv run pytest -q`. Tests in `tests/db/` use a separate
  test database (`imcp_test`) and are skipped if it isn't reachable.
- Schema changes: add an Alembic migration in `migrations/versions/`. `docker compose up` applies it.
- Read [CLAUDE.md](CLAUDE.md) and [docs/architecture.md](docs/architecture.md) before changing code.

## Troubleshooting

| Problem | What to do |
|---|---|
| `docker compose` can't pull an image | Docker Hub is blocked at Adyen: set `PYTHON_IMAGE` and `POSTGRES_IMAGE` to the internal registry's |
| `uv` can't download packages | Set the package index: `UV_DEFAULT_INDEX` in `.env` (Docker) and `~/.config/uv/uv.toml` (the MCP) |
| `uv.lock` errors after switching machines | Delete `uv.lock` and run `uv sync`; it's made per machine |
| Claude says it can't reach the app server | Is `docker compose up` running? Check `curl http://localhost:8787/health` |
| The model check fails | Check `MODEL_BASE_URL`, `MODEL_NAME` and `MODEL_API_KEY`; the internal model needs the VPN |
| A run says "still working" | Normal for long material: Claude asks again until it's done |
