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

    async def post(path: str, body: dict, timeout: float = 30, compact: bool = False) -> str:
        try:
            res = await call("POST", path, body, timeout=timeout)
        except Exception as exc:
            return unreachable(exc)
        if res.status_code != 200:
            return f"The app server refused this (HTTP {res.status_code}): {res.text[:4000]}"
        if compact:
            return json.dumps(res.json(), ensure_ascii=False, separators=(",", ":"))
        return json.dumps(res.json(), indent=2, ensure_ascii=False)

    async def job_reply(method: str, path: str, body: dict | None = None) -> str:
        """A job on the app server: its result, or pending with the job ID to ask again with."""
        try:
            res = await call(method, path, body, timeout=WAIT_SECONDS + 20, params={"wait": WAIT_SECONDS})
        except Exception as exc:
            return unreachable(exc)
        if res.status_code != 200:
            return f"The app server refused this (HTTP {res.status_code}): {res.text[:4000]}"
        data = res.json()
        if data.get("pending"):
            return json.dumps({"pending": True, "job_id": data["job_id"],
                               "next": "Our model is still working. Call im_answers_wait with this job_id."})
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

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
            return json.dumps(res.json(), indent=2)
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
        title="Start a scope (/create-scope step 1)",
        description=(
            "Starts a /create-scope run. The server selects the bank questions that match the IM's tags and, "
            "if the IM gave context, our model adds questions on topics the context mentions. Pass the IM's "
            "context as they wrote it; it is used for matching and never stored. An empty list for a tag means "
            "all values; a question with no value for a tag applies to everyone; priorities and subsections "
            "limit everything. Returns a draft_id, counts of the tag matches, the questions added by topic "
            "(with reasons, to show the IM for confirmation), questions drafted for topics no bank question covers "
            "(gap_questions, with NEW- IDs, added under 'Suggested additions') and master_sheet_url, the master "
            "bank to copy."
        ),
    )
    async def im_scope_start(
        context: str | None = None,
        merchant_name: str | None = None,
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
        body = {"tags": tags, "context": context, "merchant_name": merchant_name}
        return await post("/scope/runs", body, timeout=150)

    @server.tool(
        name="im_scope_sheet_plan",
        title="Plan the scope sheet (/create-scope step 2)",
        description=(
            "After copying the master bank: give the draft_id, the copy's Project Scope tab sheetId and "
            "columnCount, its column A exactly as read (starting with the 'id' header, '' for empty cells), its "
            "header row (row 1, as read), the tab's basicFilter exactly as read if it has one (basic_filter), "
            "and any questions the IM dropped (remove_ids, NEW- IDs included) or asked to add by ID (add_ids). "
            "Returns `requests`: send "
            "them unchanged, in one Sheets batch update on the copy. They delete the rows that aren't in the "
            "scope, add a found_by column, order and group the rows by section, and keep the tab's filter. "
            "Never compute row numbers yourself."
        ),
    )
    async def im_scope_sheet_plan(
        draft_id: str,
        tab_sheet_id: int,
        column_count: int,
        id_column: list[str],
        header_row: list[str] | None = None,
        basic_filter: dict | None = None,
        remove_ids: list[str] | None = None,
        add_ids: list[str] | None = None,
    ) -> str:
        body = {
            "tab_sheet_id": tab_sheet_id, "column_count": column_count, "id_column": id_column,
            "header_row": header_row or [], "basic_filter": basic_filter or None,
            "remove_ids": remove_ids or [], "add_ids": add_ids or [],
        }
        try:
            path = run_path(draft_id, "sheet-plan")
        except ValueError:
            return "draft_id should be the draft_id returned by im_scope_start."
        return await post(path, body, compact=True)

    @server.tool(
        name="im_scope_record",
        title="Record the scope (/create-scope step 3)",
        description=(
            "After the batch update: give the draft_id, the merchant name, the new sheet's ID and link, and "
            "its column A read back after the edit. Records the run, checks the sheet against the scope and "
            "returns a summary (counts by subsection and by how each question was found), any mismatches, "
            "a call_prompt (the scope's questions by ID, for the IM to paste into their call-notes tool; priority 1 "
            "unless call_prompt_priorities says otherwise, [] for all) and the feedback form link to show the IM. "
            "Pass share_new_questions=true only if the IM agreed to share drafted questions for review."
        ),
    )
    async def im_scope_record(
        draft_id: str, merchant_name: str, sheet_id: str, sheet_url: str, sheet_question_ids: list[str],
        share_new_questions: bool = False, call_prompt_priorities: list[Literal[1, 2, 3]] | None = None,
    ) -> str:
        body = {"merchant_name": merchant_name, "sheet_id": sheet_id, "sheet_url": sheet_url,
                "sheet_question_ids": sheet_question_ids, "share_new_questions": share_new_questions,
                "call_prompt_priorities": [1] if call_prompt_priorities is None else call_prompt_priorities}
        try:
            path = run_path(draft_id, "record")
        except ValueError:
            return "draft_id should be the draft_id returned by im_scope_start."
        return await post(path, body)

    @server.tool(
        name="im_inputs_list",
        title="List saved merchant material",
        description=(
            "Lists the text files in the IM MCP's inputs/ folder, where an IM can save long material (such as a "
            "call transcript) for /source-scope-answers instead of pasting it. Returns names, sizes and dates."
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
        title="Find scope answers in merchant material (/source-scope-answers step 1)",
        description=(
            "Give the scope sheet as read (its file ID; the Project Scope tab's sheetId, columnCount and rowCount; "
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
            "sheet_id": sheet_id, "merchant_name": merchant_name, "tab_sheet_id": tab_sheet_id,
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
        title="Record the answers run (/source-scope-answers step 2)",
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

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
