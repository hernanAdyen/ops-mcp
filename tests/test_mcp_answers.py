import json

import httpx
import pytest
from fastapi import FastAPI, Request

from imcp.config import McpSettings
from imcp.mcp_server import build_server
from tests.test_health import _tool_text

RUN = "6f1c2a1e-0000-4000-8000-000000000002"
JOB = "6f1c2a1e-0000-4000-8000-00000000000a"
SHEET = {"sheet_id": "1AbCdEfGhIjK", "tab_sheet_id": 7, "column_count": 13, "row_count": 6,
         "header_row": ["id", "answer"], "id_column": ["id", "ID-0001"], "columns": {"answer": ["answer", ""]}}


def stub(received: list, pending_polls: int = 0):
    """The app server's job endpoints: pending for `pending_polls` polls, then the result."""
    app = FastAPI()
    state = {"polls": 0}
    done = {"job_id": JOB, "pending": False, "draft_id": RUN, "requests": [{"updateCells": {}}]}

    @app.post("/answers/jobs")
    async def start(request: Request, wait: float):
        received.append(("start", await request.json(), wait))
        return {"job_id": JOB, "pending": True} if pending_polls else done

    @app.get("/answers/jobs/{job_id}")
    async def poll(job_id: str, wait: float):
        received.append(("poll", job_id, wait))
        state["polls"] += 1
        return {"job_id": job_id, "pending": True} if state["polls"] < pending_polls else done

    @app.post("/answers/runs/{run_id}/record")
    async def record(run_id: str, request: Request):
        received.append(("record", run_id, await request.json()))
        return {"ok": True}

    return app


def server_for(received, folder, pending_polls=0):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=stub(received, pending_polls)), base_url="http://app.test")
    return build_server(settings=McpSettings(IMCP_INPUTS_DIR=folder), client=client)


@pytest.mark.anyio
async def test_pasted_material_and_saved_files_are_sent_together(tmp_path):
    (tmp_path / "call-1.txt").write_text("Transcript: we need tokens migrated.", encoding="utf-8")
    received = []
    text = _tool_text(await server_for(received, tmp_path).call_tool("im_answers_start", {
        **SHEET, "material": [{"label": "Call summary", "kind": "summary", "date": "2026-10-24", "text": "US only."}],
        "files": [{"label": "Call 1 transcript", "file": "call-1.txt"}],
        "new_rows": [{"id": "NEW-0001", "question": "Two payers?"}],
        "sheet_tabs": [{"sheet_id": 0, "title": "Project Scope"}, {"sheet_id": 1001, "title": "Scope log"}]}))
    [(kind, body, wait)] = received
    assert wait == 40
    assert body["material"] == [
        {"label": "Call summary", "kind": "summary", "date": "2026-10-24", "text": "US only."},
        {"label": "Call 1 transcript", "kind": "transcript", "date": None, "text": "Transcript: we need tokens migrated."}]
    assert body["new_rows"] == [{"id": "NEW-0001", "question": "Two payers?"}] and body["basic_filter"] is None
    assert body["sheet_tabs"] == [{"sheet_id": 0, "title": "Project Scope"}, {"sheet_id": 1001, "title": "Scope log"}]
    assert json.loads(text)["draft_id"] == RUN and " " not in text  # compact


@pytest.mark.anyio
async def test_only_text_files_inside_the_inputs_folder_can_be_read(tmp_path):
    (tmp_path.parent / "outside.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "deck.pdf").write_bytes(b"%PDF")
    received = []
    server = server_for(received, tmp_path)
    for name in ("../outside.txt", "deck.pdf"):
        text = _tool_text(await server.call_tool("im_answers_start", {**SHEET, "files": [{"label": "x", "file": name}]}))
        assert "Only text files" in text
    text = _tool_text(await server.call_tool("im_answers_start", {**SHEET, "files": [{"label": "x", "file": "nope.txt"}]}))
    assert "There's no file named nope.txt" in text and received == []


@pytest.mark.anyio
async def test_no_material_asks_for_it(tmp_path):
    received = []
    text = _tool_text(await server_for(received, tmp_path).call_tool("im_answers_start", SHEET))
    assert "Give the merchant material" in text and received == []


@pytest.mark.anyio
async def test_record_goes_to_the_run_and_bad_ids_stop_early(tmp_path):
    received = []
    server = server_for(received, tmp_path)
    await server.call_tool("im_answers_record", {"draft_id": RUN, "sheet_url": "u", "id_column": ["id"]})
    assert received == [("record", RUN, {"sheet_url": "u", "id_column": ["id"], "share_new_questions": False})]
    text = _tool_text(await server.call_tool("im_answers_record", {"draft_id": "../x", "sheet_url": "u", "id_column": []}))
    assert "draft_id should be" in text and len(received) == 1


@pytest.mark.anyio
async def test_inputs_are_listed(tmp_path):
    (tmp_path / "call-1.txt").write_text("x", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"png")
    listed = json.loads(_tool_text(await server_for([], tmp_path).call_tool("im_inputs_list", {})))
    assert [f["file"] for f in listed["files"]] == ["call-1.txt"]
    missing = json.loads(_tool_text(await server_for([], tmp_path / "missing").call_tool("im_inputs_list", {})))
    assert missing["files"] == [] and "doesn't exist" in missing["note"]


@pytest.mark.anyio
async def test_a_slow_run_returns_a_job_to_wait_on(tmp_path):
    received = []
    server = server_for(received, tmp_path, pending_polls=2)
    first = json.loads(_tool_text(await server.call_tool("im_answers_start", {**SHEET, "material": [{"label": "x", "text": "y"}]})))
    assert first["pending"] is True and first["job_id"] == JOB
    again = json.loads(_tool_text(await server.call_tool("im_answers_wait", {"job_id": JOB})))
    assert again["pending"] is True
    done = json.loads(_tool_text(await server.call_tool("im_answers_wait", {"job_id": JOB})))
    assert done["draft_id"] == RUN and [r[0] for r in received] == ["start", "poll", "poll"]
    bad = _tool_text(await server.call_tool("im_answers_wait", {"job_id": "../x"}))
    assert "job_id should be" in bad
