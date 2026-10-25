import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from imcp.mcp_server import build_server
from tests.test_health import _tool_text

RUN = "6f1c2a1e-0000-4000-8000-000000000001"


def stub(received: list, status: int = 200):
    app = FastAPI()

    @app.post("/scope/runs")
    async def start(request: Request):
        received.append(("start", await request.json()))
        return JSONResponse({"draft_id": RUN}, status_code=status)

    @app.post("/scope/runs/{run_id}/{step}")
    async def step(run_id: str, step: str, request: Request):
        received.append((step, run_id, await request.json()))
        return JSONResponse({"step": step, "requests": [{"deleteDimension": {}}]}, status_code=status)

    @app.get("/health")
    async def health(check_model: bool = False):
        received.append(("health", check_model))
        return {"status": "ok"}

    return app


def server_for(received, status=200):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=stub(received, status)), base_url="http://app.test")
    return build_server(client=client)


@pytest.mark.anyio
async def test_tools_are_listed():
    names = {t.name for t in await server_for([]).list_tools()}
    assert {"im_health", "im_bank_load", "im_scope_start", "im_scope_sheet_plan", "im_scope_record"} <= names


@pytest.mark.anyio
async def test_start_sends_tags_context_and_name():
    received = []
    await server_for(received).call_tool("im_scope_start", {
        "context": "They migrate tokens.", "merchant_name": "Example Co", "pillars": ["PFS"], "priorities": [1, 2]})
    [(kind, body)] = received
    assert body["context"] == "They migrate tokens." and body["merchant_name"] == "Example Co"
    assert body["tags"] == {"channels": [], "pillars": ["PFS"], "categories": [], "platforms": [],
                            "priorities": [1, 2], "subsections": []}


@pytest.mark.anyio
async def test_sheet_plan_goes_to_the_draft_and_comes_back_compact():
    received = []
    text = _tool_text(await server_for(received).call_tool("im_scope_sheet_plan", {
        "draft_id": RUN, "tab_sheet_id": 7, "column_count": 12, "id_column": ["id", "ID-0001"],
        "remove_ids": ["ID-0002"]}))
    assert received[0][:2] == ("sheet-plan", RUN) and received[0][2]["remove_ids"] == ["ID-0002"]
    assert received[0][2]["add_ids"] == [] and " " not in text and json.loads(text)["step"] == "sheet-plan"
    assert received[0][2]["basic_filter"] is None


@pytest.mark.anyio
async def test_sheet_plan_passes_the_tabs_filter_as_read():
    received = []
    flt = {"range": {"sheetId": 7, "startRowIndex": 0}, "filterSpecs": [{"columnIndex": 6, "filterCriteria": {"hiddenValues": ["2"]}}]}
    await server_for(received).call_tool("im_scope_sheet_plan", {
        "draft_id": RUN, "tab_sheet_id": 7, "column_count": 12, "id_column": ["id"], "basic_filter": flt})
    assert received[0][2]["basic_filter"] == flt


@pytest.mark.anyio
async def test_record_goes_to_the_draft():
    received = []
    await server_for(received).call_tool("im_scope_record", {
        "draft_id": RUN, "merchant_name": "Example Co", "sheet_id": "1AbCdEfGhIjK",
        "sheet_url": "https://docs.google.com/x", "sheet_question_ids": ["id", "ID-0001"]})
    assert received[0][:2] == ("record", RUN) and received[0][2]["sheet_id"] == "1AbCdEfGhIjK"


@pytest.mark.anyio
async def test_bad_draft_id_never_reaches_the_server():
    received = []
    text = _tool_text(await server_for(received).call_tool("im_scope_record", {
        "draft_id": "../bank/loads", "merchant_name": "x", "sheet_id": "1AbCdEfGhIjK", "sheet_url": "u",
        "sheet_question_ids": []}))
    assert "draft_id should be" in text and received == []


@pytest.mark.anyio
async def test_rejections_are_passed_back_to_claude():
    text = _tool_text(await server_for([], status=422).call_tool("im_scope_start", {}))
    assert "HTTP 422" in text


@pytest.mark.anyio
async def test_health_can_ask_for_a_model_check():
    received = []
    await server_for(received).call_tool("im_health", {"check_model": True})
    assert received == [("health", True)]


@pytest.mark.anyio
async def test_unknown_tag_values_are_refused_by_the_tool():
    with pytest.raises(Exception):
        await server_for([]).call_tool("im_scope_start", {"channels": ["POS"]})
