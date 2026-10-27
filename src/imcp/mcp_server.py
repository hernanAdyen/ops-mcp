"""Thin MCP server: every tool calls the app server over HTTP.

Run by Claude desktop on your Mac (stdio). Start with: uv run imcp-mcp
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from imcp import SERVICE_NAME, SERVICE_VERSION
from imcp.config import McpSettings
from imcp.db import enums as E

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/imcp/mcp_server.py -> repo


def data_dir(settings: McpSettings) -> Path:
    return (settings.IMCP_DATA_DIR or REPO_ROOT / "data").resolve()


def inputs_dir(settings: McpSettings) -> Path:
    return (settings.IMCP_INPUTS_DIR or REPO_ROOT / "inputs").resolve()


# Calls through a remote bridge give up after 60 s, so slow work is a job on the app server:
# each call waits at most this long, then returns the job ID to ask again with.
WAIT_SECONDS = 40

DOC_RULES_FILE = "adyen-doc-pages.csv"  # in data/graph/: which Adyen doc pages go into the graph
DIAGRAMS_FILE = "diagrams.csv"  # in data/graph/: the owner's curated flow diagrams
TEXT_SUFFIXES = {".txt", ".md", ".vtt", ".srt", ".csv", ".json", ".eml"}
MAX_INPUT_BYTES = 600_000
Kind = Literal["transcript", "summary", "notes", "email", "document"]


class MaterialArg(BaseModel):
    label: str = Field(description="Short label the IM will see as the source, e.g. 'Call summary, Oct 24'")
    kind: Kind = "notes"
    text: str = Field(description="The material as the IM gave it")


class FileArg(BaseModel):
    label: str = Field(description="Short label the IM will see as the source")
    kind: Kind = "transcript"
    file: str = Field(description="File name in the inputs/ folder")


class NewRowArg(BaseModel):
    id: str = Field(description="The row's ID in column A, e.g. NEW-0003")
    question: str = Field(description="Its text in the question column, as it is now")


class TrackArg(BaseModel):
    """One project track and its tags. An empty list means all values."""

    name: str = Field(description="The track's name, e.g. 'Ecommerce US'. It becomes the tab title.")
    channels: list[E.Channel] = Field(default_factory=list)
    pillars: list[E.Pillar] = Field(default_factory=list)
    categories: list[E.Category] = Field(default_factory=list)
    platforms: list[E.Platform] = Field(default_factory=list)
    priorities: list[Literal[1, 2, 3]] = Field(default_factory=list)
    subsections: list[E.Subsection] = Field(default_factory=list)

    def body(self) -> dict:
        tags = {k: v for k, v in self.model_dump(mode="json").items() if k != "name"}
        return {"name": self.name, "tags": tags}


class TrackChangesArg(BaseModel):
    name: str = Field(description="The track's name, as given to im_scope_start")
    remove_ids: list[str] = Field(default_factory=list)
    add_ids: list[str] = Field(default_factory=list)


class TabArg(BaseModel):
    name: str = Field(description="The tab's title (the track's name)")
    sheet_question_ids: list[str] = Field(description="Its column A, read back after the batch, starting with 'id'")


class ProposalTabArg(BaseModel):
    """One track tab of the scope sheet, as read for /ops-create-solution."""

    name: str = Field(description="The tab's title (the track's name)")
    id_column: list[str] = Field(description="Column A as read, starting with its 'id' header")
    columns: dict[str, list[str]] = Field(
        description="By header name, each column as read starting with its header: answer (required), and "
                    "status, source and question where the tab has them"
    )


def read_input(folder: Path, name: str) -> str:
    """A text file from the inputs folder. Nothing outside the folder can be read."""
    path = (folder / name).resolve()
    if not path.is_relative_to(folder) or path.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError(f"Only text files ({', '.join(sorted(TEXT_SUFFIXES))}) inside {folder} can be read.")
    if not path.is_file():
        raise FileNotFoundError(f"There's no file named {name} in {folder}.")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"{name} is larger than {MAX_INPUT_BYTES // 1000} KB. Split it into smaller files.")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def pick_csv(folder: Path, file: str | None) -> Path:
    """The CSV to load: the named file, or the newest .csv in the folder. Only files inside the folder."""
    if file:
        path = (folder / file).resolve()
        if not path.is_relative_to(folder) or path.suffix.lower() != ".csv":
            raise ValueError(f"Only .csv files inside {folder} can be loaded.")
        if not path.is_file():
            raise FileNotFoundError(f"There's no file named {file} in {folder}.")
        return path
    found = sorted(folder.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []
    if not found:
        raise FileNotFoundError(
            f"No .csv file in {folder}. Download the bank's Project Scope tab as CSV "
            "(File > Download > Comma-separated values) and save it there."
        )
    return found[0]


def build_server(settings: McpSettings | None = None, client: httpx.AsyncClient | None = None) -> MCPServer:
    settings = settings or McpSettings()
    base_url = str(settings.APP_SERVER_URL).rstrip("/")
    server = MCPServer(name=SERVICE_NAME, version=SERVICE_VERSION)

    async def call(method: str, path: str, body: dict | None = None, timeout: float = 5,
                   params: dict | None = None) -> httpx.Response:
        if client is not None:
            return await client.request(method, f"{base_url}{path}", json=body, params=params, timeout=timeout)
        async with httpx.AsyncClient(timeout=timeout) as c:
            return await c.request(method, f"{base_url}{path}", json=body, params=params)

    def unreachable(exc: Exception) -> str:
        return f"Could not reach the app server at {base_url}: {exc}. Is `docker compose up` running?"

    def run_path(draft_id: str, step: str, base: str = "/scope/runs") -> str:
        return f"{base}/{uuid.UUID(draft_id)}/{step}"  # a bad ID raises before any request is made

    # The IM's own settings the skills need: added to the results of the start tools.
    local = {"proposals_folder_url": str(settings.PROPOSALS_DRIVE_FOLDER_URL)} if settings.PROPOSALS_DRIVE_FOLDER_URL else {}

    async def post(path: str, body: dict, timeout: float = 30, compact: bool = False, extra: dict | None = None) -> str:
        try:
            res = await call("POST", path, body, timeout=timeout)
        except Exception as exc:
            return unreachable(exc)
        if res.status_code != 200:
            return f"The app server refused this (HTTP {res.status_code}): {res.text[:4000]}"
        data = {**res.json(), **(extra or {})}
        if compact:
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(data, indent=2, ensure_ascii=False)

    async def job_reply(method: str, path: str, body: dict | None = None, extra: dict | None = None) -> str:
        """A job on the app server: its result, or pending with the job ID to ask again with."""
        wait_tool = {"/scope/": "im_scope_wait", "/graph/": "im_graph_wait"}.get(path[:7], "im_answers_wait")
        try:
            res = await call(method, path, body, timeout=WAIT_SECONDS + 20, params={"wait": WAIT_SECONDS})
        except Exception as exc:
            return unreachable(exc)
        if res.status_code != 200:
            return f"The app server refused this (HTTP {res.status_code}): {res.text[:4000]}"
        data = res.json()
        if data.get("pending"):
            return json.dumps({"pending": True, "job_id": data["job_id"],
                               "next": f"Our model is still working. Call {wait_tool} with this job_id."})
        return json.dumps({**data, **(extra or {})}, ensure_ascii=False, separators=(",", ":"))

    @server.tool(
        name="im_health",
        title="IM MCP health check",
        description=(
            "Checks that the IM MCP can reach its app server and database, and which settings are "
            "configured (values are never shown). With check_model=true it also sends one tiny request "
            "to our model, to check its URL, key, certificates and network."
        ),
    )
    async def im_health(check_model: bool = False) -> str:
        try:
            params = {"check_model": "true"} if check_model else None
            res = await call("GET", "/health", timeout=60 if check_model else 5, params=params)
            mcp = {"proposalsFolder": bool(settings.PROPOSALS_DRIVE_FOLDER_URL), "feedbackForm": bool(settings.FEEDBACK_FORM_URL)}
            return json.dumps({**res.json(), "mcp": mcp}, indent=2)
        except Exception as exc:
            return unreachable(exc)

    @server.tool(
        name="im_bank_load",
        title="Load the question bank (admin)",
        description=(
            "Loads the master question bank into the IM MCP database from a CSV download of the bank's "
            "Project Scope tab, saved in the repo's data/ folder (no other files can be read). "
            "By default this is a dry run: it reports new, changed, deactivated and invalid questions and "
            "changes nothing. Always show the dry-run report to the user, and only call again with "
            "apply=true after they explicitly confirm. If file is not given, the newest .csv in data/ is used."
        ),
    )
    async def im_bank_load(file: str | None = None, apply: bool = False) -> str:
        try:
            path = pick_csv(data_dir(settings), file)
        except (ValueError, FileNotFoundError) as exc:
            return str(exc)
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        body = {
            "csv": path.read_text(encoding="utf-8-sig"),
            "source_ref": f"{path.name} (modified {modified})",
            "apply": apply,
        }
        try:
            res = await call("POST", "/bank/loads", body, timeout=60)
        except Exception as exc:
            return unreachable(exc)
        if res.status_code != 200:
            return f"The app server refused the load (HTTP {res.status_code}): {res.text[:2000]}"
        return json.dumps({"file": path.name, **res.json()}, indent=2, ensure_ascii=False)

    @server.tool(
        name="im_scope_start",
        title="Start a scope (/ops-create-scope step 1)",
        description=(
            "Starts a /ops-create-scope run. A scope has one or more project tracks (e.g. 'Ecommerce US' and "
            "'In-person payments UK'), each with its own tags and its own tab in the sheet. For one track, pass "
            "the tags directly; for several, pass `tracks` (name + tags each) and leave the tags empty. The server "
            "selects the bank questions that match each track's tags and, if the IM gave context, our model adds "
            "questions on topics the context mentions, per track. Pass the IM's context as they wrote it; it is "
            "used for matching and never stored. An empty list for a tag means all values; a question with no "
            "value for a tag applies to everyone; priorities and subsections limit everything. Returns a draft_id, "
            "per track the counts of tag matches and the questions added by topic (with reasons, to show the IM "
            "for confirmation), questions drafted for topics no bank question covers (gap_questions, with NEW- IDs, "
            "added under 'Suggested additions' in the first tab) and master_sheet_url, the master bank to copy. "
            f"If it returns pending with a job_id (our model is still working), call im_scope_wait."
        ),
    )
    async def im_scope_start(
        context: str | None = None,
        merchant_name: str | None = None,
        tracks: list[TrackArg] | None = None,
        channels: list[E.Channel] | None = None,
        pillars: list[E.Pillar] | None = None,
        categories: list[E.Category] | None = None,
        platforms: list[E.Platform] | None = None,
        priorities: list[Literal[1, 2, 3]] | None = None,
        subsections: list[E.Subsection] | None = None,
    ) -> str:
        tags = {
            "channels": channels or [], "pillars": pillars or [], "categories": categories or [],
            "platforms": platforms or [], "priorities": priorities or [], "subsections": subsections or [],
        }
        body = {"tags": tags, "tracks": [t.body() for t in tracks or []], "context": context,
                "merchant_name": merchant_name}
        return await job_reply("POST", "/scope/jobs", body, extra=local)

    @server.tool(
        name="im_scope_wait",
        title="Wait for im_scope_start to finish",
        description=(
            "When im_scope_start returns pending with a job_id, call this with the job_id. It waits up to "
            f"{WAIT_SECONDS} seconds and returns the same result im_scope_start would have, or pending again."
        ),
    )
    async def im_scope_wait(job_id: str) -> str:
        try:
            uuid.UUID(job_id)
        except ValueError:
            return "job_id should be the job_id returned by im_scope_start."
        return await job_reply("GET", f"/scope/jobs/{job_id}", extra=local)

    @server.tool(
        name="im_scope_sheet_plan",
        title="Plan the scope sheet (/ops-create-scope step 2)",
        description=(
            "After copying the master bank: give the draft_id, the copy's Project Scope tab sheetId and "
            "columnCount, its column A exactly as read (starting with the 'id' header, '' for empty cells), its "
            "header row (row 1, as read), the tab's basicFilter exactly as read if it has one (basic_filter), "
            "sheet_ids (every tab's sheetId in the copy, in tab order; needed with several tracks), and the IM's "
            "changes: remove_ids and add_ids apply to every track; `tracks` holds changes to one track only "
            "(by name). NEW- IDs can be removed too. Returns `requests`: send them unchanged, in one Sheets batch "
            "update on the copy. They rename the Project Scope tab to the first track, make a tab per further "
            "track, and in each tab delete the rows that aren't in that track, add a found_by column, order and "
            "group the rows by section, and keep the tab's filter. Never compute row numbers yourself."
        ),
    )
    async def im_scope_sheet_plan(
        draft_id: str,
        tab_sheet_id: int,
        column_count: int,
        id_column: list[str],
        header_row: list[str] | None = None,
        basic_filter: dict | None = None,
        sheet_ids: list[int] | None = None,
        remove_ids: list[str] | None = None,
        add_ids: list[str] | None = None,
        tracks: list[TrackChangesArg] | None = None,
    ) -> str:
        body = {
            "tab_sheet_id": tab_sheet_id, "column_count": column_count, "id_column": id_column,
            "header_row": header_row or [], "basic_filter": basic_filter or None, "sheet_ids": sheet_ids or [],
            "remove_ids": remove_ids or [], "add_ids": add_ids or [],
            "tracks": [t.model_dump() for t in tracks or []],
        }
        try:
            path = run_path(draft_id, "sheet-plan")
        except ValueError:
            return "draft_id should be the draft_id returned by im_scope_start."
        return await post(path, body, compact=True)

    @server.tool(
        name="im_scope_record",
        title="Record the scope (/ops-create-scope step 3)",
        description=(
            "After the batch update: give the draft_id, the merchant name, the new sheet's ID and link, and "
            "column A of every track's tab read back after the edit (`tabs`, each with the tab's title; for a "
            "one-track scope, sheet_question_ids alone is fine). Records the run and the tracks, checks each tab "
            "against its track and returns a summary (counts by subsection and by how each question was found, "
            "per track), any mismatches and the feedback form link to show the IM. Pass share_new_questions=true "
            "only if the IM agreed to share drafted questions for review. The call-notes prompt is a separate step "
            "the IM is offered afterwards (im_scope_call_prompt)."
        ),
    )
    async def im_scope_record(
        draft_id: str, merchant_name: str, sheet_id: str, sheet_url: str,
        sheet_question_ids: list[str] | None = None, tabs: list[TabArg] | None = None,
        share_new_questions: bool = False,
    ) -> str:
        body = {"merchant_name": merchant_name, "sheet_id": sheet_id, "sheet_url": sheet_url,
                "sheet_question_ids": sheet_question_ids or [], "tabs": [t.model_dump() for t in tabs or []],
                "share_new_questions": share_new_questions}
        try:
            path = run_path(draft_id, "record")
        except ValueError:
            return "draft_id should be the draft_id returned by im_scope_start."
        return await post(path, body)

    @server.tool(
        name="im_scope_call_prompt",
        title="Add the call-notes prompt to the scope sheet (/ops-create-scope, after the reply)",
        description=(
            "Only when the IM says yes to the offer after the sheet is made: adds a 'Call prompt' tab to the "
            "recorded scope sheet holding the call-notes prompt (the scope's questions by ID, grouped by track; "
            "priority 1 unless priorities says otherwise, [] for all), so the IM copies it from the sheet. Pass the "
            "draft_id and sheet_ids (every tab's sheetId in the sheet now, in tab order). Returns `requests` to send "
            "unchanged in one Sheets batch update, and `url`, the link to the new tab to show the IM. Asking again "
            "returns the same tab with no requests."
        ),
    )
    async def im_scope_call_prompt(draft_id: str, sheet_ids: list[int], priorities: list[Literal[1, 2, 3]] | None = None) -> str:
        try:
            path = run_path(draft_id, "call-prompt")
        except ValueError:
            return "draft_id should be the draft_id returned by im_scope_start."
        return await post(path, {"sheet_ids": sheet_ids, "priorities": [1] if priorities is None else priorities}, compact=True)

    @server.tool(
        name="im_inputs_list",
        title="List saved merchant material",
        description=(
            "Lists the text files in the IM MCP's inputs/ folder, where an IM can save long material (such as a "
            "call transcript) for /ops-answer-scope instead of pasting it. Returns names, sizes and dates."
        ),
    )
    async def im_inputs_list() -> str:
        folder = inputs_dir(settings)
        if not folder.is_dir():
            return json.dumps({"folder": str(folder), "files": [], "note": "The folder doesn't exist yet."})
        files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        return json.dumps({"folder": str(folder), "files": [
            {"file": p.name, "kb": round(p.stat().st_size / 1000, 1),
             "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")}
            for p in files]}, indent=2)

    @server.tool(
        name="im_answers_start",
        title="Find scope answers in merchant material (/ops-answer-scope step 1)",
        description=(
            "Give the scope sheet as read (its file ID; the tab being filled: its title (tab_title, the track's "
            "name; a one-track scope has the tab Project Scope), sheetId, columnCount and rowCount; "
            "the header row; column A; and `columns`: the answer column plus any source, confidence, status and "
            "ai_note columns, each as read starting with its header), the NEW- rows with their current question "
            "text, the tab's basicFilter if it has one, and the merchant material: pasted text as `material`, or "
            "files saved in the inputs/ folder as `files`. Our model finds answers and new questions; the material "
            "is used for this run only and never stored. Returns a draft_id, a short summary and `requests`: send "
            "them unchanged, in one Sheets batch update on the sheet. They fill only empty answers, add review "
            "columns and a 'Suggested additions' section. Never compute row numbers yourself."
        ),
    )
    async def im_answers_start(
        sheet_id: str,
        tab_sheet_id: int,
        column_count: int,
        row_count: int,
        header_row: list[str],
        id_column: list[str],
        columns: dict[str, list[str]],
        material: list[MaterialArg] | None = None,
        files: list[FileArg] | None = None,
        new_rows: list[NewRowArg] | None = None,
        basic_filter: dict | None = None,
        merchant_name: str | None = None,
        tab_title: str = "Project Scope",
    ) -> str:
        pieces = [m.model_dump() for m in material or []]
        folder = inputs_dir(settings)
        for f in files or []:
            try:
                pieces.append({"label": f.label, "kind": f.kind, "text": read_input(folder, f.file)})
            except (ValueError, FileNotFoundError) as exc:
                return str(exc)
        if not pieces:
            return ("Give the merchant material: paste it as `material`, or save long material as a text file in "
                    f"{folder} and pass it as `files`.")
        body = {
            "sheet_id": sheet_id, "merchant_name": merchant_name, "tab_title": tab_title, "tab_sheet_id": tab_sheet_id,
            "column_count": column_count, "row_count": row_count, "header_row": header_row,
            "id_column": id_column, "columns": columns,
            "new_rows": [r.model_dump() for r in new_rows or []], "basic_filter": basic_filter or None,
            "material": pieces,
        }
        return await job_reply("POST", "/answers/jobs", body)

    @server.tool(
        name="im_answers_wait",
        title="Wait for im_answers_start to finish",
        description=(
            "When im_answers_start returns pending with a job_id, call this with the job_id. It waits up to "
            f"{WAIT_SECONDS} seconds and returns the same result im_answers_start would have, or pending again."
        ),
    )
    async def im_answers_wait(job_id: str) -> str:
        try:
            job = uuid.UUID(job_id)
        except ValueError:
            return "job_id should be the job_id returned by im_answers_start."
        return await job_reply("GET", f"/answers/jobs/{job}")

    @server.tool(
        name="im_answers_record",
        title="Record the answers run (/ops-answer-scope step 2)",
        description=(
            "After the batch update: give the draft_id, the sheet's link and its column A read back after the edit, "
            "and share_new_questions=true only if the IM agreed to share the new questions for review. Checks the "
            "additions are in the sheet, records the run, sends new questions to the review queue (when that's "
            "switched on and the IM agreed), and returns the counts, the open priority-1 questions to ask next, and the "
            "feedback form link to show the IM."
        ),
    )
    async def im_answers_record(draft_id: str, sheet_url: str, id_column: list[str],
                                share_new_questions: bool = False) -> str:
        try:
            path = run_path(draft_id, "record", base="/answers/runs")
        except ValueError:
            return "draft_id should be the draft_id returned by im_answers_start."
        return await post(path, {"sheet_url": sheet_url, "id_column": id_column,
                                 "share_new_questions": share_new_questions})

    @server.tool(
        name="im_proposal_start",
        title="Start a solution proposal (/ops-create-solution step 1)",
        description=(
            "Starts a /ops-create-solution run from the scope sheet. Pass the sheet's file ID and every track tab "
            "(its title, column A, and the answer, status, source and question columns as read). The server picks "
            "the answers to use (the IM's own win; suggested ones are used but flagged; rejected are skipped) and "
            "builds a research brief per track from the knowledge graph: the requirements, the nearest documentation "
            "pages and flow diagrams, the known designs, and instructions. Then YOU research and draft section 3 per "
            "track (and 1.4/1.5) following the instructions, and call im_proposal_plan with the draft. Returns a "
            "draft_id, the merchant, the answers per track, the open priority-1 questions and the briefs."
        ),
    )
    async def im_proposal_start(sheet_id: str, tabs: list[ProposalTabArg], merchant_name: str | None = None,
                                max_links: int = 8) -> str:
        body = {"sheet_id": sheet_id, "merchant_name": merchant_name, "max_links": max_links,
                "tabs": [t.model_dump() for t in tabs]}
        return await post("/proposal/runs", body, timeout=90, compact=True, extra=local)

    @server.tool(
        name="im_proposal_plan",
        title="Plan the proposal document (/ops-create-solution step 2)",
        description=(
            "After the research: give the draft_id, the same tabs as at start, your draft "
            "({introduction: {background, goals}, tracks: [{name, technical_considerations: [paragraphs], "
            "integration_design: [paragraphs], links: [urls]}]}) and the copy's outline: one item per element of "
            "the document body, in order, each with its startIndex as `s` and endIndex as `e`: a paragraph "
            "{s, e, text, style} (text without the final newline, cut to 40 characters unless it contains '{{'; "
            "style = namedStyleType), a table {s, e, rows: [{s, e, cells: [{s, e, text}]}]}, anything else "
            "{s, e, kind}. The server checks the draft (known sections, lengths, links only from the brief or the "
            "docs site) and the outline, and returns the exact Docs batchUpdate `requests` to send unchanged. "
            "If it refuses, fix what it names and call again."
        ),
    )
    async def im_proposal_plan(draft_id: str, tabs: list[ProposalTabArg], draft: dict, outline: list[dict]) -> str:
        try:
            path = run_path(draft_id, "doc-plan", base="/proposal/runs")
        except ValueError:
            return "draft_id should be the draft_id returned by im_proposal_start."
        return await post(path, {"tabs": [t.model_dump() for t in tabs], "draft": draft, "outline": outline},
                          timeout=60, compact=True)

    @server.tool(
        name="im_proposal_record",
        title="Record the proposal run (/ops-create-solution step 3)",
        description=(
            "After the batch update: give the draft_id, the copy's file ID and link, and any {{tokens}} you saw left "
            "in the document (normally none). Records the run and the document for later ingestion, and returns the "
            "things to tell the IM: suggested answers used, open priority-1 questions, whether a diagram was placed, "
            "and the feedback form link."
        ),
    )
    async def im_proposal_record(draft_id: str, doc_id: str, doc_url: str, leftover_tokens: list[str] | None = None) -> str:
        try:
            path = run_path(draft_id, "record", base="/proposal/runs")
        except ValueError:
            return "draft_id should be the draft_id returned by im_proposal_start."
        return await post(path, {"doc_id": doc_id, "doc_url": doc_url, "leftover_tokens": leftover_tokens or []})

    @server.tool(
        name="im_graph_load_docs",
        title="Load the Adyen doc pages into the graph (admin)",
        description=(
            "Loads the Adyen documentation pages into the IM MCP's graph as asset nodes (link, title, one-line "
            "description, tags, embedding; never the page content). The app server reads the docs index and the rules "
            f"file from the repo's data/graph/ folder (default {DOC_RULES_FILE}; no other files can be read). By default "
            "this is a dry run: it reports new, changed, deprecated and restored pages and changes nothing. Always show "
            "the dry-run report to the user, and only call again with apply=true after they explicitly confirm. If it "
            "returns pending with a job_id, call im_graph_wait."
        ),
    )
    async def im_graph_load_docs(file: str | None = None, apply: bool = False) -> str:
        try:
            path = pick_csv(data_dir(settings) / "graph", file or DOC_RULES_FILE)
        except (ValueError, FileNotFoundError) as exc:
            return str(exc)
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        body = {
            "rules_csv": path.read_text(encoding="utf-8-sig"),
            "source_ref": f"{path.name} (modified {modified})",
            "apply": apply,
        }
        return await job_reply("POST", "/graph/loads/docs", body)

    @server.tool(
        name="im_graph_load_diagrams",
        title="Load the flow diagrams into the graph (admin)",
        description=(
            "Loads the curated flow diagrams into the IM MCP's graph as asset nodes, from a CSV in the repo's "
            f"data/graph/ folder (default {DIAGRAMS_FILE}; columns title, url, description, channels, pillars, "
            "categories, platforms, note; the url must be a public https link to a PNG, JPEG or GIF). Rows that are "
            "no longer in the file are deprecated, never deleted. By default a dry run: show the report to the user and "
            "only call again with apply=true after they explicitly confirm. If it returns pending, call im_graph_wait."
        ),
    )
    async def im_graph_load_diagrams(file: str | None = None, apply: bool = False) -> str:
        try:
            path = pick_csv(data_dir(settings) / "graph", file or DIAGRAMS_FILE)
        except (ValueError, FileNotFoundError) as exc:
            return str(exc)
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        body = {"csv": path.read_text(encoding="utf-8-sig"), "source_ref": f"{path.name} (modified {modified})",
                "apply": apply}
        return await job_reply("POST", "/graph/loads/diagrams", body)

    @server.tool(
        name="im_graph_wait",
        title="Wait for a graph load to finish",
        description=(
            "When im_graph_load_docs or im_graph_load_diagrams returns pending with a job_id, call this with the "
            f"job_id. It waits up to {WAIT_SECONDS} seconds and returns the load report, or pending again."
        ),
    )
    async def im_graph_wait(job_id: str) -> str:
        try:
            uuid.UUID(job_id)
        except ValueError:
            return "job_id should be the job_id returned by the graph load tool."
        return await job_reply("GET", f"/graph/jobs/{job_id}")

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
