import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from imcp.config import McpSettings
from imcp.mcp_server import build_server
from tests.test_health import _tool_text

DRAFT_ID = "11111111-1111-1111-1111-111111111111"
TABS = [{"name": "Project Scope", "id_column": ["id", "ID-0001"], "columns": {"answer": ["answer", "UK"]}}]


def stub_app(received: list):
    app = FastAPI()

    @app.post("/proposal/runs")
    async def start(request: Request):
        received.append(("start", await request.json()))
        return JSONResponse({"draft_id": DRAFT_ID, "tracks": []})

    @app.post("/proposal/runs/{run_id}/doc-plan")
    async def plan(run_id: str, request: Request):
        received.append(("plan", run_id, await request.json()))
        return JSONResponse({"requests": [{"replaceAllText": {}}]})

    @app.post("/proposal/runs/{run_id}/record")
    async def record(run_id: str, request: Request):
        received.append(("record", run_id, await request.json()))
        return JSONResponse({"ok": True})

    return app


def server_for(received):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=stub_app(received)), base_url="http://app.test")
    return build_server(McpSettings(), client=client)


@pytest.mark.anyio
async def test_start_plan_record_pass_through():
    received = []
    server = server_for(received)
    text = _tool_text(await server.call_tool("im_proposal_start", {"sheet_id": "1SheetIdXXXXX", "tabs": TABS, "merchant_name": "Acme"}))
    assert json.loads(text)["draft_id"] == DRAFT_ID
    assert received[0][1]["tabs"][0]["columns"]["answer"] == ["answer", "UK"] and received[0][1]["max_links"] == 8
    draft = {"introduction": {}, "tracks": [{"name": "Project Scope", "links": []}]}
    outline = [{"s": None, "e": 1, "kind": "sectionBreak"}, {"s": 1, "e": 5, "text": "abc", "style": "NORMAL_TEXT"}]
    text = _tool_text(await server.call_tool("im_proposal_plan", {"draft_id": DRAFT_ID, "tabs": TABS, "draft": draft, "outline": outline}))
    assert json.loads(text)["requests"] and received[1][1] == DRAFT_ID and received[1][2]["outline"] == outline
    text = _tool_text(await server.call_tool("im_proposal_record", {"draft_id": DRAFT_ID, "doc_id": "1DocIdXXXXXX",
                                                                   "doc_url": "https://docs.google.com/document/d/1DocIdXXXXXX/edit"}))
    assert json.loads(text)["ok"] and received[2][2]["leftover_tokens"] == []


@pytest.mark.anyio
async def test_bad_draft_id_is_caught_before_any_request():
    received = []
    server = server_for(received)
    assert "draft_id should be" in _tool_text(await server.call_tool("im_proposal_plan", {"draft_id": "nope", "tabs": TABS, "draft": {}, "outline": []}))
    assert "draft_id should be" in _tool_text(await server.call_tool("im_proposal_record", {"draft_id": "nope", "doc_id": "1DocIdXXXXXX", "doc_url": "x"}))
    assert received == []
