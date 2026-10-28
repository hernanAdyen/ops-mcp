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

## Why it matters

- **Time.** Today a scope sheet is assembled by hand from the question bank, answers are copied out of
  call notes one by one, and a solution proposal is written from a blank copy of the template. With the
  three commands, the scope sheet takes a minute, a call's answers land in the sheet in the time it
  takes to read them, and a proposal's first draft, with the merchant's answers, a researched solution
  per track, a diagram and real documentation links, is ready to review in a quarter of an hour. The IM's
  time goes into judgement and the conversation with the merchant, not into copying.
- **One standard.** Every proposal starts from the same master, every answer is tied to a question in
  the bank by its permanent ID, every documentation link is a real page the knowledge graph knows, and
  every run is recorded. Two IMs scoping two merchants produce documents that read the same way, and a
  reviewer knows where each statement came from.
- **The scope builds up over the project.** Each call's findings carry their date and source, an
  answer the material confirms is marked confirmed, a later call that says something different marks a
  conflict for the IM to settle, and the Scope log keeps the history. Nothing is overwritten and nothing
  is lost between meetings.
- **IM knowledge becomes an asset.** The question bank carries what each question is for and which
  ones every project needs; the knowledge graph holds the documentation, the approved diagrams and, next,
  the team's past proposals, so a new IM's proposal draws on the designs the experienced ones used. That
  same graph is the base for what comes after: recommending a design from a scope, spotting what a
  scope is missing, seeing which questions decide the effort, onboarding new IMs faster.
- **Private by design.** Merchant material goes to the team's own model for one run and is never
  stored; what comes back is scrubbed of contact details and keys; the files stay in the IM's own Drive;
  every run's record keeps IDs and counts, never the material.
- **Measurable.** The extraction is scored against fictional cases with known right answers, so a
  change to a prompt or a model shows up as a number, not an opinion.

## What you need

- **Docker** (Docker Desktop or similar), or a local Postgres with pgvector (see "Without Docker")
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

### Without Docker

The app server is a Python program and the database is Postgres with the pgvector extension, so
both run on the machine itself.

1. **Postgres with pgvector.** On a Mac, [Postgres.app](https://postgresapp.com) ships pgvector; with
   Homebrew, `brew install postgresql@18 pgvector`. On Linux, your distribution's `postgresql` and
   `postgresql-18-pgvector` packages. Start it and make sure `psql` connects as the admin user.
2. **The app's user and databases.** The same file Docker runs on first start works with `psql`; it
   reads the names from the environment. With the values from your `.env`:

   ```bash
   set -a; . ./.env; set +a; psql -v ON_ERROR_STOP=1 -d postgres -f docker/postgres/initdb/01-app-database.sql
   ```

   (`set -a` exports the `.env` values for that shell, so the password never goes on the command line.)

   This creates the login, the `imcp` and `imcp_test` databases, and pgvector in both. Once only.
3. **Settings.** The same `.env` works. `DB_HOST` defaults to `127.0.0.1`, so nothing to add unless
   Postgres is elsewhere; the app reads `APP_DB_USER`, `APP_DB_PASSWORD` and `APP_DB_NAME` as Docker does.
4. **Schema, then the server**, from the repo folder:

   ```bash
   uv sync
   uv run alembic upgrade head
   uv run imcp-app
   ```

   The server listens on `http://localhost:8787`; the same health check applies. Run
   `uv run alembic upgrade head` again after pulling new code, and restart `imcp-app`.

The draft of the bank columns (section 5) runs as `uv run python -m imcp.bank.draft` here.

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
      "args": ["--directory", "/full/path/to/implementation-mcp", "run", "imcp-mcp"],
      "env": {
        "PROPOSALS_DRIVE_FOLDER_URL": "https://drive.google.com/drive/folders/<your folder id>"
      }
    }
  }
}
```

`PROPOSALS_DRIVE_FOLDER_URL` is the link to your own Drive folder where the scope sheets and proposals
go; the skills copy straight into it. Leave the `"env"` block out and they look for a
`SolutionProposals` folder in My Drive instead, creating it if needed.

Use full paths: `which uv` shows uv's. Restart Claude desktop. In a chat, ask Claude to run the IM
MCP health check: it should reach the app server and the database.

Other optional settings for the same `"env"` block: `APP_SERVER_URL` (default
`http://localhost:8787`), and `IMCP_DATA_DIR` and `IMCP_INPUTS_DIR` (default the repo's `data/` and
`inputs/`).

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

Do this again whenever the master changes. The master itself, the proposal master document and the
diagram images live in the team's shared Drive folder; `QUESTION_BANK_URL` and `PROPOSAL_MASTER_URL`
in `.env` point at the first two.

## 6. Load the documentation graph and the diagrams

The proposal's research brief and documentation links come from a graph of Adyen doc pages, and its
flow diagram from a registry of images. Both load from files in `data/graph/`, which are in git:

1. **Doc pages.** `adyen-doc-pages.csv` says which sections of docs.adyen.com go into the graph. Ask
   Claude to load the Adyen docs into the graph: a dry run first (how many pages, by section), then
   apply. It reads the docs index at `DOCS_INDEX_URL`, embeds a title and one-line description per
   page, and never stores page content. About 900 pages; a few minutes.
2. **Diagrams.** `diagrams.csv` lists the approved flow diagrams: a title, a link to the image, a
   one-line description and the tags that say which projects it fits. Ask Claude to load the diagrams
   the same way.

**Publishing a diagram image.** Google Docs fetches the image itself from the public internet when
the proposal is written, so the link has to be reachable without a login: a server on your laptop or
inside the VPN won't work. The simplest home is the team's shared Drive folder: upload the PNG, JPEG or
GIF there, set its sharing to **Anyone with the link, Viewer**, copy the share link
(`https://drive.google.com/file/d/.../view?usp=sharing`) and paste it into the `url` column. The
loader turns it into the direct image link Docs needs. A plain https link to a PNG, JPEG or GIF
elsewhere works too. Diagrams are generic Adyen flows, never merchant material.

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

- Tests: `docker compose up -d postgres` (or your local Postgres), then `uv run pytest -q`. Tests in
  `tests/db/` use a separate test database (`imcp_test`) and are skipped if it isn't reachable.
- Schema changes: add an Alembic migration in `migrations/versions/`. `docker compose up` applies it;
  without Docker, `uv run alembic upgrade head`.
- Read [CLAUDE.md](CLAUDE.md) and [docs/architecture.md](docs/architecture.md) before changing code.

## Troubleshooting

| Problem | What to do |
|---|---|
| `docker compose` can't pull an image | Docker Hub is blocked at Adyen: set `PYTHON_IMAGE` and `POSTGRES_IMAGE` to the internal registry's |
| `uv` can't download packages | Set the package index: `UV_DEFAULT_INDEX` in `.env` (Docker) and `~/.config/uv/uv.toml` (the MCP) |
| `uv.lock` errors after switching machines | Delete `uv.lock` and run `uv sync`; it's made per machine |
| Claude says it can't reach the app server | Is `docker compose up` (or `uv run imcp-app`) running? Check `curl http://localhost:8787/health` |
| `imcp-app` says to set `APP_DB_PASSWORD` | Run it from the repo folder, where `.env` is |
| A diagram doesn't appear in the proposal | Its image must be fetchable without a login: Drive sharing set to "Anyone with the link" |
| The model check fails | Check `MODEL_BASE_URL`, `MODEL_NAME` and `MODEL_API_KEY`; the internal model needs the VPN |
| A run says "still working" | Normal for long material: Claude asks again until it's done |
